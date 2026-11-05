"""Read-only, unqualified SF-088 evidence-to-bars bridge for Tier-1 diagnostics.

This module does NOT certify historical tick/contract applicability, publish an
SF-084 dataset, place an order, or evaluate the BTC strategy. Every raw source
observation remains unchanged at Decimal precision.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from signalforge.domain.market import CandleQuality
from signalforge.domain.money import Price
from signalforge.domain.time import CandleInterval
from signalforge.research.delta_historical_dataset_acquisition import (
    SF088_END,
    SF088_EXPECTED_MINUTES,
    SF088_INSTRUMENT_ID,
    SF088_START,
    _candle_semantic_sha256,
    build_sf088_chunk_plan,
)
from signalforge.research.delta_historical_evidence_audit import _load_capture
from signalforge.research.delta_historical_qualification import parse_delta_candles_response
from signalforge.research.delta_provisional_research import explore_generation
from signalforge.research.historical_bars import (
    CorporateActionPolicy,
    HistoricalBar,
    HistoricalBarDataset,
    HistoricalDatasetManifest,
    HistoricalPriceBasis,
)
from signalforge.research.historical_grid import HistoricalBarGrid

# Exact identities in the predeclared SF-094 Tier-1 validation contract.
FROZEN_PROVISIONAL_REPORT_SHA256 = (
    "8632150c1aa75689cb9b3fd933dc3e3d0672ce7eb31c1772b9597d7ce57b7ff6"
)
FROZEN_FIVE_MINUTE_CLOSE_SHA256 = (
    "0787429a8203913b08b954c40d8dc57a0bad0be4b367a7d39580cdaf311733b8"
)


@dataclass(frozen=True, slots=True)
class RawDiagnosticSource:
    """Transient, provenance-bound bars explicitly lacking historical tick evidence."""

    dataset: HistoricalBarDataset
    source_diagnostic_id: str
    execution_valid: bool = False

    def __post_init__(self) -> None:
        if self.execution_valid:
            raise ValueError("Protected raw diagnostic evidence is never execution-valid")
        if not self.source_diagnostic_id.strip():
            raise ValueError("Raw diagnostic requires frozen source identity")
        if "UNQUALIFIED_HISTORICAL_METADATA" not in self.dataset.manifest.limitations:
            raise ValueError("Raw diagnostic must retain unqualified metadata limitation")


def load_sf095_raw_diagnostic_source(generation_dir: Path) -> RawDiagnosticSource:
    """Materialize only the frozen audited SF-088 first pass into transient bars.

    Source files are read-only; no network calls, local output, tick-rounding or
    historical metadata qualification occurs. The frozen independent report and
    five-minute-close digests must agree before observations are exposed.
    """

    root = generation_dir.resolve(strict=True)
    if not any(p.name == ".signalforge-data" for p in (root, *root.parents)):
        raise ValueError("Raw diagnostic source must remain under protected .signalforge-data")
    # This independently audits both passes and every first-pass content digest.
    report = explore_generation(root)
    if (
        report["report_sha256"] != FROZEN_PROVISIONAL_REPORT_SHA256
        or report["derived_price_diagnostics"]["five_minute_close_sha256"]
        != FROZEN_FIVE_MINUTE_CLOSE_SHA256
        or report["historical_metadata_status"] != "UNQUALIFIED_HISTORICAL_METADATA"
        or report["canonical_dataset_published"] is not False
        or report["independent_audit_status"] != "PASS_WITH_UNQUALIFIED_METADATA"
    ):
        raise ValueError("Protected source differs from frozen SF-094 diagnostic identity")
    frozen = json.loads((root / "evidence-only-report.json").read_text(encoding="utf-8"))
    bars: list[HistoricalBar] = []
    acquired_at: datetime | None = None
    for chunk in build_sf088_chunk_plan():
        prefix = root / "pass-1" / f"chunk-{chunk.index:06d}"
        capture, sidecar = _load_capture(
            prefix.with_suffix(".json"), prefix.with_suffix(".meta.json")
        )
        if (
            capture.content_sha256 != frozen["first_pass_raw_sha256"][chunk.index]
            or sidecar["semantic_sha256"]
            != frozen["first_pass_semantic_sha256"][chunk.index]
        ):
            raise ValueError("Raw first-pass evidence changed during diagnostic materialization")
        rows = parse_delta_candles_response(capture)
        if _candle_semantic_sha256(rows) != sidecar["semantic_sha256"]:
            raise ValueError("Raw first-pass semantic digest changed after audit")
        if acquired_at is None:
            acquired_at = capture.acquired_at
        for candle in sorted(rows, key=lambda item: item.time):
            at = datetime.fromtimestamp(candle.time, UTC)
            if candle.volume != candle.volume.to_integral_value():
                raise ValueError("Diagnostic volume is not integral contract quantity")
            bars.append(
                HistoricalBar(
                    instrument_id=SF088_INSTRUMENT_ID,
                    interval=CandleInterval(at, at + timedelta(minutes=1)),
                    open=Price(candle.open),
                    high=Price(candle.high),
                    low=Price(candle.low),
                    close=Price(candle.close),
                    volume=int(candle.volume),
                    quality=CandleQuality.VALID,
                    source_provider="delta_exchange_india",
                    source_record_count=1,
                    provider_timestamp_raw=str(candle.time),
                    provider_timestamp_interpreted=at,
                    canonicalisation_version="sf095-raw-diagnostic-v1",
                )
            )
    if (
        acquired_at is None
        or len(bars) != SF088_EXPECTED_MINUTES
        or bars[0].interval.start != SF088_START
        or bars[-1].interval.end != SF088_END
    ):
        raise ValueError("Raw diagnostic observations do not cover frozen SF-088 interval")
    grid = HistoricalBarGrid(
        "sf095-frozen-continuous-utc", "1",
        (CandleInterval(SF088_START, SF088_END),),
    )
    dataset = HistoricalBarDataset(
        manifest=HistoricalDatasetManifest(
            provider="delta_exchange_india",
            acquisition_adapter="sf095-protected-first-pass-read-only",
            acquisition_version="1",
            requested_instrument="BTCUSD",
            resolved_provider_instrument="BTCUSD#27",
            instrument_id=SF088_INSTRUMENT_ID,
            requested_start=SF088_START,
            requested_end=SF088_END,
            returned_start=SF088_START,
            returned_end=SF088_END,
            interval_minutes=1,
            acquired_at=acquired_at,
            provider_timestamp_representation="unix_seconds",
            timezone_interpretation="UTC",
            canonicalisation_version="sf095-raw-diagnostic-v1",
            expected_session_dates=(),
            raw_row_count=len(bars),
            canonical_row_count=len(bars),
            missing_interval_count=0,
            duplicate_observation_count=0,
            corrupt_rejected_count=0,
            corporate_action_policy=CorporateActionPolicy.NOT_APPLICABLE,
            limitations=(
                "UNQUALIFIED_HISTORICAL_METADATA",
                "RAW_DIAGNOSTIC_ONLY_NOT_EXECUTION_VALID",
                f"frozen_provisional_report_sha256={FROZEN_PROVISIONAL_REPORT_SHA256}",
                f"five_minute_close_sha256={FROZEN_FIVE_MINUTE_CLOSE_SHA256}",
            ),
            grid=grid,
            price_basis=HistoricalPriceBasis.TRADED,
        ),
        bars=tuple(bars),
    )
    return RawDiagnosticSource(
        dataset=dataset, source_diagnostic_id=FROZEN_PROVISIONAL_REPORT_SHA256
    )
