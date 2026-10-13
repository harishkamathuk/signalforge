"""Typed SF-079 Phase A historical-source qualification contract."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum

from signalforge.config.identity import config_hash
from signalforge.domain.time import require_aware, to_utc


class QualificationDecision(StrEnum):
    """Gate A outcome for one historical acquisition candidate."""

    SELECT = "select"
    REJECT = "reject"
    BLOCKED = "blocked"


class QualificationStatus(StrEnum):
    """Evidence state for one mandatory or informative qualification criterion."""

    PROVEN = "proven"
    FAILED = "failed"
    PENDING = "pending"


class QualificationCriterion(StrEnum):
    """Evidence required before a source may pass SF-079 Gate A."""

    INSTRUMENT_IDENTITY = "instrument_identity"
    TIMESTAMP_SEMANTICS = "timestamp_semantics"
    ONE_MINUTE_CAPABILITY = "one_minute_capability"
    RETENTION_DEPTH = "retention_depth"
    BOUNDED_REPEATABILITY = "bounded_repeatability"
    MISSING_DUPLICATE_BEHAVIOR = "missing_duplicate_behavior"
    CORPORATE_ACTION_POLICY = "corporate_action_policy"
    VOLUME_SEMANTICS = "volume_semantics"
    AUTHENTICATION_BOUNDARY = "authentication_boundary"
    RATE_LIMIT_BOUNDARY = "rate_limit_boundary"
    RAW_REFERENCE_RETENTION = "raw_reference_retention"
    DATA_USE_CONSTRAINTS = "data_use_constraints"
    TRANSPORT_RELIABILITY = "transport_reliability"
    IMPLEMENTATION_IDENTITY = "implementation_identity"


MANDATORY_SELECT_CRITERIA: tuple[QualificationCriterion, ...] = tuple(
    QualificationCriterion
)


@dataclass(frozen=True, slots=True)
class QualificationEvidence:
    """One auditable evidence statement for a source-qualification criterion."""

    criterion: QualificationCriterion
    status: QualificationStatus
    summary: str
    evidence_reference: str
    evidence_snapshot_id: str
    observed_at: datetime

    def __post_init__(self) -> None:
        if not self.summary.strip():
            raise ValueError("Qualification evidence summary must not be empty")
        if not self.evidence_reference.strip():
            raise ValueError("Qualification evidence reference must not be empty")
        if not self.evidence_snapshot_id.strip():
            raise ValueError("Qualification evidence snapshot identity must not be empty")
        require_aware(self.observed_at)
        object.__setattr__(self, "observed_at", to_utc(self.observed_at))

    def semantic_mapping(self) -> dict[str, object]:
        return {
            "criterion": self.criterion.value,
            "status": self.status.value,
            "summary": self.summary,
            "evidence_reference": self.evidence_reference,
            "evidence_snapshot_id": self.evidence_snapshot_id,
            "observed_at": self.observed_at.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class HistoricalSamplePreRegistration:
    """Outcome-blind bounded sample fixed before strategy-result inspection."""

    instrument_id: str
    requested_provider_instrument: str
    first_session_date: date
    last_session_date: date
    rationale: str
    strategy_outcomes_inspected: bool = False

    def __post_init__(self) -> None:
        if not self.instrument_id.strip():
            raise ValueError("Pre-registered instrument_id must not be empty")
        if not self.requested_provider_instrument.strip():
            raise ValueError("Pre-registered provider instrument must not be empty")
        if self.last_session_date < self.first_session_date:
            raise ValueError("Pre-registered sample end must not precede start")
        if not self.rationale.strip():
            raise ValueError("Pre-registration rationale must not be empty")
        if self.strategy_outcomes_inspected:
            raise ValueError(
                "SF-079 sample must be frozen before strategy outcome inspection"
            )

    def semantic_mapping(self) -> dict[str, object]:
        return {
            "instrument_id": self.instrument_id,
            "requested_provider_instrument": self.requested_provider_instrument,
            "first_session_date": self.first_session_date.isoformat(),
            "last_session_date": self.last_session_date.isoformat(),
            "rationale": self.rationale,
            "strategy_outcomes_inspected": self.strategy_outcomes_inspected,
        }


@dataclass(frozen=True, slots=True)
class HistoricalSourceQualification:
    """Deterministic Gate A record for one external historical-data source."""

    candidate_id: str
    source_name: str
    library_or_adapter: str
    version: str
    endpoint_family: str
    implementation_source: str
    implementation_revision: str
    decision: QualificationDecision
    evidence: tuple[QualificationEvidence, ...]
    decision_rationale: str
    sample: HistoricalSamplePreRegistration | None = None
    blockers: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for field_name in (
            "candidate_id",
            "source_name",
            "library_or_adapter",
            "version",
            "endpoint_family",
            "implementation_source",
            "implementation_revision",
            "decision_rationale",
        ):
            if not str(getattr(self, field_name)).strip():
                raise ValueError(f"{field_name} must not be empty")

        by_criterion: dict[QualificationCriterion, QualificationEvidence] = {}
        for item in self.evidence:
            if item.criterion in by_criterion:
                raise ValueError(
                    f"Duplicate qualification criterion: {item.criterion.value}"
                )
            by_criterion[item.criterion] = item

        missing = [
            criterion.value
            for criterion in MANDATORY_SELECT_CRITERIA
            if criterion not in by_criterion
        ]
        if missing:
            raise ValueError(
                "Qualification record is missing criteria: " + ", ".join(missing)
            )

        if self.decision is QualificationDecision.SELECT:
            if self.sample is None:
                raise ValueError("SELECT requires a pre-registered bounded sample")
            non_proven = [
                item.criterion.value
                for item in self.evidence
                if item.criterion in MANDATORY_SELECT_CRITERIA
                and item.status is not QualificationStatus.PROVEN
            ]
            if non_proven:
                raise ValueError(
                    "SELECT requires all mandatory criteria PROVEN: "
                    + ", ".join(non_proven)
                )
            if self.blockers:
                raise ValueError("SELECT cannot retain unresolved blockers")
        elif self.decision is QualificationDecision.REJECT:
            if not any(
                item.status is QualificationStatus.FAILED for item in self.evidence
            ):
                raise ValueError("REJECT requires at least one FAILED criterion")
        elif self.decision is QualificationDecision.BLOCKED:
            if not self.blockers:
                raise ValueError("BLOCKED requires at least one explicit blocker")
            if not any(
                item.status is QualificationStatus.PENDING for item in self.evidence
            ):
                raise ValueError("BLOCKED requires at least one PENDING criterion")

    @property
    def semantic_id(self) -> str:
        """Return deterministic qualification identity."""

        return config_hash(self.semantic_mapping())

    def semantic_mapping(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "source_name": self.source_name,
            "library_or_adapter": self.library_or_adapter,
            "version": self.version,
            "endpoint_family": self.endpoint_family,
            "implementation_source": self.implementation_source,
            "implementation_revision": self.implementation_revision,
            "decision": self.decision.value,
            "evidence": [
                item.semantic_mapping()
                for item in sorted(self.evidence, key=lambda value: value.criterion.value)
            ],
            "decision_rationale": self.decision_rationale,
            "sample": None if self.sample is None else self.sample.semantic_mapping(),
            "blockers": list(self.blockers),
        }


@dataclass(frozen=True, slots=True)
class SourceQualificationReport:
    """Phase A result across all candidates considered at one evidence checkpoint."""

    work_item: str
    candidates: tuple[HistoricalSourceQualification, ...]
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.work_item.strip():
            raise ValueError("Qualification report work_item must not be empty")
        if not self.candidates:
            raise ValueError("Qualification report requires at least one candidate")
        ids = [item.candidate_id for item in self.candidates]
        if len(ids) != len(set(ids)):
            raise ValueError("Qualification report candidate IDs must be unique")
        selected = [
            item
            for item in self.candidates
            if item.decision is QualificationDecision.SELECT
        ]
        if len(selected) > 1:
            raise ValueError("Phase A report may SELECT at most one source")

    @property
    def gate_a_passed(self) -> bool:
        return any(
            item.decision is QualificationDecision.SELECT
            for item in self.candidates
        )

    @property
    def semantic_id(self) -> str:
        return config_hash(self.semantic_mapping())

    def semantic_mapping(self) -> dict[str, object]:
        return {
            "work_item": self.work_item,
            "candidates": [
                item.semantic_mapping()
                for item in sorted(self.candidates, key=lambda value: value.candidate_id)
            ],
            "notes": list(self.notes),
        }
