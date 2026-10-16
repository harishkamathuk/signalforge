"""SF-083 corrective evidence-gate regressions; deterministic and offline."""
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
FORK_URL = "https://github.com/harishkamathuk/signalforge-nsemine.git"


class _Distribution:
    version = "2.2.1"

    def __init__(self, *, url: str = FORK_URL, commit_id: str = REVISION, direct_url=True):
        self.url = url
        self.commit_id = commit_id
        self.has_direct_url = direct_url

    def read_text(self, name: str):
        assert name == "direct_url.json"
        if not self.has_direct_url:
            return None
        return json.dumps(
            {
                "url": self.url,
                "vcs_info": {
                    "vcs": "git",
                    "commit_id": self.commit_id,
                    "requested_revision": self.commit_id,
                },
            }
        )


def _install_distribution(monkeypatch, **kwargs):
    monkeypatch.setattr(
        cli.importlib.metadata,
        "distribution",
        lambda name: _Distribution(**kwargs),
    )


def _evidence(tmp_path: Path) -> Path:
    path = tmp_path / "permission.txt"
    path.write_text("synthetic test-only source-use evidence", encoding="utf-8")
    return path


def _install_provider(
    monkeypatch,
    *,
    candidates,
    response=None,
    search_error: Exception | None = None,
    direct_api: bool = True,
):
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
        if search_error is not None:
            raise search_error
        return candidates

    historical.search_stock_instruments = search_stock_instruments

    if direct_api:
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
            if response is not None:
                return response
            return {
                "data": [
                    {"time": 123, "open": 1, "high": 1, "low": 1, "close": 1}
                ]
            }

        historical.get_stock_historical_data_by_instrument = (
            get_stock_historical_data_by_instrument
        )
    else:
        def get_stock_historical_data_by_instrument(
            *, symbol, symbol_type, start_datetime, end_datetime, interval, raw
        ):
            pytest.fail("incompatible API must fail before provider calls")

        historical.get_stock_historical_data_by_instrument = (
            get_stock_historical_data_by_instrument
        )

    nsemine.historical = historical
    monkeypatch.setitem(sys.modules, "nsemine", nsemine)
    monkeypatch.setitem(sys.modules, "nsemine.historical", historical)
    return calls


def _acquire(tmp_path, monkeypatch, *, candidates, response=None):
    output = tmp_path / "private-data"
    output.mkdir()
    _install_distribution(monkeypatch)
    calls = _install_provider(
        monkeypatch, candidates=candidates, response=response
    )
    report = cli.acquire(
        symbol="TCS",
        session=SESSION,
        output=output,
        entitlement=_evidence(tmp_path),
        calendar="synthetic-calendar",
        revision=REVISION,
    )
    return output, calls, report


def test_exact_tcs_eq_identity_is_retained_and_exact_token_is_used(tmp_path, monkeypatch):
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
    assert len(calls["fetch"]) == 1
    assert calls["fetch"][0]["token"] == "11536"
    assert report["instrument_verification"]["selected_provider_token"] == "11536"
    assert report["installed_nsemine_vcs"] == {
        "repository_url": "https://github.com/harishkamathuk/signalforge-nsemine",
        "commit_id": REVISION,
        "verification": "MATCHED_DECLARED_REVISION_BEFORE_PROVIDER_ACCESS",
    }
    resolver = json.loads((output / "resolver-evidence.json").read_text())
    assert resolver["candidates"] == [candidate]
    assert resolver["selected_candidate"] == candidate
    assert json.loads((output / "acquisition-manifest.json").read_text()) == report


@pytest.mark.parametrize(
    ("distribution_kwargs", "match"),
    [
        ({"commit_id": "b" * 40}, "does not match"),
        ({"url": "https://github.com/example/other.git"}, "repository does not match"),
        ({"direct_url": False}, "lacks VCS direct_url"),
    ],
)
def test_unproven_or_wrong_installed_revision_fails_before_provider_import(
    tmp_path, monkeypatch, distribution_kwargs, match
):
    output = tmp_path / "private"
    output.mkdir()
    _install_distribution(monkeypatch, **distribution_kwargs)

    original = cli.importlib.import_module

    def forbid_provider_import(name):
        if name.startswith("nsemine"):
            pytest.fail("provider must not be imported before VCS provenance is verified")
        return original(name)

    monkeypatch.setattr(cli.importlib, "import_module", forbid_provider_import)
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


def test_non_commit_revision_fails_before_provider_import(tmp_path, monkeypatch):
    output = tmp_path / "private"
    output.mkdir()
    original = cli.importlib.import_module

    def forbid_provider_import(name):
        if name.startswith("nsemine"):
            pytest.fail("provider must not be imported for invalid revision")
        return original(name)

    monkeypatch.setattr(cli.importlib, "import_module", forbid_provider_import)
    with pytest.raises(ValueError, match="40-character"):
        cli.acquire(
            symbol="TCS",
            session=SESSION,
            output=output,
            entitlement=_evidence(tmp_path),
            calendar="synthetic",
            revision="branch-name",
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
    ],
)
def test_ambiguous_wrong_type_series_or_token_fails_before_history(
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


def test_base_symbol_without_provider_series_fails_closed_no_reference_override(
    tmp_path, monkeypatch
):
    output = tmp_path / "private"
    output.mkdir()
    _install_distribution(monkeypatch)
    calls = _install_provider(
        monkeypatch,
        candidates=[{"symbol": "TCS", "scripcode": "11536", "type": "Equity"}],
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
    with pytest.raises(ValueError, match="sample is BLOCKED"):
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


def test_direct_token_api_is_required_before_resolver_or_history(tmp_path, monkeypatch):
    output = tmp_path / "private"
    output.mkdir()
    _install_distribution(monkeypatch)
    calls = _install_provider(
        monkeypatch,
        candidates=[{"symbol": "TCS-EQ", "scripcode": "11536", "type": "Equity"}],
        direct_api=False,
    )
    with pytest.raises(ValueError, match="signature"):
        cli.acquire(
            symbol="TCS",
            session=SESSION,
            output=output,
            entitlement=_evidence(tmp_path),
            calendar="synthetic",
            revision=REVISION,
        )
    assert calls["search"] == []
    assert calls["fetch"] == []


def test_resolver_failure_produces_no_partial_evidence(tmp_path, monkeypatch):
    output = tmp_path / "private"
    output.mkdir()
    _install_distribution(monkeypatch)
    calls = _install_provider(
        monkeypatch,
        candidates=[],
        search_error=RuntimeError("resolver unavailable"),
    )
    with pytest.raises(RuntimeError, match="resolver unavailable"):
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


def test_manifest_write_failure_cleans_resolver_and_response_evidence(
    tmp_path, monkeypatch
):
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


def test_existing_acquisition_protection_remains_fail_closed(tmp_path, monkeypatch):
    output = tmp_path / "private"
    output.mkdir()
    (output / "existing").write_text("do not overwrite", encoding="utf-8")
    with pytest.raises(FileExistsError, match="must be empty"):
        cli.acquire(
            symbol="TCS",
            session=SESSION,
            output=output,
            entitlement=_evidence(tmp_path),
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


def test_cli_returns_blocked_for_missing_dataset(tmp_path, capsys):
    status = cli.main(
        [
            "offline-verify",
            "--output",
            str(tmp_path),
            "--dataset-id",
            "a" * 64,
        ]
    )
    assert status == 2
    assert "SF-083 blocked:" in capsys.readouterr().err
