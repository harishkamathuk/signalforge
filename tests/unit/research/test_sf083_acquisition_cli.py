"""SF-083 CLI: synthetic stub acquisition, deterministic evidence and offline boundaries."""
from __future__ import annotations

import importlib.util
import json
import sys
from datetime import date
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "tools/research/sf083_acquire_sample.py"
SPEC = importlib.util.spec_from_file_location("sf083_acquisition_cli", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
cli = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cli)


def test_single_bounded_mock_acquisition_does_not_reinterpret_raw(tmp_path, monkeypatch):
    output = tmp_path / "private-data"
    output.mkdir()
    entitlement = tmp_path / "entitlement.txt"
    entitlement.write_text("Test-only permission evidence; mock response")
    calls = []
    nsemine = ModuleType("nsemine")
    historical = ModuleType("nsemine.historical")

    def mock_fetch(**kwargs):
        calls.append(kwargs)
        return {"raw": {"bars": [{"time": 123, "p": 101.2}]}}

    historical.get_stock_historical_data = mock_fetch
    nsemine.historical = historical
    monkeypatch.setitem(sys.modules, "nsemine", nsemine)
    monkeypatch.setitem(sys.modules, "nsemine.historical", historical)

    report = cli.acquire(
        symbol="TEST", session=date(2026, 10, 9), output=output,
        entitlement=entitlement, calendar="synthetic-calendar",
        revision="fixed-mock-revision",
    )
    assert len(calls) == 1
    assert calls[0]["interval"] == 1
    assert calls[0]["raw"] is True
    assert report["status"].startswith("RAW_CAPTURED")
    assert json.loads((output / "raw-response.json").read_text()) == mock_fetch()
    assert json.loads((output / "acquisition-manifest.json").read_text()) == report
    assert report["raw_sha256"] == cli.hashlib.sha256(
        (output / "raw-response.json").read_bytes()
    ).hexdigest()
    with pytest.raises(FileExistsError):
        cli.acquire(
            symbol="TEST", session=date(2026, 10, 9), output=output,
            entitlement=entitlement, calendar="synthetic-calendar",
            revision="fixed-mock-revision",
        )


def test_acquisition_rejected_before_import_without_evidence(tmp_path, monkeypatch):
    output = tmp_path / "out"
    output.mkdir()
    original = cli.importlib.import_module

    def fail_import(name):
        if name.startswith("nsemine"):
            pytest.fail("no provider call allowed without evidence")
        return original(name)

    monkeypatch.setattr(cli.importlib, "import_module", fail_import)
    with pytest.raises(ValueError, match="evidence"):
        cli.acquire(
            symbol="TEST", session=date(2026, 10, 9), output=output,
            entitlement=tmp_path / "missing.txt", calendar="synthetic",
            revision="test-rev",
        )
    assert list(output.iterdir()) == []


def test_offline_verify_never_imports_provider(tmp_path, monkeypatch):
    from signalforge.research.historical_bars import load_historical_bar_fixture
    from signalforge.research.historical_dataset_store import LocalHistoricalDatasetStore

    example = Path(__file__).resolve().parents[3]
    dataset = load_historical_bar_fixture(
        example / "examples/research/historical-bars-one-session.json"
    )
    identity = LocalHistoricalDatasetStore(tmp_path).save(dataset)

    def forbid_import(name):
        pytest.fail(f"offline mode should not import {name}")

    monkeypatch.setattr(cli.importlib, "import_module", forbid_import)
    summary = cli.verify(output=tmp_path, dataset_id=str(identity))
    assert summary["dataset_id"] == str(identity)
    assert summary["canonical_bars"] == 375
    assert summary["derived_5m"] == {"valid": 75, "incomplete": 0, "missing": 0}


def test_cli_returns_blocked_for_missing_dataset(tmp_path, capsys):
    status = cli.main([
        "offline-verify", "--output", str(tmp_path),
        "--dataset-id", "a" * 64,
    ])
    assert status == 2
    assert "SF-083 blocked:" in capsys.readouterr().err
