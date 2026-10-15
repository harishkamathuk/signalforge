"""SF-083: bounded local nsemine raw acquisition and independent offline verification.

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
    return (json.dumps(value, sort_keys=True, allow_nan=False, separators=(",", ":"))
            + "\n").encode("utf-8")


def acquire(
    *, symbol: str, session: date, output: Path, entitlement: Path,
    calendar: str, revision: str, series: str = "EQ",
) -> dict[str, object]:
    """Acquire at most one declared session and preserve raw provider evidence.

    Caller must establish and document external rights and timestamp semantics.
    Acquisition stops after raw capture; no unsafe clock inference is performed.
    """
    if not symbol or not symbol.isascii() or not symbol.replace("-", "").isalnum():
        raise ValueError("provide an explicit NSE symbol")
    if series != "EQ":
        raise ValueError("SF-083 experiment is limited to the EQ series")
    if not calendar.strip() or not revision.strip():
        raise ValueError("calendar evidence and pinned revision are required")
    if session >= datetime.now(IST).date():
        raise ValueError("session must be a completed prior trading date")
    if not entitlement.is_file() or not entitlement.read_text(encoding="utf-8").strip():
        raise ValueError("provide a non-empty local source-use and retention evidence file")
    if not output.exists() or not output.is_dir():
        raise ValueError("create the private local output directory before acquisition")
    if any(output.iterdir()):
        raise FileExistsError("output directory must be empty; no implicit overwrite")
    # Check the installed SDK interface before any provider call.
    historical = importlib.import_module("nsemine.historical")
    call = historical.get_stock_historical_data
    expected = {"stock_symbol", "start_datetime", "end_datetime", "interval", "raw"}
    actual = inspect.signature(call).parameters
    if not expected.issubset(actual) or any(
        actual[name].kind == inspect.Parameter.POSITIONAL_ONLY for name in expected
    ):
        raise ValueError("installed nsemine historical function signature is incompatible")
    try:
        installed_version = importlib.metadata.version("nsemine")
    except importlib.metadata.PackageNotFoundError:
        installed_version = "unknown (source checkout or mocked install)"
    module_path = str(getattr(historical, "__file__", None) or "unavailable")
    start = datetime.combine(session, time(9, 15), tzinfo=IST)
    end = datetime.combine(session, time(15, 30), tzinfo=IST)
    response = call(
        stock_symbol=symbol, start_datetime=start, end_datetime=end,
        interval=1, raw=True,
    )
    if response is None:
        raise ValueError("nsemine returned no response; nothing persisted")
    if not isinstance(response, dict):
        raise ValueError("expected decoded dictionary from nsemine raw=True")
    raw = _json_bytes(response)
    if len(raw) > 20_000_000:
        raise ValueError("decoded provider response exceeds 20 MB bounded sample limit")
    digest = hashlib.sha256(raw).hexdigest()
    observed_at = datetime.now(UTC).isoformat()
    acquisition = {
        "status": "RAW_CAPTURED_CANONICAL_MAPPING_BLOCKED_PENDING_SOURCE_EVIDENCE",
        "provider": "nsemine",
        "symbol": symbol,
        "series": series,
        "session": session.isoformat(),
        "calendar_reference": calendar,
        "declared_revision": revision,
        "acquisition_api": "nsemine.historical.get_stock_historical_data",
        "parameters": {"interval": 1, "raw": True,
                       "start_datetime": start.isoformat(),
                       "end_datetime": end.isoformat()},
        "acquired_at_utc": observed_at,
        "sdk_decoded_json_sha256": digest,
        "evidence_representation": "deterministically re-encoded SDK-decoded JSON; NOT HTTP bytes",
        "installed_nsemine_version": installed_version,
        "installed_nsemine_module_path": module_path,
        "raw_size_bytes": len(raw),
        "local_entitlement_evidence": str(entitlement),
        "preflight_inputs_are_operator_attestations": True,
        "limitations": [
            "Raw response has not been independently interpreted or canonicalized",
            "nsemine timestamp and EQ identity semantics are unverified",
            "SDK historical symbol lookup does not explicitly enforce EQ series",
            "Not SF-079 Gate A approval or an SF-083 completed real-data acceptance",
        ],
    }
    # Publish both artifacts as a unit or remove our own partial writes.
    raw_path = output / "sdk-decoded-response.json"
    manifest_path = output / "acquisition-manifest.json"
    try:
        _write_exclusive(raw_path, raw)
        _write_exclusive(manifest_path, _json_bytes(acquisition))
    except Exception:
        # Do not silently retain a response that has no matching manifest.
        if manifest_path.exists():
            manifest_path.unlink()
        if raw_path.exists():
            raw_path.unlink()
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
    acquire_parser = modes.add_parser("acquire", help="capture raw evidence only")
    acquire_parser.add_argument("--symbol", required=True)
    acquire_parser.add_argument("--session", required=True, type=date.fromisoformat)
    acquire_parser.add_argument("--series", default="EQ")
    acquire_parser.add_argument("--output", type=Path, required=True)
    acquire_parser.add_argument("--entitlement-evidence", type=Path, required=True)
    acquire_parser.add_argument("--calendar-reference", required=True)
    acquire_parser.add_argument("--revision", required=True)
    verify_parser = modes.add_parser("offline-verify", help="load a frozen canonical ID")
    verify_parser.add_argument("--dataset-id", required=True)
    verify_parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.mode == "acquire":
            result = acquire(
                symbol=args.symbol, session=args.session, output=args.output,
                entitlement=args.entitlement_evidence, calendar=args.calendar_reference,
                revision=args.revision, series=args.series,
            )
        else:
            result = verify(output=args.output, dataset_id=args.dataset_id)
    except (ValueError, OSError, ImportError, AttributeError, TypeError,
            OverflowError, RecursionError, RuntimeError) as exc:
        print(f"SF-083 blocked: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
