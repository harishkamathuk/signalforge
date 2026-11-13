"""SF-260: separately versioned, source-only audited BTCUSD 91-day derivation.

This is deliberately not a RawDiagnosticSource subtype.  The original frozen
full-year proof remains byte-for-byte unchanged and cannot be applied to a
different dataset.  The private constructor seal prevents routine caller-side
identity relabelling; it is not a sandbox against hostile Python introspection.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta

from signalforge.config.identity import canonical_config_json, config_hash
from signalforge.domain.market import CandleQuality
from signalforge.domain.time import CandleInterval
from signalforge.research.btc_raw_diagnostic_input import (
    FROZEN_PROVISIONAL_REPORT_SHA256,
    RawDiagnosticSource,
)
from signalforge.research.historical_bars import (
    HistoricalBarDataset,
    aggregate_one_minute_to_five_minute,
)
from signalforge.research.historical_grid import HistoricalBarGrid

SOURCE_START = datetime(2025, 10, 30, tzinfo=UTC)
IS_START = datetime(2025, 10, 31, tzinfo=UTC)
OOS_START = datetime(2025, 12, 30, tzinfo=UTC)
MEASURED_END = datetime(2026, 1, 29, tzinfo=UTC)
SOURCE_MINUTES = 131_040
IS_CANDLES = 17_280
OOS_CANDLES = 8_640
PARENT_END = datetime(2026, 10, 30, tzinfo=UTC)
PARENT_DATASET_HASH = "85d89887078504385a5023eaba007ffcdeeb7f4c67689c79cd5db9a407c999f9"
DERIVATION_VERSION = "sf260-audited-source-slice-v1"
_SEAL = object()


def ordered_bar_digest(bars: tuple[object, ...]) -> str:
    """Independent-friendly, streaming digest of ordered canonical 1m mappings."""
    digest = hashlib.sha256()
    digest.update(b"sf260-ordered-one-minute-bars-v1\n")
    for bar in bars:
        mapping = bar.semantic_mapping()
        digest.update(canonical_config_json(mapping).encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def five_minute_close_digest(dataset: HistoricalBarDataset) -> str:
    """Bind all independently aggregated complete five-minute closes."""
    candles = aggregate_one_minute_to_five_minute(dataset)
    if len(candles) != SOURCE_MINUTES // 5 or any(
        candle.quality is not CandleQuality.VALID for candle in candles
    ):
        raise ValueError("audited source slice has incomplete five-minute coverage")
    return config_hash({
        "close": [candle.close.value for candle in candles if candle.close is not None],
    })


@dataclass(frozen=True, slots=True)
class AuditedSourceSliceV1:
    """Private-factory 90D source wrapper; never implies tick quality or fills."""

    dataset: HistoricalBarDataset
    parent_dataset_hash: str
    parent_diagnostic_id: str
    ordered_one_minute_sha256: str
    derived_five_minute_close_digest: str
    derivation_id: str
    _factory_seal: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._factory_seal is not _SEAL:
            raise ValueError("audited source slice must use the verified factory")
        if self.parent_dataset_hash != PARENT_DATASET_HASH or (
            self.parent_diagnostic_id != FROZEN_PROVISIONAL_REPORT_SHA256
        ):
            raise ValueError("audited source slice parent identity mismatch")
        manifest = self.dataset.manifest
        coverage = manifest.effective_grid.coverage
        if (
            len(coverage) != 1 or coverage[0].start != SOURCE_START
            or coverage[0].end != MEASURED_END
            or len(self.dataset.bars) != SOURCE_MINUTES
            or manifest.missing_interval_count != 0
            or "UNQUALIFIED_HISTORICAL_METADATA" not in manifest.limitations
        ):
            raise ValueError("audited source slice bounds/quality mismatch")
        if ordered_bar_digest(self.dataset.bars) != self.ordered_one_minute_sha256:
            raise ValueError("audited source slice one-minute digest mismatch")
        if five_minute_close_digest(self.dataset) != self.derived_five_minute_close_digest:
            raise ValueError("audited source slice five-minute digest mismatch")
        if config_hash(self.lineage_preimage()) != self.derivation_id:
            raise ValueError("audited source slice lineage identity mismatch")

    @property
    def source_diagnostic_id(self) -> str:
        return self.derivation_id

    @property
    def execution_valid(self) -> bool:
        return False

    def lineage_preimage(self) -> dict[str, object]:
        return {
            "domain": DERIVATION_VERSION,
            "parent_dataset_hash": self.parent_dataset_hash,
            "parent_diagnostic_id": self.parent_diagnostic_id,
            "source_start": SOURCE_START.isoformat(),
            "source_end": MEASURED_END.isoformat(),
            "child_dataset_hash": self.dataset.content_hash,
            "child_manifest": self.dataset.manifest.semantic_mapping(),
            "ordered_one_minute_sha256": self.ordered_one_minute_sha256,
            "derived_five_minute_close_digest": self.derived_five_minute_close_digest,
            "historical_metadata_status": "UNQUALIFIED_HISTORICAL_METADATA",
            "execution_valid": False,
        }


def derive_audited_source_slice(parent: RawDiagnosticSource) -> AuditedSourceSliceV1:
    """Derive only from an already authenticated full-year protected source.

    The parent is never stored on the returned slice.  Callers must release the
    parent reference before scenario work; separate cgroup checks must bound the
    entire audit/derivation operation as well as the later worker.
    """
    if type(parent) is not RawDiagnosticSource or parent.execution_valid:
        raise ValueError("expected the original audited RawDiagnosticSource")
    full = parent.dataset
    coverage = full.manifest.effective_grid.coverage
    if (
        parent.source_diagnostic_id != FROZEN_PROVISIONAL_REPORT_SHA256
        or full.content_hash != PARENT_DATASET_HASH
        or len(coverage) != 1
        or coverage[0].start != SOURCE_START or coverage[0].end != PARENT_END
        or len(full.bars) != 525_600
        or full.manifest.missing_interval_count != 0
    ):
        raise ValueError("frozen parent audit/coverage identity mismatch")
    bars = full.bars[:SOURCE_MINUTES]
    if (
        len(bars) != SOURCE_MINUTES
        or bars[0].interval.start != SOURCE_START
        or bars[-1].interval.end != MEASURED_END
        or any(
            bar.interval.start != SOURCE_START + timedelta(minutes=i)
            or bar.interval.end != SOURCE_START + timedelta(minutes=i + 1)
            for i, bar in enumerate(bars)
        )
    ):
        raise ValueError("audited slice is not complete unique chronological UTC minutes")
    grid = HistoricalBarGrid(
        "sf260-approved-90d-source", "1",
        (CandleInterval(SOURCE_START, MEASURED_END),),
    )
    manifest = replace(
        full.manifest,
        requested_start=SOURCE_START, requested_end=MEASURED_END,
        returned_start=SOURCE_START, returned_end=MEASURED_END,
        raw_row_count=SOURCE_MINUTES, canonical_row_count=SOURCE_MINUTES,
        duplicate_observation_count=0, corrupt_rejected_count=0,
        missing_interval_count=0, grid=grid,
    )
    child = HistoricalBarDataset(manifest, bars)
    digest_1m = ordered_bar_digest(child.bars)
    digest_5m = five_minute_close_digest(child)
    preimage = {
        "domain": DERIVATION_VERSION,
        "parent_dataset_hash": full.content_hash,
        "parent_diagnostic_id": parent.source_diagnostic_id,
        "source_start": SOURCE_START.isoformat(),
        "source_end": MEASURED_END.isoformat(),
        "child_dataset_hash": child.content_hash,
        "child_manifest": child.manifest.semantic_mapping(),
        "ordered_one_minute_sha256": digest_1m,
        "derived_five_minute_close_digest": digest_5m,
        "historical_metadata_status": "UNQUALIFIED_HISTORICAL_METADATA",
        "execution_valid": False,
    }
    return AuditedSourceSliceV1(
        child, full.content_hash, parent.source_diagnostic_id,
        digest_1m, digest_5m, config_hash(preimage), _SEAL,
    )
