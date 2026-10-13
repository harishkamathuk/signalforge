"""Authoritative executable SF-079 Phase A qualification state."""

from __future__ import annotations

from datetime import datetime, timezone

from signalforge.research.source_qualification import (
    HistoricalSourceQualification,
    QualificationCriterion,
    QualificationDecision,
    QualificationEvidence,
    QualificationStatus,
    SourceQualificationReport,
)

_DATA001_REF = (
    "docs/validation/sf-075-data-001-free-nse-historical-data.md"
)
_DATA001_SNAPSHOT = "git-blob:90562cb0bfdb7e73ff9e9e831e92e38e38d3a034"
_DATA001_OBSERVED_AT = datetime(2026, 10, 11, 0, 0, tzinfo=timezone.utc)

_DATA002_REF = "github-issue:#188"
_DATA002_SNAPSHOT = "github-issue-188@2026-10-11T20:29:38Z"
_DATA002_OBSERVED_AT = datetime(2026, 10, 11, 20, 29, 38, tzinfo=timezone.utc)

_PENDING_REF = "pending:SignalForge-nsemine-local-validation"
_PENDING_SNAPSHOT = "pending:no-immutable-probe-artifact-yet"
_PENDING_OBSERVED_AT = datetime(2026, 10, 13, 0, 0, tzinfo=timezone.utc)


def _evidence(
    criterion: QualificationCriterion,
    status: QualificationStatus,
    summary: str,
    *,
    reference: str,
    snapshot_id: str,
    observed_at: datetime,
) -> QualificationEvidence:
    return QualificationEvidence(
        criterion=criterion,
        status=status,
        summary=summary,
        evidence_reference=reference,
        evidence_snapshot_id=snapshot_id,
        observed_at=observed_at,
    )


def _pending(criterion: QualificationCriterion, summary: str) -> QualificationEvidence:
    return _evidence(
        criterion,
        QualificationStatus.PENDING,
        summary,
        reference=_PENDING_REF,
        snapshot_id=_PENDING_SNAPSHOT,
        observed_at=_PENDING_OBSERVED_AT,
    )


NSEPYTHON_2_101 = HistoricalSourceQualification(
    candidate_id="nsepython-2.101",
    source_name="nsepython",
    library_or_adapter="nsepython",
    version="2.101",
    endpoint_family="NSE historical cash-equity path evaluated in DATA-001",
    implementation_source="pypi:nsepython",
    implementation_revision="2.101",
    decision=QualificationDecision.REJECT,
    evidence=tuple(
        _evidence(
            criterion,
            (
                QualificationStatus.FAILED
                if criterion is QualificationCriterion.ONE_MINUTE_CAPABILITY
                else QualificationStatus.PENDING
            ),
            (
                "DATA-001 found the tested cash-equity path daily/EOD only."
                if criterion is QualificationCriterion.ONE_MINUTE_CAPABILITY
                else "Not required to complete after decisive one-minute capability failure."
            ),
            reference=_DATA001_REF,
            snapshot_id=_DATA001_SNAPSHOT,
            observed_at=_DATA001_OBSERVED_AT,
        )
        for criterion in QualificationCriterion
    ),
    decision_rationale=(
        "Rejected because the tested path does not provide required one-minute intraday data."
    ),
)

OPENCHART_0_2_0 = HistoricalSourceQualification(
    candidate_id="openchart-0.2.0",
    source_name="OpenChart",
    library_or_adapter="openchart",
    version="0.2.0",
    endpoint_family="OpenChart historical path evaluated in DATA-001",
    implementation_source="pypi:openchart",
    implementation_revision="0.2.0",
    decision=QualificationDecision.REJECT,
    evidence=tuple(
        _evidence(
            criterion,
            (
                QualificationStatus.FAILED
                if criterion is QualificationCriterion.INSTRUMENT_IDENTITY
                else QualificationStatus.PENDING
            ),
            (
                "DATA-001 found the tested path did not preserve trustworthy requested instrument identity."
                if criterion is QualificationCriterion.INSTRUMENT_IDENTITY
                else "Not required to complete after decisive identity failure."
            ),
            reference=_DATA001_REF,
            snapshot_id=_DATA001_SNAPSHOT,
            observed_at=_DATA001_OBSERVED_AT,
        )
        for criterion in QualificationCriterion
    ),
    decision_rationale=(
        "Rejected because the tested path did not preserve trustworthy instrument identity."
    ),
)

_NSEMINE_STATUS: dict[QualificationCriterion, QualificationStatus] = {
    QualificationCriterion.INSTRUMENT_IDENTITY: QualificationStatus.PROVEN,
    QualificationCriterion.TIMESTAMP_SEMANTICS: QualificationStatus.PENDING,
    QualificationCriterion.ONE_MINUTE_CAPABILITY: QualificationStatus.PROVEN,
    QualificationCriterion.RETENTION_DEPTH: QualificationStatus.PENDING,
    QualificationCriterion.BOUNDED_REPEATABILITY: QualificationStatus.PENDING,
    QualificationCriterion.MISSING_DUPLICATE_BEHAVIOR: QualificationStatus.PENDING,
    QualificationCriterion.CORPORATE_ACTION_POLICY: QualificationStatus.PENDING,
    QualificationCriterion.VOLUME_SEMANTICS: QualificationStatus.PENDING,
    QualificationCriterion.AUTHENTICATION_BOUNDARY: QualificationStatus.PENDING,
    QualificationCriterion.RATE_LIMIT_BOUNDARY: QualificationStatus.PENDING,
    QualificationCriterion.RAW_REFERENCE_RETENTION: QualificationStatus.PENDING,
    QualificationCriterion.DATA_USE_CONSTRAINTS: QualificationStatus.PENDING,
    QualificationCriterion.TRANSPORT_RELIABILITY: QualificationStatus.PENDING,
    QualificationCriterion.IMPLEMENTATION_IDENTITY: QualificationStatus.PENDING,
}


def _nsemine_evidence(criterion: QualificationCriterion) -> QualificationEvidence:
    status = _NSEMINE_STATUS[criterion]
    if criterion is QualificationCriterion.INSTRUMENT_IDENTITY:
        return _evidence(
            criterion,
            status,
            "DATA-001 captured exact BAJAJ-AUTO equity identity.",
            reference=_DATA001_REF,
            snapshot_id=_DATA001_SNAPSHOT,
            observed_at=_DATA001_OBSERVED_AT,
        )
    if criterion is QualificationCriterion.ONE_MINUTE_CAPABILITY:
        return _evidence(
            criterion,
            status,
            "DATA-001 successfully retrieved one-minute historical OHLCV.",
            reference=_DATA001_REF,
            snapshot_id=_DATA001_SNAPSHOT,
            observed_at=_DATA001_OBSERVED_AT,
        )
    if criterion in {
        QualificationCriterion.TIMESTAMP_SEMANTICS,
        QualificationCriterion.AUTHENTICATION_BOUNDARY,
        QualificationCriterion.TRANSPORT_RELIABILITY,
    }:
        return _evidence(
            criterion,
            status,
            (
                "Prior evidence exists, but the repaired local path must be re-observed before selection."
            ),
            reference=_DATA002_REF,
            snapshot_id=_DATA002_SNAPSHOT,
            observed_at=_DATA002_OBSERVED_AT,
        )
    if criterion is QualificationCriterion.IMPLEMENTATION_IDENTITY:
        return _pending(
            criterion,
            "Exact SignalForge-nsemine repository/commit identity under validation is not yet recorded.",
        )
    return _pending(
        criterion,
        "Mandatory evidence remains pending local SignalForge-nsemine validation.",
    )


NSEMINE_SIGNALFORGE_CANDIDATE = HistoricalSourceQualification(
    candidate_id="nsemine-signalforge-local",
    source_name="nsemine / SignalForge-nsemine",
    library_or_adapter="nsemine-compatible local fork",
    version="upstream-2.2.1-compatible",
    endpoint_family="NSE quote/charting endpoints",
    implementation_source="local:SignalForge-nsemine",
    implementation_revision="PENDING_LOCAL_COMMIT_IDENTITY",
    decision=QualificationDecision.BLOCKED,
    evidence=tuple(
        _nsemine_evidence(criterion)
        for criterion in QualificationCriterion
    ),
    decision_rationale=(
        "Blocked pending immutable local implementation identity and fresh reliability/retention evidence."
    ),
    blockers=(
        "SignalForge-nsemine local implementation commit identity pending",
        "fresh transport/repeatability/retention qualification pending",
    ),
)

CURRENT_SF079_PHASE_A_REPORT = SourceQualificationReport(
    work_item="SF-079",
    candidates=(
        NSEPYTHON_2_101,
        OPENCHART_0_2_0,
        NSEMINE_SIGNALFORGE_CANDIDATE,
    ),
    notes=(
        "Gate A is not passed.",
        "Phase B must not begin until one candidate reaches SELECT.",
    ),
)
