"""SF-083 offline integration rehearsal; synthetic nsemine-shaped input only.

This is not evidence that a real NSE session was acquired.
"""
from __future__ import annotations

import importlib.util
import json
import socket
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from signalforge.domain.market import CandleQuality
from signalforge.research.historical_bars import aggregate_one_minute_to_five_minute
from signalforge.research.historical_dataset_store import (
    HistoricalDatasetStoreError,
    LocalHistoricalDatasetStore,
)

MAPPER = Path(__file__).resolve().parents[2] / "support" / "sf079_provisional_mapper.py"
SPEC = importlib.util.spec_from_file_location("sf079_provisional_mapper_sf083", MAPPER)
assert SPEC and SPEC.loader
mapper = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mapper)

SESSION = date(2026, 10, 12)
IDENTITY = "NSE:SF083-SYNTHETIC"
PROVIDER_SYMBOL = "SF083-SYNTHETIC-EQ"


def _synthetic_rows() -> list[dict[str, object]]:
    rows = []
    for minute in range(60):
        if minute == 7:
            continue  # one deliberately unavailable upstream minute
        local_wall = datetime(2026, 10, 12, 9, 15, 53, tzinfo=UTC) + timedelta(
            minutes=minute
        )
        rows.append({
            "instrument": IDENTITY,
            "provider_symbol": PROVIDER_SYMBOL,
            "time": int(local_wall.timestamp()) * 1000,
            "open": "100.00", "high": "101.00",
            "low": "99.00", "close": "100.50",
            "volume": 100 + minute,
        })
    return rows


def test_sf083_offline_reuse_through_shared_sf084_store(tmp_path, monkeypatch):
    source_rows = _synthetic_rows()
    canonical = mapper.map_synthetic_session(
        source_rows,
        session_date=SESSION,
        instrument=IDENTITY,
        provider_symbol=PROVIDER_SYMBOL,
        acquired_at=datetime(2026, 10, 14, tzinfo=UTC),
        fork_revision="a" * 40,
        fixture_sha256=mapper.fixture_digest(source_rows),
    )
    store = LocalHistoricalDatasetStore(tmp_path)
    dataset_id = store.save(canonical)

    def refuse_network(*args, **kwargs):
        raise AssertionError("SF-083 offline replay attempted network access")

    monkeypatch.setattr(socket, "socket", refuse_network)
    reloaded = LocalHistoricalDatasetStore(tmp_path).load(dataset_id)
    assert reloaded == canonical
    assert reloaded.content_hash == canonical.content_hash
    assert reloaded.dataset_id == dataset_id
    assert reloaded.manifest.raw_row_count == 59
    assert reloaded.manifest.missing_interval_count == 316
    first = aggregate_one_minute_to_five_minute(canonical)
    second = aggregate_one_minute_to_five_minute(reloaded)
    assert second == first
    assert sum(c.quality is CandleQuality.VALID for c in second) == 11
    assert sum(c.quality is CandleQuality.INCOMPLETE for c in second) == 1
    assert sum(c.quality is CandleQuality.MISSING for c in second) == 63
    assert "SYNTHETIC" in reloaded.manifest.limitations[0]
    assert store.save(reloaded) == dataset_id


def test_sf083_stored_evidence_tampering_fails_offline(tmp_path, monkeypatch):
    rows = _synthetic_rows()
    dataset = mapper.map_synthetic_session(
        rows,
        session_date=SESSION,
        instrument=IDENTITY,
        provider_symbol=PROVIDER_SYMBOL,
        acquired_at=datetime(2026, 10, 14, tzinfo=UTC),
        fork_revision="a" * 40,
        fixture_sha256=mapper.fixture_digest(rows),
    )
    store = LocalHistoricalDatasetStore(tmp_path)
    dataset_id = store.save(dataset)
    path = tmp_path / (str(dataset_id) + ".json")
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["manifest"]["acquired_at"] = "2026-10-15T12:00:00+00:00"
    path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(socket, "socket", lambda *args, **kw: pytest.fail("network called"))
    with pytest.raises(HistoricalDatasetStoreError, match="digest"):
        store.load(dataset_id)
