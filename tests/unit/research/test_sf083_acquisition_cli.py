"""SF-083 CLI instrument identity, acquisition evidence and offline boundaries."""
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


def _evidence(tmp_path: Path) -> Path:
    path = tmp_path / "permission.txt"
    path.write_text("synthetic test-only source-use evidence", encoding="utf-8")
    return path


def _reference(
    tmp_path: Path,
    *,
    token: str = "11536",
    symbol: str = "TCS",
    series: str = "EQ",
    source_bytes: bytes = b"synthetic authoritative instrument master snapshot",
) -> tuple[Path, Path]:
    source = tmp_path / "instrument-reference-source.bin"
    source.write_bytes(source_bytes)
    path = tmp_path / "instrument-reference.json"
    path.write_text(
        json.dumps(
            {
                "evidence_type": "independent_instrument_reference",
                "provider": "nsemine",
                "exchange": "NSE",
                "symbol": symbol,
                "series": series,
                "instrument_type": "Equity",
                "provider_token": token,
                "source_reference": "synthetic://authoritative-instrument-master",
                "source_content_sha256": cli.hashlib.sha256(source_bytes).hexdigest(),
            }
        ),
        encoding="utf-8",
    )
    return path, source


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
            return response if response is not None else {"data": []}

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


def _acquire(
    tmp_path,
    monkeypatch,
    *,
    candidates,
    response=None,
    reference: tuple[Path, Path] | None = None,
):
    output = tmp_path / "private-data"
    output.mkdir()
    calls = _install_provider(
        monkeypatch, candidates=candidates, response=response or {"data": []}
    )
    report = cli.acquire(
        symbol="TCS",
        session=SESSION,
        output=output,
        entitlement=_evidence(tmp_path),
        calendar="synthetic-calendar",
        revision="fixed-mock-revision",
        instrument_reference=reference[0] if reference is not None else None,
        instrument_reference_source=reference[1] if reference is not None else None,
    )
    return output, calls, report


def test_exact_tcs_eq_identity_is_retained_and_exact_token_is_used(tmp_path, monkeypatch):
    candidate = {
        "symbol": "TCS-EQ",
        "scripcode": "11536",
        "type": "Equity",
        "description": "TATA CONSULTANCY SERVICES LIMITED",
    }
    response = {"data": [{"time": 123, "open": 1, "high": 1, "low": 1, "close": 1}]}
    output, calls, report = _acquire(
        tmp_path, monkeypatch, candidates=[candidate], response=response
    )

    assert calls["search"] == [
        {"stock_symbol": "TCS", "segment": "EQ", "scrip_type": None}
    ]
    assert len(calls["fetch"]) == 1
    assert calls["fetch"][0]["token"] == "11536"
    assert calls["fetch"][0]["symbol"] == "TCS"
    assert calls["fetch"][0]["symbol_type"] == "Equity"
    assert report["instrument_verification"]["selected_provider_token"] == "11536"
    assert (
        report["historical_request_token_linkage"]["provider_token"]
        == report["instrument_verification"]["selected_provider_token"]
    )
    resolver = json.loads((output / "resolver-evidence.json").read_text())
    assert resolver["candidates"] == [candidate]
    assert resolver["selected_candidate"] == candidate
    assert report["resolver_evidence_sha256"] == cli.hashlib.sha256(
        (output / "resolver-evidence.json").read_bytes()
    ).hexdigest()
    assert json.loads((output / "sdk-decoded-response.json").read_text()) == response
    assert json.loads((output / "acquisition-manifest.json").read_text()) == report


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
            [{"symbol": "TCS-EQ", "scripcode": {"bad": "shape"}, "type": "Equity"}],
            "token/scripcode",
        ),
    ],
)
def test_ambiguous_wrong_type_series_or_token_fails_before_history(
    tmp_path, monkeypatch, candidates, match
):
    output = tmp_path / "private"
    output.mkdir()
    calls = _install_provider(monkeypatch, candidates=candidates, response={"data": [1]})
    with pytest.raises(ValueError, match=match):
        cli.acquire(
            symbol="TCS",
            session=SESSION,
            output=output,
            entitlement=_evidence(tmp_path),
            calendar="synthetic",
            revision="test-rev",
        )
    assert calls["fetch"] == []
    assert list(output.iterdir()) == []


def test_missing_series_can_use_exact_hash_addressed_independent_token_reference(
    tmp_path, monkeypatch
):
    candidate = {"symbol": "TCS", "scripcode": "11536", "type": "Equity"}
    reference = _reference(tmp_path)
    output, calls, report = _acquire(
        tmp_path,
        monkeypatch,
        candidates=[candidate],
        response={"data": []},
        reference=reference,
    )
    assert calls["fetch"][0]["token"] == "11536"
    assert (
        report["instrument_verification"]["selection_basis"]
        == "independent_reference_exact_token_symbol_series"
    )
    resolver = json.loads((output / "resolver-evidence.json").read_text())
    assert (
        resolver["independent_reference_evidence"]["source_content_sha256"]
        == cli.hashlib.sha256(reference[1].read_bytes()).hexdigest()
    )
    assert resolver["independent_reference_file_sha256"] == cli.hashlib.sha256(
        reference[0].read_bytes()
    ).hexdigest()
    assert resolver["independent_reference_source_sha256"] == cli.hashlib.sha256(
        reference[1].read_bytes()
    ).hexdigest()


def test_missing_series_without_independent_reference_fails_before_history(
    tmp_path, monkeypatch
):
    candidate = {"symbol": "TCS", "scripcode": "11536", "type": "Equity"}
    output = tmp_path / "private"
    output.mkdir()
    calls = _install_provider(monkeypatch, candidates=[candidate], response={"data": [1]})
    with pytest.raises(ValueError, match="does not establish series EQ"):
        cli.acquire(
            symbol="TCS",
            session=SESSION,
            output=output,
            entitlement=_evidence(tmp_path),
            calendar="synthetic",
            revision="test",
        )
    assert calls["fetch"] == []


def test_independent_reference_token_mismatch_fails_closed(tmp_path, monkeypatch):
    candidate = {"symbol": "TCS", "scripcode": "11536", "type": "Equity"}
    output = tmp_path / "private"
    output.mkdir()
    calls = _install_provider(monkeypatch, candidates=[candidate], response={"data": [1]})
    reference = _reference(tmp_path, token="99999")
    with pytest.raises(ValueError, match="does not establish series EQ"):
        cli.acquire(
            symbol="TCS",
            session=SESSION,
            output=output,
            entitlement=_evidence(tmp_path),
            calendar="synthetic",
            revision="test",
            instrument_reference=reference[0],
            instrument_reference_source=reference[1],
        )
    assert calls["fetch"] == []


def test_independent_reference_source_hash_mismatch_fails_before_resolver(
    tmp_path, monkeypatch
):
    output = tmp_path / "private"
    output.mkdir()
    metadata, source = _reference(tmp_path)
    source.write_bytes(b"tampered after metadata creation")
    calls = _install_provider(
        monkeypatch,
        candidates=[{"symbol": "TCS", "scripcode": "11536", "type": "Equity"}],
    )
    with pytest.raises(ValueError, match="source snapshot hash"):
        cli.acquire(
            symbol="TCS",
            session=SESSION,
            output=output,
            entitlement=_evidence(tmp_path),
            calendar="synthetic",
            revision="test",
            instrument_reference=metadata,
            instrument_reference_source=source,
        )
    assert calls["search"] == []
    assert calls["fetch"] == []


def test_successful_historical_response_alone_cannot_establish_identity(
    tmp_path, monkeypatch
):
    candidate = {"symbol": "TCS", "scripcode": "11536", "type": "Equity"}
    output = tmp_path / "private"
    output.mkdir()
    calls = _install_provider(
        monkeypatch,
        candidates=[candidate],
        response={"data": [{"time": 123, "close": 999}]},
    )
    with pytest.raises(ValueError, match="does not establish series EQ"):
        cli.acquire(
            symbol="TCS",
            session=SESSION,
            output=output,
            entitlement=_evidence(tmp_path),
            calendar="synthetic",
            revision="test",
        )
    assert calls["fetch"] == []


def test_direct_token_api_is_required_before_any_resolver_or_history_call(
    tmp_path, monkeypatch
):
    output = tmp_path / "private"
    output.mkdir()
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
            revision="test",
        )
    assert calls["search"] == []
    assert calls["fetch"] == []


@pytest.mark.parametrize("candidates", [[], [{"description": "TCS"}], "bad-schema"])
def test_empty_or_malformed_resolver_results_fail_closed(
    tmp_path, monkeypatch, candidates
):
    output = tmp_path / "private"
    output.mkdir()
    calls = _install_provider(monkeypatch, candidates=candidates)
    with pytest.raises(ValueError):
        cli.acquire(
            symbol="TCS",
            session=SESSION,
            output=output,
            entitlement=_evidence(tmp_path),
            calendar="synthetic",
            revision="test",
        )
    assert calls["fetch"] == []


def test_resolver_failure_produces_no_partial_evidence(tmp_path, monkeypatch):
    output = tmp_path / "private"
    output.mkdir()
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
            revision="test",
        )
    assert calls["fetch"] == []
    assert list(output.iterdir()) == []


def test_non_eq_operator_request_is_rejected_before_provider_import(tmp_path, monkeypatch):
    output = tmp_path / "private"
    output.mkdir()
    original = cli.importlib.import_module

    def fail_import(name):
        if name.startswith("nsemine"):
            pytest.fail("provider must not be imported for unsupported series")
        return original(name)

    monkeypatch.setattr(cli.importlib, "import_module", fail_import)
    with pytest.raises(ValueError, match="limited to the EQ series"):
        cli.acquire(
            symbol="TCS",
            series="BE",
            session=SESSION,
            output=output,
            entitlement=_evidence(tmp_path),
            calendar="synthetic",
            revision="test",
        )


def test_manifest_write_failure_cleans_resolver_and_response_evidence(
    tmp_path, monkeypatch
):
    output = tmp_path / "private"
    output.mkdir()
    _install_provider(
        monkeypatch,
        candidates=[{"symbol": "TCS-EQ", "scripcode": "11536", "type": "Equity"}],
        response={"data": []},
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
            revision="test",
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
            revision="test",
        )


def test_acquisition_rejected_before_import_without_entitlement_evidence(
    tmp_path, monkeypatch
):
    output = tmp_path / "out"
    output.mkdir()
    original = cli.importlib.import_module

    def fail_import(name):
        if name.startswith("nsemine"):
            pytest.fail("no provider import allowed without evidence")
        return original(name)

    monkeypatch.setattr(cli.importlib, "import_module", fail_import)
    with pytest.raises(ValueError, match="evidence"):
        cli.acquire(
            symbol="TCS",
            session=SESSION,
            output=output,
            entitlement=tmp_path / "missing.txt",
            calendar="synthetic",
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
