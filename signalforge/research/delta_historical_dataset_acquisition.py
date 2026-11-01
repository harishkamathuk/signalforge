"""SF-088 deterministic Delta BTCUSD one-year research dataset acquisition.

This module is deliberately provider-specific. It acquires protected local evidence,
proves two-pass semantic coherence, maps through the existing canonical boundary, and
persists through the provider-neutral historical dataset store. It performs no strategy
evaluation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from signalforge.domain.ids import DatasetId, InstrumentId
from signalforge.research.delta_historical_qualification import (
    DeltaCandle,
    DeltaProductSnapshot,
    DeltaRawCapture,
    DeltaTimestampContract,
    DeltaTimestampLabel,
    acquire_delta_response,
    canonicalize_delta_one_minute,
    parse_delta_candles_response,
    parse_delta_product_response,
    summarize_delta_candles,
)
from signalforge.research.historical_bars import aggregate_one_minute_to_five_minute
from signalforge.research.historical_dataset_store import LocalHistoricalDatasetStore

SF088_START = datetime(2025, 10, 30, tzinfo=UTC)
SF088_END = datetime(2026, 10, 30, tzinfo=UTC)
SF088_EXPECTED_MINUTES = 525_600
SF088_CHUNK_MINUTES = 2_000
SF088_ACQUISITION_VERSION = "sf088-delta-one-year-v1"
SF088_CANONICALISATION_VERSION = "delta-traded-v1"
SF088_INSTRUMENT_ID = InstrumentId("DELTA:BTCUSD")
SF088_SYMBOL = "BTCUSD"

_TIMESTAMP_CONTRACT = DeltaTimestampContract(
    timestamp_unit="seconds",
    timestamp_label=DeltaTimestampLabel.CANDLE_OPEN,
    start_inclusive=True,
    end_inclusive=True,
)


class DeltaResearchDisposition(StrEnum):
    """SF-088 dataset-readiness outcomes."""

    READY = "READY_FOR_BTC_STRATEGY_RESEARCH"
    PENDING_OFFLINE_VERIFICATION = "PENDING_OFFLINE_VERIFICATION"
    PARTIAL = "PARTIAL"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True, slots=True)
class DeltaResearchChunk:
    """One deterministic canonical/provider request partition."""

    index: int
    start: datetime
    end: datetime
    provider_start: int
    provider_end: int

    @property
    def expected_minutes(self) -> int:
        """Return exact one-minute intervals represented by this chunk."""

        return int((self.end - self.start) / timedelta(minutes=1))

    @property
    def identity(self) -> str:
        """Return a stable chunk identity independent of acquisition time."""

        return (
            f"{self.index:06d}:"
            f"{self.start.isoformat()}:{self.end.isoformat()}:"
            f"{self.provider_start}:{self.provider_end}"
        )


@dataclass(frozen=True, slots=True)
class DeltaCapturedChunk:
    """Sanitized identity for one locally retained raw chunk response."""

    chunk: DeltaResearchChunk
    raw_sha256: str
    semantic_sha256: str
    row_count: int
    duplicate_count: int
    missing_count: int
    request_url: str
    acquired_at: datetime


@dataclass(frozen=True, slots=True)
class DeltaAcquisitionPass:
    """One complete acquisition pass across the predeclared chunk plan."""

    pass_name: str
    product: DeltaProductSnapshot
    chunks: tuple[DeltaCapturedChunk, ...]

    @property
    def semantic_sha256(self) -> str:
        """Hash the ordered semantic evidence for one full pass."""

        return _sha256_json(
            {
                "pass_name": self.pass_name,
                "product_semantic_sha256": self.product.semantic_sha256,
                "chunks": [
                    {
                        "identity": item.chunk.identity,
                        "semantic_sha256": item.semantic_sha256,
                        "row_count": item.row_count,
                        "duplicate_count": item.duplicate_count,
                        "missing_count": item.missing_count,
                    }
                    for item in self.chunks
                ],
            }
        )


def build_sf088_chunk_plan(
    *,
    start: datetime = SF088_START,
    end: datetime = SF088_END,
    chunk_minutes: int = SF088_CHUNK_MINUTES,
) -> tuple[DeltaResearchChunk, ...]:
    """Build the deterministic bounded request plan for SF-088."""

    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("SF-088 bounds must be timezone-aware")
    start_utc, end_utc = start.astimezone(UTC), end.astimezone(UTC)
    if start_utc.second or start_utc.microsecond or end_utc.second or end_utc.microsecond:
        raise ValueError("SF-088 bounds must align to exact minutes")
    if end_utc <= start_utc:
        raise ValueError("SF-088 end must be after start")
    if chunk_minutes <= 0:
        raise ValueError("SF-088 chunk_minutes must be positive")

    chunks: list[DeltaResearchChunk] = []
    cursor = start_utc
    index = 0
    step = timedelta(minutes=chunk_minutes)
    while cursor < end_utc:
        chunk_end = min(cursor + step, end_utc)
        provider_start, provider_end = _TIMESTAMP_CONTRACT.provider_bounds(
            cursor,
            chunk_end,
        )
        chunks.append(
            DeltaResearchChunk(
                index=index,
                start=cursor,
                end=chunk_end,
                provider_start=provider_start,
                provider_end=provider_end,
            )
        )
        cursor = chunk_end
        index += 1
    return tuple(chunks)


def validate_product_applicability(
    product: DeltaProductSnapshot,
    *,
    research_start: datetime = SF088_START,
) -> str:
    """Prove a single captured product rule predates the complete research interval.

    This is deliberately conservative. If Delta reports that the product was updated
    during/after the research start, SF-088 must obtain an effective-dated metadata
    schedule instead of applying the current snapshot retrospectively.
    """

    start = research_start.astimezone(UTC)
    if product.created_at is None or product.updated_at is None:
        raise ValueError(
            "Delta product created_at/updated_at are required for historical applicability"
        )
    if product.created_at > start:
        raise ValueError("Delta BTCUSD product was created after the research start")
    if product.updated_at > start:
        raise ValueError(
            "Delta BTCUSD product metadata changed after the research start; "
            "effective-dated metadata evidence is required"
        )
    return _sha256_json(
        {
            "coverage_start": start.isoformat(),
            "product_semantic_sha256": product.semantic_sha256,
            "product_created_at": product.created_at.isoformat(),
            "product_updated_at": product.updated_at.isoformat(),
        }
    )


def _canonical_decimal(value: Decimal) -> str:
    normalized = value.normalize()
    if normalized == 0:
        return "0"
    return format(normalized, "f")


def _candle_semantic_sha256(candles: tuple[DeltaCandle, ...]) -> str:
    ordered = sorted(candles, key=lambda candle: candle.time)
    return _sha256_json(
        [
            {
                "time": item.time,
                "open": _canonical_decimal(item.open),
                "high": _canonical_decimal(item.high),
                "low": _canonical_decimal(item.low),
                "close": _canonical_decimal(item.close),
                "volume": _canonical_decimal(item.volume),
            }
            for item in ordered
        ]
    )


def _sha256_json(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def _write_once(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())


def _write_json_once(path: Path, payload: object) -> None:
    _write_once(
        path,
        (json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=True) + "\n").encode(
            "utf-8"
        ),
    )


def _verify_evidence_source_url(
    request_url: str,
    *,
    path: str,
    params: dict[str, str | int] | None = None,
) -> None:
    """Require exact canonical Delta India source and frozen request parameters."""
    parsed = urlsplit(request_url)
    if (
        parsed.scheme != "https"
        or parsed.netloc != "api.india.delta.exchange"
        or parsed.path != path
        or parsed.fragment
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ValueError("SF-088 evidence source is not canonical Delta India")
    actual_params = parse_qs(parsed.query, keep_blank_values=True)
    expected_params = (
        {key: [str(value)] for key, value in params.items()}
        if params is not None
        else {}
    )
    if actual_params != expected_params:
        raise ValueError("SF-088 evidence request parameters contradict frozen plan")


def _chunk_paths(pass_dir: Path, chunk: DeltaResearchChunk) -> tuple[Path, Path]:
    stem = f"chunk-{chunk.index:06d}"
    return pass_dir / f"{stem}.json", pass_dir / f"{stem}.meta.json"


def _chunk_meta_payload(
    captured: DeltaCapturedChunk,
) -> dict[str, object]:
    return {
        "chunk_identity": captured.chunk.identity,
        "canonical_start": captured.chunk.start.isoformat(),
        "canonical_end": captured.chunk.end.isoformat(),
        "provider_start": captured.chunk.provider_start,
        "provider_end": captured.chunk.provider_end,
        "request_url": captured.request_url,
        "acquired_at": captured.acquired_at.isoformat(),
        "row_count": captured.row_count,
        "duplicate_count": captured.duplicate_count,
        "missing_count": captured.missing_count,
        "raw_sha256": captured.raw_sha256,
        "semantic_sha256": captured.semantic_sha256,
        "acquisition_version": SF088_ACQUISITION_VERSION,
    }


def _load_existing_chunk(
    *,
    raw_path: Path,
    meta_path: Path,
    chunk: DeltaResearchChunk,
    product: DeltaProductSnapshot,
    evidence_only: bool = False,
) -> DeltaCapturedChunk:
    raw = raw_path.read_bytes()
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    if not isinstance(meta, dict) or meta.get("chunk_identity") != chunk.identity:
        raise ValueError("existing SF-088 chunk metadata contradicts deterministic plan")
    raw_sha256 = hashlib.sha256(raw).hexdigest()
    if meta.get("raw_sha256") != raw_sha256:
        raise ValueError("existing SF-088 raw chunk digest mismatch")
    capture = DeltaRawCapture(
        request_url=str(meta.get("request_url")),
        acquired_at=datetime.fromisoformat(str(meta.get("acquired_at"))),
        content_sha256=raw_sha256,
        content=raw,
    )
    if evidence_only:
        _verify_evidence_source_url(
            capture.request_url,
            path="/v2/history/candles",
            params={
                "resolution": "1m",
                "symbol": SF088_SYMBOL,
                "start": chunk.provider_start,
                "end": chunk.provider_end,
            },
        )
    candles = parse_delta_candles_response(capture)
    semantic_sha256 = _candle_semantic_sha256(candles)
    if meta.get("semantic_sha256") != semantic_sha256:
        raise ValueError("existing SF-088 chunk semantic digest mismatch")
    summary = summarize_delta_candles(candles, tick_size=product.tick_size)
    if not evidence_only and (
        not summary.integral_volume or not summary.tick_aligned_prices
    ):
        raise ValueError("existing SF-088 chunk violates qualified price/volume semantics")
    unique_times = {item.time for item in candles}
    expected_times = {
        int((chunk.start + timedelta(minutes=offset)).timestamp())
        for offset in range(chunk.expected_minutes)
    }
    if not unique_times.issubset(expected_times):
        raise ValueError("existing SF-088 chunk contains out-of-grid timestamps")
    missing_count = len(expected_times - unique_times)
    duplicate_count = len(candles) - len(unique_times)
    if meta.get("missing_count") != missing_count or (
        meta.get("duplicate_count") != duplicate_count
    ):
        raise ValueError("existing SF-088 chunk quality counts disagree with raw evidence")
    return DeltaCapturedChunk(
        chunk=chunk,
        raw_sha256=raw_sha256,
        semantic_sha256=semantic_sha256,
        row_count=len(candles),
        duplicate_count=duplicate_count,
        missing_count=missing_count,
        request_url=capture.request_url,
        acquired_at=capture.acquired_at,
    )


def acquire_sf088_pass(
    *,
    output_dir: Path,
    pass_name: str,
    chunk_plan: tuple[DeltaResearchChunk, ...],
    evidence_only: bool = False,
) -> DeltaAcquisitionPass:
    """Acquire or resume one write-once full pass of the SF-088 chunk plan."""

    if not pass_name.strip():
        raise ValueError("SF-088 pass_name must not be empty")
    pass_dir = output_dir / pass_name
    pass_dir.mkdir(parents=True, exist_ok=True)

    product_path = pass_dir / "product.json"
    product_meta_path = pass_dir / "product.meta.json"
    if product_path.exists() or product_meta_path.exists():
        if not product_path.exists() or not product_meta_path.exists():
            raise ValueError("incomplete existing SF-088 product evidence")
        product_raw = product_path.read_bytes()
        meta = json.loads(product_meta_path.read_text(encoding="utf-8"))
        if not isinstance(meta, dict):
            raise ValueError("existing SF-088 product metadata must be an object")
        product_sha = hashlib.sha256(product_raw).hexdigest()
        if meta.get("raw_sha256") != product_sha:
            raise ValueError("existing SF-088 product evidence digest mismatch")
        capture = DeltaRawCapture(
            request_url=str(meta.get("request_url")),
            acquired_at=datetime.fromisoformat(str(meta.get("acquired_at"))),
            content_sha256=product_sha,
            content=product_raw,
        )
    else:
        capture = acquire_delta_response(f"/v2/products/{SF088_SYMBOL}")
        if evidence_only:
            _verify_evidence_source_url(
                capture.request_url,
                path=f"/v2/products/{SF088_SYMBOL}",
            )
        _write_once(product_path, capture.content)
        _write_json_once(
            product_meta_path,
            {
                "request_url": capture.request_url,
                "acquired_at": capture.acquired_at.isoformat(),
                "raw_sha256": capture.content_sha256,
                "acquisition_version": SF088_ACQUISITION_VERSION,
            },
        )

    if evidence_only:
        _verify_evidence_source_url(
            capture.request_url,
            path=f"/v2/products/{SF088_SYMBOL}",
        )
    product = parse_delta_product_response(capture, expected_symbol=SF088_SYMBOL)
    if not evidence_only:
        validate_product_applicability(product)

    captured_chunks: list[DeltaCapturedChunk] = []
    for chunk in chunk_plan:
        raw_path, meta_path = _chunk_paths(pass_dir, chunk)
        if raw_path.exists() or meta_path.exists():
            if not raw_path.exists() or not meta_path.exists():
                raise ValueError(f"incomplete existing SF-088 chunk evidence: {chunk.identity}")
            captured_chunks.append(
                _load_existing_chunk(
                    raw_path=raw_path,
                    meta_path=meta_path,
                    chunk=chunk,
                    product=product,
                    evidence_only=evidence_only,
                )
            )
            continue

        response = acquire_delta_response(
            "/v2/history/candles",
            params={
                "resolution": "1m",
                "symbol": SF088_SYMBOL,
                "start": chunk.provider_start,
                "end": chunk.provider_end,
            },
        )
        if evidence_only:
            _verify_evidence_source_url(
                response.request_url,
                path="/v2/history/candles",
                params={
                    "resolution": "1m",
                    "symbol": SF088_SYMBOL,
                    "start": chunk.provider_start,
                    "end": chunk.provider_end,
                },
            )
        # Preserve first-seen raw evidence even if semantic/structural parsing
        # fails. An incomplete raw/meta pair then fails closed on restart.
        if evidence_only:
            _write_once(raw_path, response.content)
        candles = parse_delta_candles_response(response)
        summary = summarize_delta_candles(candles, tick_size=product.tick_size)
        if not summary.exact_minute_aligned:
            raise ValueError(f"Delta chunk has non-minute timestamp: {chunk.identity}")
        if not evidence_only and not summary.integral_volume:
            raise ValueError(f"Delta chunk has fractional contract volume: {chunk.identity}")
        if not evidence_only and not summary.tick_aligned_prices:
            raise ValueError(f"Delta chunk has off-tick price: {chunk.identity}")

        unique_times = {item.time for item in candles}
        expected_times = {
            int((chunk.start + timedelta(minutes=offset)).timestamp())
            for offset in range(chunk.expected_minutes)
        }
        if not unique_times.issubset(expected_times):
            raise ValueError(f"Delta chunk has out-of-grid timestamp: {chunk.identity}")
        duplicate_count = len(candles) - len(unique_times)
        captured = DeltaCapturedChunk(
            chunk=chunk,
            raw_sha256=response.content_sha256,
            semantic_sha256=_candle_semantic_sha256(candles),
            row_count=len(candles),
            duplicate_count=duplicate_count,
            missing_count=len(expected_times - unique_times),
            request_url=response.request_url,
            acquired_at=response.acquired_at,
        )
        if not evidence_only:
            _write_once(raw_path, response.content)
        _write_json_once(meta_path, _chunk_meta_payload(captured))
        captured_chunks.append(captured)

    return DeltaAcquisitionPass(
        pass_name=pass_name,
        product=product,
        chunks=tuple(captured_chunks),
    )


def acquire_sf088_evidence_only(*, evidence_dir: Path) -> dict[str, object]:
    """Capture immutable source evidence without historical metadata qualification.

    The explicit evidence-only subdirectory prevents strict canonical acquisition from
    mistaking these captures for historically qualified input. No dataset store is used.
    """
    plan = build_sf088_chunk_plan()
    if sum(chunk.expected_minutes for chunk in plan) != SF088_EXPECTED_MINUTES:
        raise ValueError("SF-088 evidence-only chunk plan does not cover frozen horizon")

    protected_dir = evidence_dir / "evidence-only"
    first = acquire_sf088_pass(
        output_dir=protected_dir,
        pass_name="pass-1",
        chunk_plan=plan,
        evidence_only=True,
    )
    second = acquire_sf088_pass(
        output_dir=protected_dir,
        pass_name="pass-2",
        chunk_plan=plan,
        evidence_only=True,
    )
    # Structural/semantic response coherence is observable without historical
    # product-rule applicability; do not reuse strict canonical qualification.
    if first.product.semantic_sha256 != second.product.semantic_sha256:
        raise ValueError("Delta product semantics changed between evidence-only passes")
    if len(first.chunks) != len(plan) or len(second.chunks) != len(plan):
        raise ValueError("SF-088 evidence-only pass does not cover the complete chunk plan")
    changes = [
        left.chunk.identity
        for left, right in zip(first.chunks, second.chunks, strict=True)
        if left.chunk.identity != right.chunk.identity
        or left.semantic_sha256 != right.semantic_sha256
    ]
    if changes:
        raise ValueError(
            "Delta evidence-only historical semantic revisions; retain both passes: "
            + ", ".join(changes[:5])
        )

    missing_fields = [
        field
        for field in ("created_at", "updated_at")
        if getattr(first.product, field) is None
    ]
    generation_identity = _sha256_json(
        {
            "version": SF088_ACQUISITION_VERSION,
            "source_origin": first.product.api_origin,
            "product_semantic_sha256": first.product.semantic_sha256,
            "frozen_start": SF088_START.isoformat(),
            "frozen_end": SF088_END.isoformat(),
            "chunk_identities": [chunk.identity for chunk in plan],
            "source_candle_semantics": [
                chunk.semantic_sha256 for chunk in first.chunks
            ],
        }
    )
    report: dict[str, object] = {
        "acquisition_generation_identity": generation_identity,
        "chunk_identities": [chunk.identity for chunk in plan],
        "mode": "EVIDENCE_ONLY",
        "disposition": "UNQUALIFIED_SOURCE_EVIDENCE",
        "historical_metadata_applicability": "UNRESOLVED",
        "missing_product_metadata_fields": missing_fields,
        "source_api_origin": first.product.api_origin,
        "source_product_id": first.product.product_id,
        "source_symbol": first.product.symbol,
        "source_product_semantic_sha256": first.product.semantic_sha256,
        "frozen_start": SF088_START.isoformat(),
        "frozen_end": SF088_END.isoformat(),
        "expected_minutes": SF088_EXPECTED_MINUTES,
        "chunk_count_per_pass": len(plan),
        "first_pass_raw_sha256": [chunk.raw_sha256 for chunk in first.chunks],
        "second_pass_raw_sha256": [chunk.raw_sha256 for chunk in second.chunks],
        "first_pass_semantic_sha256": [chunk.semantic_sha256 for chunk in first.chunks],
        "second_pass_semantic_sha256": [chunk.semantic_sha256 for chunk in second.chunks],
        "acquisition_version": SF088_ACQUISITION_VERSION,
        "canonical_dataset_published": False,
        "strategy_research_eligible": False,
    }
    report["report_sha256"] = _sha256_json(report)
    report_path = protected_dir / "evidence-only-report.json"
    if report_path.exists():
        if json.loads(report_path.read_text(encoding="utf-8")) != report:
            raise ValueError("existing SF-088 evidence-only report differs")
    else:
        _write_json_once(report_path, report)
    return report


def assert_two_pass_coherence(
    first: DeltaAcquisitionPass,
    second: DeltaAcquisitionPass,
) -> None:
    """Require exact semantic equality across the complete two-pass horizon."""

    if first.product.semantic_sha256 != second.product.semantic_sha256:
        raise ValueError("Delta product semantic identity changed between SF-088 passes")
    first_schedule = validate_product_applicability(first.product)
    second_schedule = validate_product_applicability(second.product)
    if first_schedule != second_schedule:
        raise ValueError("Delta product metadata applicability changed between SF-088 passes")
    if len(first.chunks) != len(second.chunks):
        raise ValueError("SF-088 acquisition passes have different chunk counts")
    for left, right in zip(first.chunks, second.chunks, strict=True):
        if left.chunk.identity != right.chunk.identity:
            raise ValueError("SF-088 acquisition passes use different chunk plans")
        if left.semantic_sha256 != right.semantic_sha256:
            raise ValueError(
                f"Delta historical semantic revision detected for {left.chunk.identity}"
            )


def _load_pass_candles(
    *,
    output_dir: Path,
    acquisition_pass: DeltaAcquisitionPass,
) -> tuple[DeltaCandle, ...]:
    candles: list[DeltaCandle] = []
    pass_dir = output_dir / acquisition_pass.pass_name
    for item in acquisition_pass.chunks:
        raw_path, meta_path = _chunk_paths(pass_dir, item.chunk)
        loaded = _load_existing_chunk(
            raw_path=raw_path,
            meta_path=meta_path,
            chunk=item.chunk,
            product=acquisition_pass.product,
        )
        if loaded.semantic_sha256 != item.semantic_sha256:
            raise ValueError("SF-088 pass evidence changed after acquisition")
        raw = raw_path.read_bytes()
        capture = DeltaRawCapture(
            request_url=loaded.request_url,
            acquired_at=loaded.acquired_at,
            content_sha256=loaded.raw_sha256,
            content=raw,
        )
        candles.extend(parse_delta_candles_response(capture))
    return tuple(candles)


def _missing_minute_evidence(
    candles: tuple[DeltaCandle, ...],
) -> list[dict[str, str]]:
    observed = {item.time for item in candles}
    evidence: list[dict[str, str]] = []
    cursor = SF088_START
    while cursor < SF088_END:
        epoch = int(cursor.timestamp())
        if epoch not in observed:
            evidence.append(
                {
                    "interval_start": cursor.isoformat(),
                    "classification": "unresolved_absence",
                }
            )
        cursor += timedelta(minutes=1)
    return evidence


def _storage_content_manifest_sha256(
    *,
    store_dir: Path,
    dataset_id: DatasetId,
) -> str:
    directory = store_dir / str(dataset_id)
    path = directory / "content-manifest.json"
    if not path.is_file():
        raise ValueError("SF-088 requires the Parquet content manifest for offline evidence")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _acquisition_run_manifest(
    *,
    first: DeltaAcquisitionPass,
    second: DeltaAcquisitionPass,
    metadata_schedule_sha256: str,
) -> dict[str, object]:
    return {
        "acquisition_version": SF088_ACQUISITION_VERSION,
        "canonicalisation_version": SF088_CANONICALISATION_VERSION,
        "instrument_id": str(SF088_INSTRUMENT_ID),
        "symbol": SF088_SYMBOL,
        "start": SF088_START.isoformat(),
        "end": SF088_END.isoformat(),
        "expected_minutes": SF088_EXPECTED_MINUTES,
        "metadata_schedule_sha256": metadata_schedule_sha256,
        "passes": [
            {
                "name": acquisition_pass.pass_name,
                "semantic_sha256": acquisition_pass.semantic_sha256,
                "product_semantic_sha256": acquisition_pass.product.semantic_sha256,
                "chunks": [
                    {
                        "identity": item.chunk.identity,
                        "raw_sha256": item.raw_sha256,
                        "semantic_sha256": item.semantic_sha256,
                        "row_count": item.row_count,
                        "duplicate_count": item.duplicate_count,
                        "missing_count": item.missing_count,
                    }
                    for item in acquisition_pass.chunks
                ],
            }
            for acquisition_pass in (first, second)
        ],
    }


def finalize_sf088_dataset(
    *,
    evidence_dir: Path,
    store_dir: Path,
    first: DeltaAcquisitionPass,
    second: DeltaAcquisitionPass,
) -> dict[str, object]:
    """Freeze a coherent SF-088 acquisition generation and persist canonically."""

    assert_two_pass_coherence(first, second)
    metadata_schedule_sha256 = validate_product_applicability(first.product)
    run_manifest = _acquisition_run_manifest(
        first=first,
        second=second,
        metadata_schedule_sha256=metadata_schedule_sha256,
    )
    run_manifest_sha256 = _sha256_json(run_manifest)
    manifest_path = evidence_dir / "acquisition-run-manifest.json"
    if manifest_path.exists():
        existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        if existing != run_manifest:
            raise ValueError("existing SF-088 acquisition run manifest differs")
    else:
        _write_json_once(manifest_path, run_manifest)

    candles = _load_pass_candles(output_dir=evidence_dir, acquisition_pass=first)
    missing_evidence = _missing_minute_evidence(candles)
    missing_evidence_payload: dict[str, object] = {
        "classification_contract": "sf088-missing-minute-v1",
        "missing_intervals": missing_evidence,
    }
    missing_evidence_sha256 = _sha256_json(missing_evidence_payload)
    missing_evidence_path = evidence_dir / "missing-minute-evidence.json"
    if missing_evidence_path.exists():
        existing = json.loads(missing_evidence_path.read_text(encoding="utf-8"))
        if existing != missing_evidence_payload:
            raise ValueError("existing SF-088 missing-minute evidence differs")
    else:
        _write_json_once(missing_evidence_path, missing_evidence_payload)

    dataset = canonicalize_delta_one_minute(
        candles=candles,
        product=first.product,
        instrument_id=SF088_INSTRUMENT_ID,
        requested_start=SF088_START,
        requested_end=SF088_END,
        acquired_at=max(item.acquired_at for item in first.chunks),
        timestamp_contract=_TIMESTAMP_CONTRACT,
        acquisition_version=SF088_ACQUISITION_VERSION,
        canonicalisation_version=SF088_CANONICALISATION_VERSION,
    )
    dataset = replace(
        dataset,
        manifest=replace(
            dataset.manifest,
            limitations=dataset.manifest.limitations
            + (f"source_metadata_schedule_sha256={metadata_schedule_sha256}",),
            acquisition_evidence=dataset.manifest.acquisition_evidence
            + (
                f"source_acquisition_run_manifest_sha256={run_manifest_sha256}",
                f"source_missing_minute_evidence_sha256={missing_evidence_sha256}",
            ),
        ),
    )

    duplicate_count = dataset.manifest.duplicate_observation_count
    missing_count = dataset.manifest.missing_interval_count
    disposition = (
        DeltaResearchDisposition.PENDING_OFFLINE_VERIFICATION
        if duplicate_count == 0 and missing_count == 0
        else DeltaResearchDisposition.PARTIAL
    )

    store = LocalHistoricalDatasetStore(store_dir)
    dataset_id = store.save(dataset)
    restored = LocalHistoricalDatasetStore(store_dir).load(dataset_id)
    if restored != dataset or restored.dataset_id != dataset_id:
        raise ValueError("SF-088 offline dataset round-trip differs")
    derived = aggregate_one_minute_to_five_minute(restored)

    storage_path = store_dir / str(dataset_id)
    if storage_path.is_dir():
        manifest_size = (storage_path / "manifest.json").stat().st_size
        parquet_size = (storage_path / "bars.parquet").stat().st_size
        total_size = sum(
            item.stat().st_size for item in storage_path.iterdir() if item.is_file()
        )
        representation = "historical-bars-parquet-v1"
    else:
        legacy_path = store_dir / f"{dataset_id}.json"
        manifest_size = 0
        parquet_size = 0
        total_size = legacy_path.stat().st_size
        representation = "legacy-json"

    report: dict[str, object] = {
        "disposition": disposition.value,
        "dataset_id": str(dataset_id),
        "instrument_id": str(SF088_INSTRUMENT_ID),
        "start": SF088_START.isoformat(),
        "end": SF088_END.isoformat(),
        "expected_minutes": SF088_EXPECTED_MINUTES,
        "canonical_rows": dataset.manifest.canonical_row_count,
        "missing_minutes": missing_count,
        "duplicate_observations": duplicate_count,
        "metadata_schedule_sha256": metadata_schedule_sha256,
        "acquisition_run_manifest_sha256": run_manifest_sha256,
        "missing_minute_evidence_sha256": missing_evidence_sha256,
        "missing_minute_evidence_count": len(missing_evidence),
        "storage_representation": representation,
        "manifest_size_bytes": manifest_size,
        "parquet_size_bytes": parquet_size,
        "total_stored_size_bytes": total_size,
        "derived_five_minute_candles": len(derived),
        "same_process_round_trip_pass": True,
        "offline_verification_required": True,
    }
    report_path = evidence_dir / "sf088-finalization-report.json"
    if report_path.exists():
        existing = json.loads(report_path.read_text(encoding="utf-8"))
        if existing != report:
            raise ValueError("existing SF-088 final report differs")
    else:
        _write_json_once(report_path, report)
    return report


def verify_sf088_offline(
    *,
    evidence_dir: Path,
    store_dir: Path,
    dataset_id: DatasetId,
) -> dict[str, object]:
    """Verify frozen local content and emit the only evidence that can promote READY."""

    finalization_path = evidence_dir / "sf088-finalization-report.json"
    if not finalization_path.is_file():
        raise ValueError("SF-088 finalization report is required before offline verification")
    finalization = json.loads(finalization_path.read_text(encoding="utf-8"))
    if not isinstance(finalization, dict):
        raise ValueError("SF-088 finalization report must be an object")
    if finalization.get("dataset_id") != str(dataset_id):
        raise ValueError("SF-088 offline dataset ID contradicts finalization evidence")

    dataset = LocalHistoricalDatasetStore(store_dir).load(dataset_id)
    derived = aggregate_one_minute_to_five_minute(dataset)
    content_manifest_sha256 = _storage_content_manifest_sha256(
        store_dir=store_dir,
        dataset_id=dataset_id,
    )
    verification: dict[str, object] = {
        "verification_contract": "sf088-offline-verification-v1",
        "dataset_id": str(dataset.dataset_id),
        "storage_content_manifest_sha256": content_manifest_sha256,
        "canonical_rows": dataset.manifest.canonical_row_count,
        "missing_minutes": dataset.manifest.missing_interval_count,
        "derived_five_minute_candles": len(derived),
        "offline_reload_pass": True,
        "provider_access_performed": False,
    }
    verification_path = evidence_dir / "sf088-offline-verification.json"
    if verification_path.exists():
        existing = json.loads(verification_path.read_text(encoding="utf-8"))
        if existing != verification:
            raise ValueError("existing SF-088 offline verification evidence differs")
    else:
        _write_json_once(verification_path, verification)

    preliminary = str(finalization.get("disposition"))
    if (
        preliminary == DeltaResearchDisposition.PENDING_OFFLINE_VERIFICATION.value
        and dataset.manifest.missing_interval_count == 0
        and dataset.manifest.duplicate_observation_count == 0
    ):
        disposition = DeltaResearchDisposition.READY
    elif preliminary == DeltaResearchDisposition.PARTIAL.value:
        disposition = DeltaResearchDisposition.PARTIAL
    else:
        raise ValueError("SF-088 finalization disposition cannot be promoted offline")

    final_report: dict[str, object] = dict(finalization)
    final_report.update(
        {
            "disposition": disposition.value,
            "offline_verification_required": False,
            "offline_verification_sha256": _sha256_json(verification),
            "storage_content_manifest_sha256": content_manifest_sha256,
        }
    )
    final_report_path = evidence_dir / "sf088-final-report.json"
    if final_report_path.exists():
        existing = json.loads(final_report_path.read_text(encoding="utf-8"))
        if existing != final_report:
            raise ValueError("existing SF-088 final report differs")
    else:
        _write_json_once(final_report_path, final_report)
    return final_report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m signalforge.research.delta_historical_dataset_acquisition",
        description="Acquire/finalize or offline-verify SF-088 Delta BTCUSD evidence.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    evidence = subparsers.add_parser("evidence-only")
    evidence.add_argument("--evidence-dir", type=Path, required=True)

    acquire = subparsers.add_parser("acquire")
    acquire.add_argument("--evidence-dir", type=Path, required=True)
    acquire.add_argument("--store-dir", type=Path, required=True)

    verify = subparsers.add_parser("verify-offline")
    verify.add_argument("--evidence-dir", type=Path, required=True)
    verify.add_argument("--store-dir", type=Path, required=True)
    verify.add_argument("--dataset-id", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the explicit SF-088 acquisition or offline verification command."""

    args = _parser().parse_args(argv)
    if args.command == "verify-offline":
        report = verify_sf088_offline(
            evidence_dir=args.evidence_dir,
            store_dir=args.store_dir,
            dataset_id=DatasetId(args.dataset_id),
        )
        print(json.dumps(report, sort_keys=True, separators=(",", ":")))
        return 0

    if args.command == "evidence-only":
        report = acquire_sf088_evidence_only(evidence_dir=args.evidence_dir)
        print(json.dumps(report, sort_keys=True, separators=(",", ":")))
        return 0

    plan = build_sf088_chunk_plan()
    if sum(item.expected_minutes for item in plan) != SF088_EXPECTED_MINUTES:
        raise ValueError("SF-088 deterministic chunk plan does not cover expected horizon")
    first = acquire_sf088_pass(
        output_dir=args.evidence_dir,
        pass_name="pass-1",
        chunk_plan=plan,
    )
    second = acquire_sf088_pass(
        output_dir=args.evidence_dir,
        pass_name="pass-2",
        chunk_plan=plan,
    )
    report = finalize_sf088_dataset(
        evidence_dir=args.evidence_dir,
        store_dir=args.store_dir,
        first=first,
        second=second,
    )
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
