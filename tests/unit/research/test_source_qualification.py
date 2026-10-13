from __future__ import annotations

from datetime import date

import pytest

from signalforge.research.source_qualification import (
    HistoricalSamplePreRegistration,
    HistoricalSourceQualification,
    QualificationCriterion,
    QualificationDecision,
    QualificationEvidence,
    QualificationStatus,
    SourceQualificationReport,
)


def _evidence(
    *,
    default_status: QualificationStatus = QualificationStatus.PROVEN,
    overrides: dict[QualificationCriterion, QualificationStatus] | None = None,
) -> tuple[QualificationEvidence, ...]:
    overrides = overrides or {}
    return tuple(
        QualificationEvidence(
            criterion,
            overrides.get(criterion, default_status),
            f"{criterion.value} evidence",
            f"docs://{criterion.value}",
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


def test_select_requires_all_mandatory_evidence_and_frozen_sample() -> None:
    selected = HistoricalSourceQualification(
        candidate_id="candidate-a",
        source_name="candidate-a",
        library_or_adapter="adapter-a",
        version="1.0",
        endpoint_family="history",
        decision=QualificationDecision.SELECT,
        evidence=_evidence(),
        decision_rationale="All Gate A criteria proven.",
        sample=_sample(),
    )

    assert selected.sample is not None
    assert selected.semantic_id == selected.semantic_id

    with pytest.raises(ValueError, match="pre-registered bounded sample"):
        HistoricalSourceQualification(
            candidate_id="candidate-a",
            source_name="candidate-a",
            library_or_adapter="adapter-a",
            version="1.0",
            endpoint_family="history",
            decision=QualificationDecision.SELECT,
            evidence=_evidence(),
            decision_rationale="Invalid select without sample.",
        )

    with pytest.raises(ValueError, match="all mandatory criteria PROVEN"):
        HistoricalSourceQualification(
            candidate_id="candidate-a",
            source_name="candidate-a",
            library_or_adapter="adapter-a",
            version="1.0",
            endpoint_family="history",
            decision=QualificationDecision.SELECT,
            evidence=_evidence(
                overrides={
                    QualificationCriterion.TRANSPORT_RELIABILITY:
                        QualificationStatus.PENDING
                }
            ),
            decision_rationale="Transport is still pending.",
            sample=_sample(),
        )


def test_blocked_requires_explicit_pending_evidence_and_blocker() -> None:
    blocked = HistoricalSourceQualification(
        candidate_id="nsemine-2.2.1",
        source_name="NSE charting via nsemine",
        library_or_adapter="nsemine",
        version="2.2.1",
        endpoint_family="NSE quote/charting endpoints",
        decision=QualificationDecision.BLOCKED,
        evidence=_evidence(
            overrides={
                QualificationCriterion.RETENTION_DEPTH: QualificationStatus.PENDING,
                QualificationCriterion.BOUNDED_REPEATABILITY:
                    QualificationStatus.PENDING,
                QualificationCriterion.TRANSPORT_RELIABILITY:
                    QualificationStatus.PENDING,
            }
        ),
        decision_rationale="Local transport validation remains incomplete.",
        blockers=("SignalForge-nsemine local transport validation pending",),
    )

    assert blocked.decision is QualificationDecision.BLOCKED
    assert blocked.sample is None

    with pytest.raises(ValueError, match="explicit blocker"):
        HistoricalSourceQualification(
            candidate_id="nsemine-2.2.1",
            source_name="NSE charting via nsemine",
            library_or_adapter="nsemine",
            version="2.2.1",
            endpoint_family="NSE quote/charting endpoints",
            decision=QualificationDecision.BLOCKED,
            evidence=blocked.evidence,
            decision_rationale="Invalid blocked record.",
        )


def test_reject_requires_failed_evidence() -> None:
    rejected = HistoricalSourceQualification(
        candidate_id="daily-only",
        source_name="daily-only",
        library_or_adapter="candidate",
        version="1",
        endpoint_family="history",
        decision=QualificationDecision.REJECT,
        evidence=_evidence(
            overrides={
                QualificationCriterion.ONE_MINUTE_CAPABILITY:
                    QualificationStatus.FAILED
            }
        ),
        decision_rationale="No one-minute capability.",
    )
    assert rejected.decision is QualificationDecision.REJECT

    with pytest.raises(ValueError, match="FAILED criterion"):
        HistoricalSourceQualification(
            candidate_id="invalid-reject",
            source_name="invalid-reject",
            library_or_adapter="candidate",
            version="1",
            endpoint_family="history",
            decision=QualificationDecision.REJECT,
            evidence=_evidence(),
            decision_rationale="No failed criterion.",
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
    blocked = HistoricalSourceQualification(
        candidate_id="nsemine-2.2.1",
        source_name="NSE charting via nsemine",
        library_or_adapter="nsemine",
        version="2.2.1",
        endpoint_family="NSE quote/charting endpoints",
        decision=QualificationDecision.BLOCKED,
        evidence=_evidence(
            overrides={
                QualificationCriterion.TRANSPORT_RELIABILITY:
                    QualificationStatus.PENDING
            }
        ),
        decision_rationale="Transport validation pending.",
        blockers=("local validation pending",),
    )
    report = SourceQualificationReport("SF-079", (blocked,))

    assert report.gate_a_passed is False
    assert report.semantic_id == report.semantic_id

    first = HistoricalSourceQualification(
        candidate_id="a",
        source_name="a",
        library_or_adapter="a",
        version="1",
        endpoint_family="history",
        decision=QualificationDecision.SELECT,
        evidence=_evidence(),
        decision_rationale="selected",
        sample=_sample(),
    )
    second = HistoricalSourceQualification(
        candidate_id="b",
        source_name="b",
        library_or_adapter="b",
        version="1",
        endpoint_family="history",
        decision=QualificationDecision.SELECT,
        evidence=_evidence(),
        decision_rationale="selected",
        sample=_sample(),
    )
    with pytest.raises(ValueError, match="at most one"):
        SourceQualificationReport("SF-079", (first, second))


def test_semantic_identity_is_order_independent_for_candidate_evidence() -> None:
    evidence = _evidence()
    first = HistoricalSourceQualification(
        candidate_id="candidate-a",
        source_name="candidate-a",
        library_or_adapter="adapter",
        version="1",
        endpoint_family="history",
        decision=QualificationDecision.SELECT,
        evidence=evidence,
        decision_rationale="selected",
        sample=_sample(),
    )
    second = HistoricalSourceQualification(
        candidate_id="candidate-a",
        source_name="candidate-a",
        library_or_adapter="adapter",
        version="1",
        endpoint_family="history",
        decision=QualificationDecision.SELECT,
        evidence=tuple(reversed(evidence)),
        decision_rationale="selected",
        sample=_sample(),
    )

    assert first.semantic_id == second.semantic_id
