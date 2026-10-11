from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from signalforge.config.strategy_registry import StrategySelection
from signalforge.domain.ids import InstrumentId
from signalforge.domain.market import CandleQuality
from signalforge.domain.money import Price
from signalforge.domain.time import CandleInterval, IST, to_utc
from signalforge.research.historical_bars import (
    CorporateActionPolicy,
    HistoricalBar,
    HistoricalBarDataset,
    HistoricalBarResearchRunner,
    HistoricalDatasetManifest,
    aggregate_one_minute_to_five_minute,
    load_historical_bar_fixture,
)

INSTRUMENT = InstrumentId("NSE:TEST")
VERSION = "historical-bar-v1"


def _bar(
    minute: int,
    *,
    close: str | None = None,
    start_hour: int = 9,
) -> HistoricalBar:
    start = datetime(2026, 10, 9, start_hour, minute, tzinfo=IST)
    base = Decimal(str(100 + minute))
    close_value = base + Decimal("1") if close is None else Decimal(close)
    return HistoricalBar(
        instrument_id=INSTRUMENT,
        interval=CandleInterval(start=start, end=start + timedelta(minutes=1)),
        open=Price(base),
        high=Price(max(base + Decimal("2"), close_value)),
        low=Price(min(base - Decimal("1"), close_value)),
        close=Price(close_value),
        volume=1000 + minute,
        quality=CandleQuality.VALID,
        source_provider="fixture",
        source_record_count=1,
        provider_timestamp_raw=start.isoformat(),
        provider_timestamp_interpreted=start,
        canonicalisation_version=VERSION,
    )


def _bars(start_minute: int, count: int) -> tuple[HistoricalBar, ...]:
    return tuple(_bar(start_minute + offset) for offset in range(count))


def _manifest(
    bars: tuple[HistoricalBar, ...],
    *,
    duplicates: int = 0,
    acquired_at: datetime | None = None,
    canonical_row_count: int | None = None,
) -> HistoricalDatasetManifest:
    first = bars[0].interval.start
    last = bars[-1].interval.end
    return HistoricalDatasetManifest(
        provider="fixture",
        acquisition_adapter="test-fixture",
        acquisition_version="1",
        requested_instrument="NSE:TEST",
        resolved_provider_instrument="NSE:TEST",
        instrument_id=INSTRUMENT,
        requested_start=first,
        requested_end=last,
        returned_start=first,
        returned_end=last,
        interval_minutes=1,
        acquired_at=acquired_at or datetime(2026, 10, 11, 12, 0, tzinfo=IST),
        provider_timestamp_representation="ISO-8601",
        timezone_interpretation="Asia/Kolkata interval-start",
        canonicalisation_version=VERSION,
        raw_row_count=len(bars),
        canonical_row_count=(
            len(bars) - duplicates if canonical_row_count is None else canonical_row_count
        ),
        missing_interval_count=max(0, 375 - (len(bars) - duplicates)),
        duplicate_observation_count=duplicates,
        corrupt_rejected_count=0,
        corporate_action_policy=CorporateActionPolicy.UNKNOWN,
        limitations=("test fixture",),
    )


def _dataset(bars: tuple[HistoricalBar, ...]) -> HistoricalBarDataset:
    return HistoricalBarDataset(manifest=_manifest(bars), bars=bars)


def test_historical_bar_requires_exact_valid_one_minute_observation() -> None:
    bar = _bar(15)
    assert bar.interval.start == to_utc(datetime(2026, 10, 9, 9, 15, tzinfo=IST))
    assert bar.provider_timestamp_interpreted == bar.interval.start

    with pytest.raises(ValueError, match="exactly one minute"):
        replace(
            bar,
            interval=CandleInterval(
                start=datetime(2026, 10, 9, 9, 15, tzinfo=IST),
                end=datetime(2026, 10, 9, 9, 17, tzinfo=IST),
            ),
        )
    with pytest.raises(ValueError, match="quality must be VALID"):
        replace(bar, quality=CandleQuality.INCOMPLETE)
    with pytest.raises(ValueError, match="volume must not be negative"):
        replace(bar, volume=-1)
    with pytest.raises(ValueError, match="prices must be strictly positive"):
        replace(bar, open=Price(Decimal("0")))


def test_dataset_deduplicates_exact_observation_and_rejects_contradiction() -> None:
    bar = _bar(15)
    duplicate_dataset = HistoricalBarDataset(
        manifest=_manifest((bar, bar), duplicates=1, canonical_row_count=1),
        bars=(bar, bar),
    )
    assert duplicate_dataset.bars == (bar,)

    contradictory = replace(bar, close=Price(bar.close.value + Decimal("1")))
    with pytest.raises(ValueError, match="Contradictory duplicate"):
        HistoricalBarDataset(
            manifest=_manifest((bar, contradictory), duplicates=1, canonical_row_count=1),
            bars=(bar, contradictory),
        )


def test_dataset_rejects_noncanonical_input_order() -> None:
    bars = (_bar(16), _bar(15))
    with pytest.raises(ValueError, match="strict canonical chronological order"):
        HistoricalBarDataset(manifest=_manifest(bars), bars=bars)


def test_complete_five_minute_bucket_has_exact_ohlcv() -> None:
    bars = _bars(15, 5)
    candles = aggregate_one_minute_to_five_minute(_dataset(bars))
    first = candles[0]

    assert len(candles) == 75
    assert first.quality is CandleQuality.VALID
    assert first.open == bars[0].open
    assert first.close == bars[-1].close
    assert first.high == Price(max(item.high.value for item in bars))
    assert first.low == Price(min(item.low.value for item in bars))
    assert first.volume == sum(item.volume for item in bars)


def test_missing_minute_is_incomplete_and_empty_bucket_is_missing() -> None:
    bars = _bars(15, 4)
    candles = aggregate_one_minute_to_five_minute(_dataset(bars))

    assert candles[0].quality is CandleQuality.INCOMPLETE
    assert candles[0].open is not None
    assert candles[1].quality is CandleQuality.MISSING
    assert candles[1].open is None
    assert candles[1].high is None
    assert candles[1].low is None
    assert candles[1].close is None
    assert candles[1].volume is None


def test_dataset_identity_ignores_acquisition_wall_clock_but_changes_with_content() -> None:
    bars = _bars(15, 5)
    first = HistoricalBarDataset(
        manifest=_manifest(
            bars,
            acquired_at=datetime(2026, 10, 11, 12, 0, tzinfo=IST),
        ),
        bars=bars,
    )
    second = HistoricalBarDataset(
        manifest=_manifest(
            bars,
            acquired_at=datetime(2026, 10, 12, 17, 0, tzinfo=IST),
        ),
        bars=bars,
    )
    assert first.dataset_id == second.dataset_id

    changed_bars = (*bars[:-1], replace(bars[-1], volume=bars[-1].volume + 1))
    changed = HistoricalBarDataset(
        manifest=_manifest(changed_bars),
        bars=changed_bars,
    )
    assert changed.dataset_id != first.dataset_id


def test_fixture_loads_and_runs_existing_strategy_indicator_path_deterministically() -> None:
    root = Path(__file__).parents[3]
    dataset = load_historical_bar_fixture(
        root / "examples/research/historical-bars-one-session.json"
    )
    runner = HistoricalBarResearchRunner()
    selection = StrategySelection("intraday_momentum_v1", "1.0.0", {})

    first = runner.run(
        dataset,
        strategy_selection=selection,
        engine_calculation_version="engine-v1",
    )
    second = runner.run(
        dataset,
        strategy_selection=selection,
        engine_calculation_version="engine-v1",
    )

    assert first == second
    assert first.semantic_mapping() == second.semantic_mapping()
    assert first.derived_candles == 75
    assert first.valid_candles == 2
    assert first.missing_candles == 73
    assert first.incomplete_candles == 0
    assert len(first.decisions) == 2
    assert all(not item.indicator_ready for item in first.decisions)


def test_non_valid_bucket_breaks_research_continuity_without_resuming() -> None:
    first_bucket = _bars(15, 5)
    third_bucket = _bars(25, 5)
    bars = first_bucket + third_bucket
    dataset = _dataset(bars)
    result = HistoricalBarResearchRunner().run(
        dataset,
        strategy_selection=StrategySelection(
            "intraday_momentum_v1",
            "1.0.0",
            {},
        ),
        engine_calculation_version="engine-v1",
    )

    assert result.valid_candles == 2
    assert result.missing_candles == 73
    assert len(result.decisions) == 1
    assert result.skipped_after_continuity_break == 1
