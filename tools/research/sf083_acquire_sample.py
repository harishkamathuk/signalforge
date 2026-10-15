"""SF-083: bounded nsemine acquisition with fail-closed instrument identity evidence.

Deliberately DOES NOT reinterpret provider clocks or auto-canonicalize unknown
raw responses. This is a research CLI, not a production data adapter.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import importlib.metadata
import inspect
import json
import os
import sys
from datetime import UTC, date, datetime, time
from pathlib import Path

from signalforge.domain.ids import DatasetId
from signalforge.domain.time import IST
from signalforge.research.historical_bars import aggregate_one_minute_to_five_minute
from signalforge.research.historical_dataset_store import LocalHistoricalDatasetStore


def _write_exclusive(path: Path, payload: bytes) -> None:
    """Write evidence without silently replacing an existing acquisition."""
    with path.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, sort_keys=True, allow_nan=False, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def _require_callable_signature(
    call: object, expected: set[str], *, name: str
) -> None:
    if not callable(call):
        raise ValueError(f"installed nsemine is missing {name}")
    actual = inspect.signature(call).parameters
    if not expected.issubset(actual) or any(
        actual[param].kind == inspect.Parameter.POSITIONAL_ONLY for param in expected
    ):
        raise ValueError(f"installed nsemine {name} signature is incompatible")


def _provider_token(candidate: dict[str, object]) -> str:
    value = candidate.get("scripcode")
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return str(value)
    if isinstance(value, str) and value.isdigit() and int(value) > 0:
        return value
    raise ValueError("provider candidate token/scripcode is absent or malformed")


def _load_reference_evidence(
    path: Path | None,
    source_path: Path | None,
) -> tuple[dict[str, object] | None, str | None, str | None]:
    if path is None and source_path is None:
        return None, None, None
    if path is None or source_path is None:
        raise ValueError(
            "independent instrument-reference metadata and source snapshot are both required"
        )
    if not path.is_file():
        raise ValueError("independent instrument-reference evidence file does not exist")
    if not source_path.is_file():
        raise ValueError("independent instrument-reference source snapshot does not exist")

    raw = path.read_bytes()
    metadata_digest = hashlib.sha256(raw).hexdigest()
    source_bytes = source_path.read_bytes()
    if not source_bytes:
        raise ValueError("independent instrument-reference source snapshot is empty")
    source_digest = hashlib.sha256(source_bytes).hexdigest()

    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("independent instrument-reference evidence is not valid JSON") from exc
    if not isinstance(value, dict):
        raise ValueError("independent instrument-reference evidence must be a JSON object")
    required_strings = {
        "evidence_type": "independent_instrument_reference",
        "provider": "nsemine",
        "exchange": "NSE",
        "instrument_type": "Equity",
    }
    for field, expected in required_strings.items():
        if value.get(field) != expected:
            raise ValueError(
                f"independent instrument-reference evidence has invalid {field}"
            )
    for field in ("symbol", "series", "provider_token", "source_reference"):
        if not isinstance(value.get(field), str) or not str(value[field]).strip():
            raise ValueError(
                f"independent instrument-reference evidence is missing {field}"
            )
    declared_source_hash = value.get("source_content_sha256")
    if (
        not isinstance(declared_source_hash, str)
        or len(declared_source_hash) != 64
        or any(char not in "0123456789abcdef" for char in declared_source_hash)
    ):
        raise ValueError(
            "independent instrument-reference evidence requires a lowercase source hash"
        )
    if declared_source_hash != source_digest:
        raise ValueError(
            "independent instrument-reference source snapshot hash does not match metadata"
        )
    return value, metadata_digest, source_digest


def _reference_supports_candidate(
    reference: dict[str, object] | None,
    *,
    symbol: str,
    series: str,
    token: str,
) -> bool:
    if reference is None:
        return False
    return (
        str(reference.get("symbol", "")).upper() == symbol.upper()
        and str(reference.get("series", "")).upper() == series.upper()
        and reference.get("provider_token") == token
    )


def _select_equity_candidate(
    candidates: list[dict[str, object]],
    *,
    symbol: str,
    series: str,
    reference: dict[str, object] | None = None,
) -> tuple[dict[str, object], str, str]:
    """Select exactly one candidate whose evidence proves SYMBOL/SERIES."""
    requested_symbol = symbol.upper()
    requested_series = series.upper()
    composite = f"{requested_symbol}-{requested_series}"
    accepted: list[tuple[dict[str, object], str, str]] = []
    conflicts: list[str] = []

    for index, candidate in enumerate(candidates):
        original_symbol = candidate.get("symbol")
        provider_type = candidate.get("type")
        provider_series = candidate.get("series")

        if not isinstance(original_symbol, str):
            continue
        original_upper = original_symbol.upper()
        base_matches = original_upper == requested_symbol or original_upper.startswith(
            f"{requested_symbol}-"
        )
        if not base_matches:
            continue

        if not isinstance(provider_type, str) or provider_type.casefold() != "equity":
            conflicts.append(
                f"candidate {index} for {original_symbol!r} is not cash Equity"
            )
            continue

        try:
            token = _provider_token(candidate)
        except ValueError as exc:
            conflicts.append(f"candidate {index} for {original_symbol!r}: {exc}")
            continue

        series_from_symbol = original_upper == composite
        series_from_field = (
            isinstance(provider_series, str)
            and provider_series.upper() == requested_series
            and original_upper == requested_symbol
        )
        series_from_reference = (
            original_upper == requested_symbol
            and _reference_supports_candidate(
                reference, symbol=symbol, series=series, token=token
            )
        )
        if not (series_from_symbol or series_from_field or series_from_reference):
            conflicts.append(
                f"candidate {index} for {original_symbol!r} does not establish "
                f"series {requested_series}"
            )
            continue

        if series_from_symbol:
            basis = "original_provider_symbol_exact_symbol_series"
        elif series_from_field:
            basis = "original_provider_symbol_plus_series_field"
        else:
            basis = "independent_reference_exact_token_symbol_series"
        accepted.append((candidate, token, basis))

    if len(accepted) != 1:
        detail = "; ".join(conflicts) if conflicts else "no exact supported candidate"
        if len(accepted) > 1:
            detail = f"{len(accepted)} indistinguishable supported candidates"
        raise ValueError(f"instrument identity verification failed: {detail}")

    return accepted[0]


def acquire(
    *,
    symbol: str,
    session: date,
    output: Path,
    entitlement: Path,
    calendar: str,
    revision: str,
    series: str = "EQ",
    instrument_reference: Path | None = None,
    instrument_reference_source: Path | None = None,
) -> dict[str, object]:
    """Resolve and verify one instrument, then acquire one declared session."""
    if not symbol or not symbol.isascii() or not symbol.replace("-", "").isalnum():
        raise ValueError("provide an explicit NSE symbol")
    if series != "EQ":
        raise ValueError("SF-083 experiment is limited to the EQ series")
    if not calendar.strip() or not revision.strip():
        raise ValueError("calendar evidence and pinned revision are required")
    if session >= datetime.now(IST).date():
        raise ValueError("session must be a completed prior trading date")
    if not entitlement.is_file() or not entitlement.read_text(encoding="utf-8").strip():
        raise ValueError(
            "provide a non-empty local source-use and retention evidence file"
        )
    if not output.exists() or not output.is_dir():
        raise ValueError("create the private local output directory before acquisition")
    if any(output.iterdir()):
        raise FileExistsError("output directory must be empty; no implicit overwrite")

    historical = importlib.import_module("nsemine.historical")
    search = getattr(historical, "search_stock_instruments", None)
    fetch = getattr(historical, "get_stock_historical_data_by_instrument", None)
    _require_callable_signature(
        search,
        {"stock_symbol", "segment", "scrip_type"},
        name="search_stock_instruments",
    )
    _require_callable_signature(
        fetch,
        {
            "symbol",
            "token",
            "symbol_type",
            "start_datetime",
            "end_datetime",
            "interval",
            "raw",
        },
        name="get_stock_historical_data_by_instrument",
    )

    try:
        installed_version = importlib.metadata.version("nsemine")
    except importlib.metadata.PackageNotFoundError:
        installed_version = "unknown (source checkout or mocked install)"
    module_path = str(vars(historical).get("__file__") or "unavailable")

    reference, reference_file_digest, reference_source_digest = _load_reference_evidence(
        instrument_reference, instrument_reference_source
    )
    if reference is not None and (
        str(reference["symbol"]).upper() != symbol.upper()
        or str(reference["series"]).upper() != series.upper()
    ):
        raise ValueError(
            "independent instrument-reference evidence contradicts requested identity"
        )

    search_parameters = {"stock_symbol": symbol, "segment": series, "scrip_type": None}
    raw_candidates = search(**search_parameters)
    if not isinstance(raw_candidates, list) or any(
        not isinstance(candidate, dict) for candidate in raw_candidates
    ):
        raise ValueError("provider resolver returned an invalid candidate collection")
    candidates: list[dict[str, object]] = raw_candidates
    selected, token, match_basis = _select_equity_candidate(
        candidates, symbol=symbol, series=series, reference=reference
    )
    selected_symbol = selected.get("symbol")
    selected_type = selected.get("type")
    if not isinstance(selected_symbol, str) or not isinstance(selected_type, str):
        raise ValueError("selected provider candidate lacks required identity fields")

    resolver_evidence = {
        "requested_symbol": symbol,
        "requested_series": series,
        "provider_search_api": "nsemine.historical.search_stock_instruments",
        "provider_search_parameters": search_parameters,
        "candidate_count": len(candidates),
        "candidates": candidates,
        "selected_candidate": selected,
        "selected_provider_symbol": selected_symbol,
        "selected_provider_type": selected_type,
        "selected_provider_series": selected.get("series"),
        "selected_provider_token": token,
        "selection_basis": match_basis,
        "verification_outcome": "VERIFIED_EXACT_PROVIDER_IDENTITY",
        "independent_reference_evidence": reference,
        "independent_reference_file_sha256": reference_file_digest,
        "independent_reference_source_sha256": reference_source_digest,
    }
    resolver_bytes = _json_bytes(resolver_evidence)
    resolver_digest = hashlib.sha256(resolver_bytes).hexdigest()

    start = datetime.combine(session, time(9, 15), tzinfo=IST)
    end = datetime.combine(session, time(15, 30), tzinfo=IST)
    request_evidence = {
        "api": "nsemine.historical.get_stock_historical_data_by_instrument",
        "symbol": symbol,
        "provider_token": token,
        "provider_symbol_type": selected_type,
        "start_datetime": start.isoformat(),
        "end_datetime": end.isoformat(),
        "interval": 1,
        "raw": True,
        "linkage": "validated provider token supplied directly; no second resolution",
    }
    response = fetch(
        symbol=symbol,
        token=token,
        symbol_type=selected_type,
        start_datetime=start,
        end_datetime=end,
        interval=1,
        raw=True,
    )
    if response is None:
        raise ValueError("nsemine returned no historical response; nothing persisted")
    if not isinstance(response, dict):
        raise ValueError("expected decoded dictionary from nsemine raw=True")
    raw = _json_bytes(response)
    if len(raw) > 20_000_000:
        raise ValueError("decoded provider response exceeds 20 MB bounded sample limit")

    response_digest = hashlib.sha256(raw).hexdigest()
    observed_at = datetime.now(UTC).isoformat()
    acquisition = {
        "status": (
            "RAW_CAPTURED_INSTRUMENT_IDENTITY_VERIFIED_"
            "CANONICAL_MAPPING_BLOCKED_PENDING_SOURCE_EVIDENCE"
        ),
        "provider": "nsemine",
        "symbol": symbol,
        "series": series,
        "session": session.isoformat(),
        "calendar_reference": calendar,
        "declared_revision": revision,
        "installed_nsemine_version": installed_version,
        "installed_nsemine_module_path": module_path,
        "acquired_at_utc": observed_at,
        "sdk_decoded_json_sha256": response_digest,
        "resolver_evidence_sha256": resolver_digest,
        "resolver_evidence_file": "resolver-evidence.json",
        "instrument_verification": {
            "outcome": "VERIFIED_EXACT_PROVIDER_IDENTITY",
            "selected_provider_symbol": selected_symbol,
            "selected_provider_type": selected_type,
            "selected_provider_series": selected.get("series"),
            "selected_provider_token": token,
            "selection_basis": match_basis,
        },
        "historical_request_token_linkage": request_evidence,
        "evidence_representation": (
            "deterministically re-encoded SDK-decoded JSON; NOT HTTP bytes"
        ),
        "raw_size_bytes": len(raw),
        "local_entitlement_evidence": str(entitlement),
        "source_fact_vs_attestation": {
            "provider_candidates_and_selected_token": "provider source facts",
            "independent_reference_evidence": (
                "metadata verified against a retained external source snapshot hash"
                if reference is not None
                else "not supplied/not required"
            ),
            "historical_request_token": "direct SDK call argument recorded by this CLI",
            "declared_revision": "operator attestation",
            "calendar_reference": "operator attestation/reference",
            "entitlement_evidence_path": "operator-supplied local evidence pointer",
        },
        "limitations": [
            "Historical response is not yet canonicalized by this command",
            "Timestamp interpretation remains evidence-qualified under SF-081",
            "Declared fork revision is not cryptographically derived from the installed package",
            "Not SF-079 Gate A approval or an SF-083 completed real-data acceptance",
        ],
    }

    resolver_path = output / "resolver-evidence.json"
    raw_path = output / "sdk-decoded-response.json"
    manifest_path = output / "acquisition-manifest.json"
    try:
        _write_exclusive(resolver_path, resolver_bytes)
        _write_exclusive(raw_path, raw)
        _write_exclusive(manifest_path, _json_bytes(acquisition))
    except Exception:
        for path in (manifest_path, raw_path, resolver_path):
            if path.exists():
                path.unlink()
        raise
    return acquisition


def verify(*, output: Path, dataset_id: str) -> dict[str, object]:
    """Load stored canonical data without importing nsemine or reaching a provider."""
    if len(dataset_id) != 64 or any(c not in "0123456789abcdef" for c in dataset_id):
        raise ValueError("dataset id must be a lowercase 64-digit SHA-256")
    dataset = LocalHistoricalDatasetStore(output).load(DatasetId(dataset_id))
    candles = aggregate_one_minute_to_five_minute(dataset)
    qualities = {"valid": 0, "incomplete": 0, "missing": 0}
    for candle in candles:
        qualities[candle.quality.value] += 1
    return {
        "dataset_id": str(dataset.dataset_id),
        "content_hash": dataset.content_hash,
        "instrument_id": str(dataset.manifest.instrument_id),
        "canonical_bars": len(dataset.bars),
        "raw_rows": dataset.manifest.raw_row_count,
        "missing_1m": dataset.manifest.missing_interval_count,
        "duplicates": dataset.manifest.duplicate_observation_count,
        "corrupt_rejected": dataset.manifest.corrupt_rejected_count,
        "derived_5m": qualities,
    }


def main(argv: list[str] | None = None) -> int:
    """Run a single bounded acquisition or independent local verification."""
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_subparsers(dest="mode", required=True)
    acquire_parser = modes.add_parser(
        "acquire", help="verify instrument identity and capture raw evidence"
    )
    acquire_parser.add_argument("--symbol", required=True)
    acquire_parser.add_argument("--session", required=True, type=date.fromisoformat)
    acquire_parser.add_argument("--series", default="EQ")
    acquire_parser.add_argument("--output", type=Path, required=True)
    acquire_parser.add_argument("--entitlement-evidence", type=Path, required=True)
    acquire_parser.add_argument("--calendar-reference", required=True)
    acquire_parser.add_argument("--revision", required=True)
    acquire_parser.add_argument(
        "--instrument-reference-evidence",
        type=Path,
        help=(
            "optional independent-reference metadata JSON; required only when "
            "provider candidate fields do not themselves establish EQ identity"
        ),
    )
    acquire_parser.add_argument(
        "--instrument-reference-source",
        type=Path,
        help=(
            "local retained source snapshot whose SHA-256 must match the independent "
            "reference metadata"
        ),
    )
    verify_parser = modes.add_parser(
        "offline-verify", help="load a frozen canonical ID"
    )
    verify_parser.add_argument("--dataset-id", required=True)
    verify_parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.mode == "acquire":
            result = acquire(
                symbol=args.symbol,
                session=args.session,
                output=args.output,
                entitlement=args.entitlement_evidence,
                calendar=args.calendar_reference,
                revision=args.revision,
                series=args.series,
                instrument_reference=args.instrument_reference_evidence,
                instrument_reference_source=args.instrument_reference_source,
            )
        else:
            result = verify(output=args.output, dataset_id=args.dataset_id)
    except (
        ValueError,
        OSError,
        ImportError,
        AttributeError,
        TypeError,
        OverflowError,
        RecursionError,
        RuntimeError,
    ) as exc:
        print(f"SF-083 blocked: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
