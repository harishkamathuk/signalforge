"""SF-083 corrective regressions: provenance, identity and blocked acquisition."""
from __future__ import annotations

import importlib.util
import json
import sys
from datetime import date
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "tools/research/sf083_acquire_sample.py"
SPEC = importlib.util.spec_from_file_location("sf083_acquisition_cli", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
cli = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cli)

SESSION = date(2026, 10, 9)
REVISION = "a" * 40
REPOSITORY = "https://github.com/harishkamathuk/signalforge-nsemine.git"


class _Distribution:
    def __init__(
        self,
        *,
        commit_id: str = REVISION,
        repository: str = REPOSITORY,
        version: str = "2.2.1",
        direct_url: bool = True,
    ):
        self.version = version
        self._commit_id = commit_id
        self._repository = repository
        self._direct_url = direct_url

    def read_text(self, name: str):
        assert name == "direct_url.json"
        if not self._direct_url:
            return None
        return json.dumps(
            {
                "url": self._repository,
                "vcs_info": {
                    "vcs": "git",
                    "commit_id": self._commit_id,
                    "requested_revision": self._commit_id,
                },
            }
        )


def _evidence(tmp_path: Path) -> Path:
    path = tmp_path / "permission.txt"
    path.write_text("synthetic test-only source-use evidence", encoding="utf-8")
    return path


def _install_distribution(monkeypatch, distribution: _Distribution | None = None):
    monkeypatch.setattr(
        cli.importlib.metadata,
        "distribution",
        lambda name: distribution or _Distribution(),
    )


def _install_provider(monkeypatch, *, candidates, response=None):
    nsemine = ModuleType("nsemine")
    historical = ModuleType("nsemine.historical")
    calls: dict[str, list[dict[str, object]]] = {"search": [], "fetch": []}

    def search_stock_instruments(*, stock_symbol, segment=None, scrip_type=None):
        calls["search"].append(
            {
                "stock_symbol": stock_symbol,
                "segment": segment,
                "scrip_type": scrip_type,
            }
        )
        return candidates

    def get_stock_historical_data_by_instrument(
        *,
        symbol,
        token,
        symbol_type,
        start_datetime,
        end_datetime,
        interval,
        raw,
    ):
        calls["fetch"].append(
            {
                "symbol": symbol,
                "token": token,
                "symbol_type": symbol_type,
                "start_datetime": start_datetime,
                "end_datetime": end_datetime,
                "interval": interval,
                "raw": raw,
            }
        )
        return response if response is not None else {
            "data": [{"time": 123, "open": 1, "high": 1, "low": 1, "close": 1}]
        }

    historical.search_stock_instruments = search_stock_instruments
    historical.get_stock_historical_data_by_instrument = (
        get_stock_historical_data_by_instrument
    )
    nsemine.historical = historical
    monkeypatch.setitem(sys.modules, "nsemine", nsemine)
    monkeypatch.setitem(sys.modules, "nsemine.historical", historical)
    return calls


def _acquire(tmp_path, monkeypatch, *, candidates, response=None):
    output = tmp_path / "private"
    output.mkdir()
    _install_distribution(monkeypatch)
    calls = _install_provider(monkeypatch, candidates=candidates, response=response)
    report = cli.acquire(
        symbol="TCS",
        session=SESSION,
        output=output,
        entitlement=_evidence(tmp_path),
        calendar="synthetic-calendar",
        revision=REVISION,
    )
    return output, calls, report


def test_exact_provider_identity_and_verified_revision_are_persisted(
    tmp_path, monkeypatch
):
    candidate = {
        "symbol": "TCS-EQ",
        "scripcode": "11536",
        "type": "Equity",
        "description": "TATA CONSULTANCY SERVICES LIMITED",
    }
    output, calls, report = _acquire(tmp_path, monkeypatch, candidates=[candidate])

    assert calls["search"] == [
        {"stock_symbol": "TCS", "segment": "EQ", "scrip_type": None}
    ]
    assert calls["fetch"][0]["token"] == "11536"
    assert report["verified_revision"] == REVISION
    assert report["installed_nsemine_provenance"] == {
        "repository": "https://github.com/harishkamathuk/signalforge-nsemine",
        "commit_id": REVISION,
        "version": "2.2.1",
        "provenance": "PEP610_direct_url_vcs_info",
    }
    assert report["raw_row_count"] == 1
    resolver = json.loads((output / "resolver-evidence.json").read_text())
    assert resolver["candidates"] == [candidate]
    assert resolver["selected_candidate"] == candidate
    assert json.loads((output / "acquisition-manifest.json").read_text()) == report


@pytest.mark.parametrize(
    ("distribution", "match"),
    [
        (_Distribution(commit_id="b" * 40), "commit does not match"),
        (
            _Distribution(repository="https://github.com/example/not-signalforge-nsemine.git"),
            "repository does not match",
        ),
        (_Distribution(direct_url=False), "no PEP 610"),
    ],
)
def test_unverifiable_or_wrong_installed_revision_fails_before_provider_import(
    tmp_path, monkeypatch, distribution, match
):
    output = tmp_path / "private"
    output.mkdir()
    monkeypatch.setattr(cli.importlib.metadata, "distribution", lambda name: distribution)
    original_import = cli.importlib.import_module

    def fail_provider_import(name):
        if name.startswith("nsemine"):
            pytest.fail("provider code must not import before revision verification")
        return original_import(name)

    monkeypatch.setattr(cli.importlib, "import_module", fail_provider_import)

    with pytest.raises(ValueError, match=match):
        cli.acquire(
            symbol="TCS",
            session=SESSION,
            output=output,
            entitlement=_evidence(tmp_path),
            calendar="synthetic",
            revision=REVISION,
        )
    assert list(output.iterdir()) == []


@pytest.mark.parametrize("revision", ["short", "A" * 40, "z" * 40])
def test_invalid_revision_format_fails_before_provider_import(
    tmp_path, monkeypatch, revision
):
    output = tmp_path / "private"
    output.mkdir()
    original_import = cli.importlib.import_module

    def fail_provider_import(name):
        if name.startswith("nsemine"):
            pytest.fail("provider code must not import for invalid revision")
        return original_import(name)

    monkeypatch.setattr(cli.importlib, "import_module", fail_provider_import)
    with pytest.raises(ValueError, match="40-character Git commit SHA"):
        cli.acquire(
            symbol="TCS",
            session=SESSION,
            output=output,
            entitlement=_evidence(tmp_path),
            calendar="synthetic",
            revision=revision,
        )


@pytest.mark.parametrize(
    ("candidates", "match"),
    [
        (
            [
                {"symbol": "TCS-EQ", "scripcode": "11536", "type": "Equity"},
                {"symbol": "TCS-EQ", "scripcode": "11537", "type": "Equity"},
            ],
            "indistinguishable",
        ),
        (
            [{"symbol": "TCS-BE", "scripcode": "11536", "type": "Equity"}],
            "does not establish series EQ",
        ),
        (
            [{"symbol": "TCS-EQ", "scripcode": "11536", "type": "Futures"}],
            "not cash Equity",
        ),
        (
            [{"symbol": "TCS-EQ", "type": "Equity"}],
            "token/scripcode",
        ),
        (
            [{"symbol": "TCS", "scripcode": "11536", "type": "Equity"}],
            "does not establish series EQ",
        ),
    ],
)
def test_identity_ambiguity_or_missing_provider_series_fails_before_history(
    tmp_path, monkeypatch, candidates, match
):
    output = tmp_path / "private"
    output.mkdir()
    _install_distribution(monkeypatch)
    calls = _install_provider(monkeypatch, candidates=candidates)

    with pytest.raises(ValueError, match=match):
        cli.acquire(
            symbol="TCS",
            session=SESSION,
            output=output,
            entitlement=_evidence(tmp_path),
            calendar="synthetic",
            revision=REVISION,
        )
    assert calls["fetch"] == []
    assert list(output.iterdir()) == []


@pytest.mark.parametrize("response", [{}, {"data": []}, {"data": "not-a-list"}])
def test_empty_or_invalid_historical_payload_is_blocked_without_success_artifacts(
    tmp_path, monkeypatch, response
):
    output = tmp_path / "private"
    output.mkdir()
    _install_distribution(monkeypatch)
    calls = _install_provider(
        monkeypatch,
        candidates=[{"symbol": "TCS-EQ", "scripcode": "11536", "type": "Equity"}],
        response=response,
    )

    with pytest.raises(ValueError, match="sample acquisition is BLOCKED"):
        cli.acquire(
            symbol="TCS",
            session=SESSION,
            output=output,
            entitlement=_evidence(tmp_path),
            calendar="synthetic",
            revision=REVISION,
        )
    assert len(calls["fetch"]) == 1
    assert list(output.iterdir()) == []


def test_successful_historical_response_alone_cannot_establish_identity(
    tmp_path, monkeypatch
):
    output = tmp_path / "private"
    output.mkdir()
    _install_distribution(monkeypatch)
    calls = _install_provider(
        monkeypatch,
        candidates=[{"symbol": "TCS", "scripcode": "11536", "type": "Equity"}],
        response={"data": [{"time": 123, "close": 999}]},
    )

    with pytest.raises(ValueError, match="does not establish series EQ"):
        cli.acquire(
            symbol="TCS",
            session=SESSION,
            output=output,
            entitlement=_evidence(tmp_path),
            calendar="synthetic",
            revision=REVISION,
        )
    assert calls["fetch"] == []


def test_manifest_write_failure_cleans_partial_success_artifacts(tmp_path, monkeypatch):
    output = tmp_path / "private"
    output.mkdir()
    _install_distribution(monkeypatch)
    _install_provider(
        monkeypatch,
        candidates=[{"symbol": "TCS-EQ", "scripcode": "11536", "type": "Equity"}],
    )
    original_write = cli._write_exclusive

    def fail_manifest(path, data):
        if path.name == "acquisition-manifest.json":
            raise OSError("simulated disk fault")
        return original_write(path, data)

    monkeypatch.setattr(cli, "_write_exclusive", fail_manifest)
    with pytest.raises(OSError, match="simulated disk fault"):
        cli.acquire(
            symbol="TCS",
            session=SESSION,
            output=output,
            entitlement=_evidence(tmp_path),
            calendar="synthetic",
            revision=REVISION,
        )
    assert list(output.iterdir()) == []


def test_acquisition_rejected_before_provenance_check_without_entitlement(
    tmp_path, monkeypatch
):
    output = tmp_path / "private"
    output.mkdir()

    def fail_distribution(name):
        pytest.fail("package provenance must not be inspected without entitlement evidence")

    monkeypatch.setattr(cli.importlib.metadata, "distribution", fail_distribution)
    with pytest.raises(ValueError, match="evidence"):
        cli.acquire(
            symbol="TCS",
            session=SESSION,
            output=output,
            entitlement=tmp_path / "missing.txt",
            calendar="synthetic",
            revision=REVISION,
        )


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
