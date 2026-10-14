"""SF-081: offline contract compatibility, NOT an NSE acquisition adapter.

Synthetic raw-looking clock values mirror the observed 1m/5m *shape*,
not proprietary prices, provider identity or vendor-wide semantics.
"""
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from signalforge.domain.ids import InstrumentId
from signalforge.domain.market import CandleQuality
from signalforge.domain.money import Price
from signalforge.domain.time import IST, CandleInterval, to_utc
from signalforge.research.historical_bars import (
    CorporateActionPolicy,
    HistoricalBar,
    HistoricalBarDataset,
    HistoricalDatasetManifest,
    aggregate_one_minute_to_five_minute,
)

DAY = datetime(2026, 10, 12, tzinfo=IST)
START = DAY.replace(hour=9, minute=15)
END = DAY.replace(hour=10, minute=15)
INSTRUMENT = InstrumentId("NSE:SF081-SYNTHETIC")
VERSION = "sf081-test-only-clock-proof-v1"


def fake_provider_milliseconds(local_clock: datetime) -> int:
    """Create NSE-wall-clock-shaped milliseconds, deliberately NOT a UTC instant."""
    assert local_clock.tzinfo is IST
    return int(local_clock.replace(tzinfo=UTC).timestamp() * 1000)


def checked_canonical_interval(raw_ms: int, minutes: int) -> CandleInterval:
    """Test-only explicit translation of the observed response convention."""
    if isinstance(raw_ms, bool) or not isinstance(raw_ms, int) or raw_ms % 1000:
        raise ValueError("invalid raw milliseconds")
    if minutes not in (1, 5):
        raise ValueError("unqualified interval")
    # UTC is used only to recover encoded wall-clock fields, NOT as instant.
    wall = datetime.fromtimestamp(raw_ms / 1000, UTC).replace(tzinfo=None)
    open_wall = wall.replace(second=0, microsecond=0)
    if minutes == 5:
        open_wall = open_wall.replace(minute=(open_wall.minute // 5) * 5)
    if wall.replace(second=0, microsecond=0) != open_wall + timedelta(minutes=minutes - 1):
        raise ValueError("raw timestamp is not in the final candle minute")
    opened = open_wall.replace(tzinfo=IST)
    if opened.time() < START.time() or (
        opened + timedelta(minutes=minutes)).time() > DAY.replace(hour=15, minute=30).time():
        raise ValueError("outside regular NSE session")
    return CandleInterval(start=to_utc(opened), end=to_utc(opened + timedelta(minutes=minutes)))


def synthetic_bars() -> tuple[HistoricalBar, ...]:
    records = []
    for offset in range(60):
        local_open = START + timedelta(minutes=offset)
        raw = fake_provider_milliseconds(local_open.replace(second=53 + offset % 7))
        interval = checked_canonical_interval(raw, 1)
        price = Decimal("100") + Decimal(offset) / Decimal("10")
        records.append(HistoricalBar(
            instrument_id=INSTRUMENT, interval=interval,
            open=Price(price), high=Price(price + 1), low=Price(price - 1),
            close=Price(price + Decimal("0.5")), volume=100 + offset,
            quality=CandleQuality.VALID, source_provider="synthetic-clock-contract",
            source_record_count=1, provider_timestamp_raw=str(raw),
            provider_timestamp_interpreted=datetime.fromtimestamp(raw / 1000, UTC).replace(\n                tzinfo=IST).astimezone(UTC),
            canonicalisation_version=VERSION,
        ))
    return tuple(records)


def synthetic_dataset() -> HistoricalBarDataset:
    bars = synthetic_bars()
    manifest = HistoricalDatasetManifest(
        provider="synthetic-clock-contract", acquisition_adapter="none-test-only",
        acquisition_version="0", requested_instrument=str(INSTRUMENT),
        resolved_provider_instrument=str(INSTRUMENT), instrument_id=INSTRUMENT,
        requested_start=START, requested_end=DAY.replace(hour=15, minute=30),
        returned_start=bars[0].interval.start, returned_end=bars[-1].interval.end,
        interval_minutes=1, acquired_at=DAY.replace(hour=16),
        provider_timestamp_representation="wall-clock-encoded epoch milliseconds",
        timezone_interpretation="Asia/Kolkata wall clock, NOT real UTC",
        canonicalisation_version=VERSION,
        expected_session_dates=(DAY.date(),), raw_row_count=60,
        canonical_row_count=60, missing_interval_count=315,
        duplicate_observation_count=0, corrupt_rejected_count=0,
        corporate_action_policy=CorporateActionPolicy.UNKNOWN,
        limitations=("Synthetic contract demonstration; source not selected",),
    )
    return HistoricalBarDataset(manifest=manifest, bars=bars)


def test_observed_1m_to_canonical_utc_full_hour_and_five_minute_alignment():
    dataset = synthetic_dataset()
    assert len(dataset.bars) == 60
    assert dataset.bars[0].interval.start == datetime(2026, 10, 12, 3, 45, tzinfo=UTC)
    assert dataset.bars[-1].interval.end == datetime(2026, 10, 12, 4, 45, tzinfo=UTC)
    assert dataset.bars[0].provider_timestamp_raw != str(
        int(dataset.bars[0].interval.end.timestamp() * 1000))
    derived = aggregate_one_minute_to_five_minute(dataset)
    valid = [bar for bar in derived if bar.quality is CandleQuality.VALID]
    assert len(derived) == 75
    assert len(valid) == 12
    assert valid[0].interval.start == datetime(2026, 10, 12, 3, 45, tzinfo=UTC)
    assert valid[-1].interval.end == datetime(2026, 10, 12, 4, 45, tzinfo=UTC)
    assert sum(bar.quality is CandleQuality.MISSING for bar in derived) == 63
    assert valid[0].volume == sum(100 + i for i in range(5))


def test_observed_five_minute_provider_clock_matches_canonical_derived_bucket():
    valid = [bar for bar in aggregate_one_minute_to_five_minute(synthetic_dataset())
             if bar.quality is CandleQuality.VALID]
    for index, bar in enumerate(valid):
        local_close_clock = START + timedelta(minutes=index * 5 + 4, seconds=53 + index % 7)
        mapped = checked_canonical_interval(fake_provider_milliseconds(local_close_clock), 5)
        assert mapped == bar.interval


@pytest.mark.parametrize("minutes,minute", [(5, 18), (5, 20)])
def test_invalid_five_minute_provider_bucket_is_rejected(minutes: int, minute: int):
    with pytest.raises(ValueError, match="final candle minute"):
        checked_canonical_interval(fake_provider_milliseconds(
            START.replace(minute=minute, second=59)), minutes)


def test_unqualified_interval_and_incorrect_raw_precision_are_rejected():
    raw = fake_provider_milliseconds(START.replace(second=59))
    with pytest.raises(ValueError, match="unqualified"):
        checked_canonical_interval(raw, 10)
    with pytest.raises(ValueError, match="invalid raw milliseconds"):
        checked_canonical_interval(raw + 500, 1)
