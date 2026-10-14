from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from signalforge.research.sf079_phase_a_report import (
    CURRENT_SF079_PHASE_A_REPORT,
    NSEMINE_SIGNALFORGE_CANDIDATE,
    NSEPYTHON_2_101,
    OPENCHART_0_2_0,
)
from signalforge.research.source_qualification import (
    HistoricalSamplePreRegistration,
    HistoricalSourceQualification,
    QualificationCriterion,
    QualificationDecision,
    QualificationEvidence,
    QualificationStatus,
    SourceQualificationReport,
)

OBSERVED_AT = datetime(
    2026, 10, 13, 0, 0, tzinfo=UTC
)


def _evidence(
    *,
    default_status: QualificationStatus = QualificationStatus.PROVEN,
    overrides: dict[QualificationCriterion, QualificationStatus] | None = None,
) -> tuple[QualificationEvidence, ...]:
    overrides = overrides or {}
    return tuple(
        QualificationEvidence(
            criterion=criterion,
            status=overrides.get(criterion, default_status),
            summary=f"{criterion.value} evidence",
            evidence_reference=f"docs://{criterion.value}",
            evidence_snapshot_id=f"snapshot:{criterion.value}:v1",
            observed_at=OBSERVED_AT,
        )
        for criterion in QualificationCriterion
    )


def _sample() -> HistoricalSamplePreRegistration:
    return HistoricalSamplePreRegistration(
        instrument_id="NSE:BAJAJ-AUTO",
        requested_provider_instrument="BAJAJ-AUTO-EQ",
        first_session_date=date(2026, 9, 1),
        last_session_date=date(2026, 9, 30),
        rationale="Coverage-led qualification sample; no strategy outcomes inspected.",
    )


def _candidate(
    *,
    candidate_id: str,
    decision: QualificationDecision,
    evidence: tuple[QualificationEvidence, ...],
    sample: HistoricalSamplePreRegistration | None = None,
    blockers: tuple[str, ...] = (),
) -> HistoricalSourceQualification:
    return HistoricalSourceQualification(
        candidate_id=candidate_id,
        source_name=candidate_id,
        library_or_adapter="adapter",
        version="1.0",
        endpoint_family="history",
        implementation_source="repo:example/source",
        implementation_revision="commit:abc123",
        decision=decision,
        evidence=evidence,
        decision_rationale=f"{decision.value} rationale",
        sample=sample,
        blockers=blockers,
    )


def test_select_requires_all_mandatory_evidence_and_frozen_sample() -> None:
    selected = _candidate(
        candidate_id="candidate-a",
        decision=QualificationDecision.SELECT,
        evidence=_evidence(),
        sample=_sample(),
    )

    assert selected.sample is not None
    assert selected.semantic_id == selected.semantic_id

    with pytest.raises(ValueError, match="pre-registered bounded sample"):
        _candidate(
            candidate_id="candidate-a",
            decision=QualificationDecision.SELECT,
            evidence=_evidence(),
        )

    with pytest.raises(ValueError, match="all mandatory criteria PROVEN"):
        _candidate(
            candidate_id="candidate-a",
            decision=QualificationDecision.SELECT,
            evidence=_evidence(
                overrides={
                    QualificationCriterion.TRANSPORT_RELIABILITY:
                        QualificationStatus.PENDING
                }
            ),
            sample=_sample(),
        )


def test_blocked_requires_explicit_pending_evidence_and_blocker() -> None:
    blocked = _candidate(
        candidate_id="candidate-a",
        decision=QualificationDecision.BLOCKED,
        evidence=_evidence(
            overrides={
                QualificationCriterion.RETENTION_DEPTH: QualificationStatus.PENDING,
                QualificationCriterion.TRANSPORT_RELIABILITY:
                    QualificationStatus.PENDING,
            }
        ),
        blockers=("local validation pending",),
    )

    assert blocked.sample is None

    with pytest.raises(ValueError, match="explicit blocker"):
        _candidate(
            candidate_id="candidate-a",
            decision=QualificationDecision.BLOCKED,
            evidence=blocked.evidence,
        )


def test_reject_requires_failed_evidence() -> None:
    rejected = _candidate(
        candidate_id="daily-only",
        decision=QualificationDecision.REJECT,
        evidence=_evidence(
            overrides={
                QualificationCriterion.ONE_MINUTE_CAPABILITY:
                    QualificationStatus.FAILED
            }
        ),
    )
    assert rejected.decision is QualificationDecision.REJECT

    with pytest.raises(ValueError, match="FAILED criterion"):
        _candidate(
            candidate_id="invalid-reject",
            decision=QualificationDecision.REJECT,
            evidence=_evidence(),
        )


def test_pre_registration_rejects_post_outcome_selection() -> None:
    with pytest.raises(ValueError, match="before strategy outcome inspection"):
        HistoricalSamplePreRegistration(
            instrument_id="NSE:BAJAJ-AUTO",
            requested_provider_instrument="BAJAJ-AUTO-EQ",
            first_session_date=date(2026, 9, 1),
            last_session_date=date(2026, 9, 30),
            rationale="Invalid post-hoc sample.",
            strategy_outcomes_inspected=True,
        )


def test_report_allows_blocked_phase_a_and_at_most_one_selected_source() -> None:
    blocked = _candidate(
        candidate_id="blocked",
        decision=QualificationDecision.BLOCKED,
        evidence=_evidence(
            overrides={
                QualificationCriterion.TRANSPORT_RELIABILITY:
                    QualificationStatus.PENDING
            }
        ),
        blockers=("local validation pending",),
    )
    report = SourceQualificationReport("SF-079", (blocked,))
    assert report.gate_a_passed is False

    first = _candidate(
        candidate_id="a",
        decision=QualificationDecision.SELECT,
        evidence=_evidence(),
        sample=_sample(),
    )
    second = _candidate(
        candidate_id="b",
        decision=QualificationDecision.SELECT,
        evidence=_evidence(),
        sample=_sample(),
    )
    with pytest.raises(ValueError, match="at most one"):
        SourceQualificationReport("SF-079", (first, second))


def test_semantic_identity_includes_implementation_and_evidence_snapshot() -> None:
    first = _candidate(
        candidate_id="candidate-a",
        decision=QualificationDecision.SELECT,
        evidence=_evidence(),
        sample=_sample(),
    )
    changed_revision = HistoricalSourceQualification(
        candidate_id=first.candidate_id,
        source_name=first.source_name,
        library_or_adapter=first.library_or_adapter,
        version=first.version,
        endpoint_family=first.endpoint_family,
        implementation_source=first.implementation_source,
        implementation_revision="commit:def456",
        decision=first.decision,
        evidence=first.evidence,
        decision_rationale=first.decision_rationale,
        sample=first.sample,
    )
    changed_snapshot_evidence = list(first.evidence)
    item = changed_snapshot_evidence[0]
    changed_snapshot_evidence[0] = QualificationEvidence(
        criterion=item.criterion,
        status=item.status,
        summary=item.summary,
        evidence_reference=item.evidence_reference,
        evidence_snapshot_id="snapshot:changed",
        observed_at=item.observed_at,
    )
    changed_snapshot = HistoricalSourceQualification(
        candidate_id=first.candidate_id,
        source_name=first.source_name,
        library_or_adapter=first.library_or_adapter,
        version=first.version,
        endpoint_family=first.endpoint_family,
        implementation_source=first.implementation_source,
        implementation_revision=first.implementation_revision,
        decision=first.decision,
        evidence=tuple(changed_snapshot_evidence),
        decision_rationale=first.decision_rationale,
        sample=first.sample,
    )

    assert first.semantic_id != changed_revision.semantic_id
    assert first.semantic_id != changed_snapshot.semantic_id


def test_observed_at_is_aware_and_identity_material() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        QualificationEvidence(
            criterion=QualificationCriterion.TRANSPORT_RELIABILITY,
            status=QualificationStatus.PROVEN,
            summary="evidence",
            evidence_reference="docs://transport",
            evidence_snapshot_id="snapshot:v1",
            observed_at=datetime(2026, 10, 13),
        )

    first = _evidence()[0]
    later = QualificationEvidence(
        criterion=first.criterion,
        status=first.status,
        summary=first.summary,
        evidence_reference=first.evidence_reference,
        evidence_snapshot_id=first.evidence_snapshot_id,
        observed_at=datetime(2026, 10, 14, tzinfo=UTC),
    )
    candidate_first = _candidate(
        candidate_id="candidate-a",
        decision=QualificationDecision.SELECT,
        evidence=(first, *_evidence()[1:]),
        sample=_sample(),
    )
    candidate_later = _candidate(
        candidate_id="candidate-a",
        decision=QualificationDecision.SELECT,
        evidence=(later, *_evidence()[1:]),
        sample=_sample(),
    )
    assert candidate_first.semantic_id != candidate_later.semantic_id


def test_current_phase_a_report_is_executable_and_gate_remains_blocked() -> None:
    report = CURRENT_SF079_PHASE_A_REPORT

    assert report.gate_a_passed is False
    assert NSEPYTHON_2_101.decision is QualificationDecision.REJECT
    assert OPENCHART_0_2_0.decision is QualificationDecision.REJECT
    assert NSEMINE_SIGNALFORGE_CANDIDATE.decision is QualificationDecision.BLOCKED

    statuses = {
        item.criterion: item.status
        for item in NSEMINE_SIGNALFORGE_CANDIDATE.evidence
    }
    assert statuses[QualificationCriterion.INSTRUMENT_IDENTITY] is QualificationStatus.PROVEN
    assert statuses[QualificationCriterion.ONE_MINUTE_CAPABILITY] is QualificationStatus.PROVEN
    assert statuses[QualificationCriterion.TIMESTAMP_SEMANTICS] is QualificationStatus.PENDING
    assert statuses[QualificationCriterion.AUTHENTICATION_BOUNDARY] is QualificationStatus.PENDING
    assert (
        statuses[QualificationCriterion.IMPLEMENTATION_IDENTITY]
        is QualificationStatus.PROVEN
    )
    assert NSEMINE_SIGNALFORGE_CANDIDATE.implementation_revision == (
        "e56ca52b5ed326a52a70a2dc833531005675bfbc"
    )


def test_current_fork_identity_is_immutable_without_promoting_other_evidence() -> None:
    candidate = NSEMINE_SIGNALFORGE_CANDIDATE
    assert candidate.implementation_source == "github:harishkamathuk/signalforge-nsemine"
    identity = next(
        item for item in candidate.evidence
        if item.criterion is QualificationCriterion.IMPLEMENTATION_IDENTITY
    )
    assert identity.status is QualificationStatus.PROVEN
    assert identity.evidence_snapshot_id == (
        "git-commit:e56ca52b5ed326a52a70a2dc833531005675bfbc"
    )
    assert candidate.decision is QualificationDecision.BLOCKED
    assert CURRENT_SF079_PHASE_A_REPORT.gate_a_passed is False
    pending = {
        item.criterion for item in candidate.evidence
        if item.status is QualificationStatus.PENDING
    }
    assert QualificationCriterion.TIMESTAMP_SEMANTICS in pending
    assert QualificationCriterion.RETENTION_DEPTH in pending
    assert QualificationCriterion.TRANSPORT_RELIABILITY in pending
