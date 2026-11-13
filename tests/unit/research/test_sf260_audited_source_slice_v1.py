"""SF-260 synthetic provenance and negative guard regression tests.

No real SF-088 archive is read.  Tiny synthetic grids are *never* admitted as
historical by production constants: test patches are local and reversible.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

import signalforge.research.audited_source_slice_v1 as deriv
from signalforge.domain.ids import InstrumentId
from signalforge.domain.time import CandleInterval
from signalforge.research.btc_raw_diagnostic_input import RawDiagnosticSource
from signalforge.research.historical_bars import (
    HistoricalBarDataset,
    HistoricalPriceBasis,
    load_historical_bar_fixture,
)
from signalforge.research.historical_grid import HistoricalBarGrid
from signalforge.research.scenario_execution import FULL_YEAR_VARIANT, SF260_90D_VARIANT
import scripts.stage6_90d_guarded_launcher as launcher

BASE = datetime(2027, 1, 1, tzinfo=UTC)
ORIGINAL = Path(__file__).resolve().parents[3] / (
    "examples/research/historical-bars-one-session.json"
)


def synthetic_parent(monkeypatch: pytest.MonkeyPatch) -> RawDiagnosticSource:
    """Only test scope shortens the protected source interval and parent identity."""
    first = load_historical_bar_fixture(ORIGINAL)
    total, child_count = 1320, 1300
    bars = tuple(
        replace(
            first.bars[0],
            instrument_id=InstrumentId("DELTA:BTCUSD"),
            interval=CandleInterval(
                BASE + timedelta(minutes=i),
                BASE + timedelta(minutes=i + 1),
            ),
            provider_timestamp_raw=f"synthetic-{i}",
            provider_timestamp_interpreted=BASE + timedelta(minutes=i),
        )
        for i in range(total)
    )
    end = BASE + timedelta(minutes=total)
    manifest = replace(
        first.manifest,
        instrument_id=InstrumentId("DELTA:BTCUSD"),
        requested_instrument="BTCUSD", resolved_provider_instrument="BTCUSD",
        requested_start=BASE, requested_end=end,
        returned_start=BASE, returned_end=end,
        grid=HistoricalBarGrid(
            "scenario-synthetic", "1", (CandleInterval(BASE, end),),
        ),
        expected_session_dates=(),
        price_basis=HistoricalPriceBasis.TRADED,
        limitations=("UNQUALIFIED_HISTORICAL_METADATA", "SYNTHETIC_TEST_ONLY"),
        raw_row_count=total, canonical_row_count=total,
        missing_interval_count=0, duplicate_observation_count=0,
        corrupt_rejected_count=0,
    )
    dataset = HistoricalBarDataset(manifest, bars)
    source = RawDiagnosticSource(dataset, "synthetic-parent")
    monkeypatch.setattr(deriv, "PARENT_DATASET_HASH", dataset.content_hash)
    monkeypatch.setattr(deriv, "FROZEN_PROVISIONAL_REPORT_SHA256", "synthetic-parent")
    monkeypatch.setattr(deriv, "SOURCE_START", BASE)
    monkeypatch.setattr(deriv, "MEASURED_END", BASE + timedelta(minutes=child_count))
    monkeypatch.setattr(deriv, "PARENT_END", end)
    monkeypatch.setattr(deriv, "SOURCE_MINUTES", child_count)
    monkeypatch.setattr(deriv, "PARENT_MINUTES", total)
    return source


def test_production_study_grid_is_91_source_days_not_pilot_90():
    assert deriv.SOURCE_START.isoformat() == "2025-10-30T00:00:00+00:00"
    assert deriv.IS_START.isoformat() == "2025-10-31T00:00:00+00:00"
    assert deriv.OOS_START.isoformat() == "2025-12-30T00:00:00+00:00"
    assert deriv.MEASURED_END.isoformat() == "2026-01-29T00:00:00+00:00"
    assert deriv.SOURCE_MINUTES == 131_040
    assert deriv.IS_CANDLES == 17_280
    assert deriv.OOS_CANDLES == 8_640
    assert (deriv.MEASURED_END - deriv.IS_START) == timedelta(days=90)
    assert (deriv.MEASURED_END - deriv.SOURCE_START) == timedelta(days=91)
    assert FULL_YEAR_VARIANT != SF260_90D_VARIANT


def test_audited_child_has_distinct_hashes_and_cannot_be_relabelled(monkeypatch):
    parent = synthetic_parent(monkeypatch)
    child = deriv.derive_audited_source_slice(parent)
    assert child.source_diagnostic_id != parent.source_diagnostic_id
    assert child.execution_valid is False
    assert child.dataset.bars == parent.dataset.bars[:1300]
    assert child.parent_dataset_hash == parent.dataset.content_hash
    assert len(child.ordered_one_minute_sha256) == 64
    assert len(child.derived_five_minute_close_digest) == 64
    assert child.derivation_id == deriv.config_hash(child.lineage_preimage())
    with pytest.raises(ValueError, match="verified factory"):
        deriv.AuditedSourceSliceV1(
            child.dataset, child.parent_dataset_hash, child.parent_diagnostic_id,
            child.ordered_one_minute_sha256, child.derived_five_minute_close_digest,
            child.derivation_id, object(),
        )
    with pytest.raises(ValueError, match="digest mismatch"):
        replace(child, ordered_one_minute_sha256="0" * 64)
    with pytest.raises(ValueError, match="five-minute digest mismatch"):
        replace(child, derived_five_minute_close_digest="0" * 64)
    with pytest.raises(ValueError, match="lineage identity"):
        replace(child, derivation_id="0" * 64)


def test_parent_hash_and_nonchronological_source_rejected(monkeypatch):
    source = synthetic_parent(monkeypatch)
    monkeypatch.setattr(deriv, "PARENT_DATASET_HASH", "0" * 64)
    with pytest.raises(ValueError, match="parent audit/coverage"):
        deriv.derive_audited_source_slice(source)
    with pytest.raises(ValueError, match="chronological order"):
        replace(source.dataset, bars=tuple(reversed(source.dataset.bars)))


def test_90d_launcher_does_not_accept_missing_gate_record(monkeypatch, tmp_path):
    monkeypatch.setattr(launcher, "verify_checkout", lambda: None)
    monkeypatch.setattr(launcher, "_source_dir", lambda: tmp_path)
    monkeypatch.setattr(launcher, "_private", lambda path, mode: path)
    monkeypatch.setattr(launcher, "GATE_RECORD", tmp_path / "nonexistent-gate.json")
    with pytest.raises(launcher.LaunchBlocked, match="invalid separate 90D Gate D"):
        launcher.verify_prelaunch("REFERENCE_RAW", 1)
    with pytest.raises(launcher.LaunchBlocked, match="profile"):
        launcher.verify_prelaunch("NOT_A_PROFILE", 1)


def test_90d_launcher_scope_includes_pid_swap_and_memory_guards(monkeypatch):
    monkeypatch.setattr(launcher.shutil, "which", lambda name: f"/usr/bin/{name}")
    command = launcher._scope_command(["--internal-probe"])
    assert "TasksMax=64" in command
    assert "MemorySwapMax=0" in command
    assert f"MemoryMax={3 * launcher.GIB}" in command
    assert f"--as={4 * launcher.GIB}:{4 * launcher.GIB}" in command
    assert "--internal-probe" in command
