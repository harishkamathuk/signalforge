"""Authoritative executable SF-079 Phase A qualification state."""

from __future__ import annotations

from datetime import UTC, datetime

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
_DATA001_OBSERVED_AT = datetime(
    2026, 10, 11, 0, 0, tzinfo=UTC
)

_DATA002_REF = "github-issue:#188"
_DATA002_SNAPSHOT = "github-issue-188@2026-10-11T20:29:38Z"
_DATA002_OBSERVED_AT = datetime(
    2026, 10, 11, 20, 29, 38, tzinfo=UTC
)

_SF081_REF = "https://github.com/harishkamathuk/signalforge/issues/203"
_SF081_SNAPSHOT = (
    "git-fork:3c642ed08b895e72319e02adc12cd78991c34800;"
    "git-main:758dd560faa97d60c02744b9965f85809bb5b33b"
)
_SF081_OBSERVED_AT = datetime(2026, 10, 14, 0, 0, tzinfo=UTC)

_PENDING_REF = "pending:signalforge-nsemine-local-validation"
_PENDING_SNAPSHOT = "pending:no-immutable-probe-artifact-yet"
_PENDING_OBSERVED_AT = datetime(
    2026, 10, 13, 0, 0, tzinfo=UTC
)


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
                "DATA-001 found the tested path did not preserve trustworthy "
                "requested instrument identity."
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
    QualificationCriterion.IMPLEMENTATION_IDENTITY: QualificationStatus.PROVEN,
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
    if criterion is QualificationCriterion.TIMESTAMP_SEMANTICS:
        return _evidence(
            criterion,
            status,
            (
                "SF-081 bounded RELIANCE 2026-10-12 09:15-10:15 IST sample "
                "(60x1m, 12x5m) and host-TZ parity support observed chart "
                "wall-clock-shaped milliseconds, 1m/5m opening labels and "
                "canonical UTC mapping. Fork PRs #3/#4 and main PR #206 "
                "merged. Generalized NSE endpoint contract, range behaviour "
                "and provider-wide source qualification remain unproven."
            ),
            reference=_SF081_REF,
            snapshot_id=_SF081_SNAPSHOT,
            observed_at=_SF081_OBSERVED_AT,
        )
    if criterion in {
        QualificationCriterion.AUTHENTICATION_BOUNDARY,
        QualificationCriterion.TRANSPORT_RELIABILITY,
    }:
        return _evidence(
            criterion,
            status,
            (
                "Prior evidence exists, but the repaired local path must be "
                "re-observed before selection."
            ),
            reference=_DATA002_REF,
            snapshot_id=_DATA002_SNAPSHOT,
            observed_at=_DATA002_OBSERVED_AT,
        )
    if criterion is QualificationCriterion.IMPLEMENTATION_IDENTITY:
        return _evidence(
            criterion,
            status,
            "Fork develop timestamp implementation is identified by merged PR #4; "
            "bounded probes support the observed date/window, not broad qualification.",
            reference="https://github.com/harishkamathuk/signalforge-nsemine/commit/"
            "3c642ed08b895e72319e02adc12cd78991c34800",
            snapshot_id="git-commit:3c642ed08b895e72319e02adc12cd78991c34800",
            observed_at=datetime(2026, 10, 14, 13, 59, tzinfo=UTC),
        )
    return _pending(
        criterion,
        "Mandatory evidence remains pending local signalforge-nsemine validation.",
    )


NSEMINE_SIGNALFORGE_CANDIDATE = HistoricalSourceQualification(
    candidate_id="nsemine-signalforge-local",
    source_name="nsemine / signalforge-nsemine",
    library_or_adapter="nsemine-compatible local fork",
    version="upstream-2.2.1-compatible",
    endpoint_family="NSE quote/charting endpoints",
    implementation_source="github:harishkamathuk/signalforge-nsemine",
    implementation_revision="e56ca52b5ed326a52a70a2dc833531005675bfbc",
    decision=QualificationDecision.BLOCKED,
    evidence=tuple(
        _nsemine_evidence(criterion)
        for criterion in QualificationCriterion
    ),
    decision_rationale=(
        "Blocked pending verified historical timestamp semantics and remaining "
        "source qualification evidence."
    ),
    blockers=(
        "SF-081 timestamp convention is proven only for a bounded sample; "
        "provider-wide request/response semantics remain pending",
        "retention and other mandatory source qualification evidence pending",
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
