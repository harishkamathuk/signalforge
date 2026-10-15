"""SF-079 provisional mapper tests; exclusively synthetic records, never NSE requests."""
import importlib.util
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from signalforge.domain.market import CandleQuality
from signalforge.research.historical_bars import aggregate_one_minute_to_five_minute

PATH = Path(__file__).resolve().parents[2] / "support" / "sf079_provisional_mapper.py"
spec = importlib.util.spec_from_file_location("sf079_provisional_mapper", PATH)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

DAY = date(2026, 10, 12)
INSTRUMENT = "NSE:SF079-SYNTHETIC"
SYMBOL = "SYNTHETIC-EQ"
SHA = "a" * 40


def rows():
    result = []
    for offset in range(60):
        if offset == 7:
            continue  # deliberate missing minute, not fabricated
        wall = datetime(2026, 10, 12, 9, 15, 53, tzinfo=UTC) + timedelta(minutes=offset)
        result.append({
            "instrument": INSTRUMENT, "provider_symbol": SYMBOL,
            "time": int(wall.timestamp()) * 1000,
            "open": "100.00", "high": "101.00", "low": "99.00", "close": "100.50",
            "volume": 100 + offset,
        })
    return result


def convert(records):
    return module.map_synthetic_session(
        records, session_date=DAY, instrument=INSTRUMENT, provider_symbol=SYMBOL,
        acquired_at=datetime(2026, 10, 14, tzinfo=UTC),
        fork_revision=SHA, fixture_sha256=module.fixture_digest(records),
    )


def test_synthetic_mapping_preserves_raw_interpreted_and_canonical_clock():
    dataset = convert(rows())
    assert len(dataset.bars) == 59
    assert dataset.manifest.missing_interval_count == 316
    assert dataset.bars[0].interval.start == datetime(2026, 10, 12, 3, 45, tzinfo=UTC)
    assert dataset.bars[0].provider_timestamp_interpreted == datetime(
        2026, 10, 12, 3, 45, 53, tzinfo=UTC
    )
    assert dataset.bars[0].provider_timestamp_raw == str(rows()[0]["time"])
    assert "SYNTHETIC" in dataset.manifest.limitations[0]
    assert str(dataset.dataset_id) == str(convert(rows()).dataset_id)
    derived = aggregate_one_minute_to_five_minute(dataset)
    assert len(derived) == 75
    assert sum(c.quality is CandleQuality.VALID for c in derived) == 11
    assert sum(c.quality is CandleQuality.INCOMPLETE for c in derived) == 1
    assert sum(c.quality is CandleQuality.MISSING for c in derived) == 63


@pytest.mark.parametrize("mutate", [
    lambda items: items.__setitem__(1, dict(items[1], instrument="NSE:OTHER")),
    lambda items: items.__setitem__(1, dict(items[1], provider_symbol="OTHER-EQ")),
    lambda items: items.__setitem__(1, dict(items[1], time=items[0]["time"])),
    lambda items: items.__setitem__(1, dict(items[1], time=items[1]["time"]+500)),
    lambda items: items.__setitem__(1, dict(items[1], time=items[1]["time"]+60_000*400)),
    lambda items: items.__setitem__(1, dict(items[1], high="98.00")),
    lambda items: items.__setitem__(1, dict(items[1], volume=-1)),
    lambda items: items.__setitem__(1, dict(items[1], open="not-a-decimal")),
])
def test_invalid_rows_fail_closed(mutate):
    fixture = rows()
    mutate(fixture)
    with pytest.raises((ValueError, ArithmeticError)):
        convert(fixture)


def test_unordered_input_fails_closed():
    fixture = rows()
    fixture[1], fixture[2] = fixture[2], fixture[1]
    with pytest.raises(ValueError):
        convert(fixture)


def test_empty_fixture_and_naive_observation_rejected():
    with pytest.raises(ValueError):
        convert([])
    with pytest.raises(ValueError):
        module.map_synthetic_session(rows(), session_date=DAY, instrument=INSTRUMENT,
            provider_symbol=SYMBOL, acquired_at=datetime(2026, 10, 14),
            fork_revision=SHA, fixture_sha256=module.fixture_digest(rows()))


def test_mutated_fixture_with_original_digest_rejected():
    fixture = rows()
    original_sha = module.fixture_digest(fixture)
    fixture[1]["close"] = "100.75"
    with pytest.raises(ValueError, match="digest mismatch"):
        module.map_synthetic_session(
            fixture, session_date=DAY, instrument=INSTRUMENT,
            provider_symbol=SYMBOL, acquired_at=datetime(2026, 10, 14, tzinfo=UTC),
            fork_revision=SHA, fixture_sha256=original_sha,
        )


def test_declared_synthetic_provenance_is_not_market_evidence():
    dataset = convert(rows())
    version = dataset.manifest.acquisition_version
    assert "declared-unverified-fork-ref:" + SHA in version
    assert "verified-synthetic-fixture:" + module.fixture_digest(rows()) in version
    assert dataset.manifest.acquired_at == datetime(2026, 10, 14, tzinfo=UTC)
    assert any("completed-candle status" in x for x in dataset.manifest.limitations)
    assert any("not provider evidence" in x for x in dataset.manifest.limitations)
    assert any("unverified" in x for x in dataset.manifest.limitations)


def test_last_regular_session_minute_maps_to_exact_1530_close():
    fixture = rows()
    wall = datetime(2026, 10, 12, 15, 29, 59, tzinfo=UTC)
    fixture.append(dict(fixture[-1], time=int(wall.timestamp()) * 1000))
    dataset = convert(fixture)
    assert dataset.manifest.returned_end == datetime(2026, 10, 12, 10, tzinfo=UTC)
    assert dataset.manifest.missing_interval_count == 315
    assert dataset.bars[-1].interval.end == dataset.manifest.returned_end


def test_wrong_calendar_date_and_contradictory_duplicate_fail_closed():
    fixture = rows()
    fixture[1]["time"] += 24 * 60 * 60 * 1000
    with pytest.raises(ValueError, match="session date"):
        convert(fixture)

    fixture = rows()
    fixture.insert(1, dict(fixture[0], close="100.75"))
    with pytest.raises(ValueError, match="duplicate or unordered"):
        convert(fixture)


@pytest.mark.parametrize("price", ["", "not-a-decimal", "NaN", "Infinity", "-10"])
def test_invalid_price_strings_fail_closed(price):
    fixture = rows()
    fixture[1]["open"] = price
    with pytest.raises((ValueError, ArithmeticError)):
        convert(fixture)
