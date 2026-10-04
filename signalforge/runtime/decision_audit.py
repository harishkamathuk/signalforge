"""Explicit projections from strategy decisions to generic audit facts."""

from signalforge.domain.decision_facts import StrategyDecisionFact
from signalforge.domain.identity import canonical_decimal
from signalforge.domain.provenance import StrategyIdentity
from signalforge.domain.strategy import StrategyEvaluation
from signalforge.runtime.rsi_mean_reversion_v1 import RsiMeanReversionDecision
from signalforge.runtime.strategy_evaluator import StrategyEvaluatorResult

V1_DECISION_KIND = "intraday_momentum_v1.evaluation.v1"
RSI_MEAN_REVERSION_DECISION_KIND = "rsi_mean_reversion_v1.evaluation.v1"


def project_v1_decision(
    evaluation: StrategyEvaluation | StrategyEvaluatorResult,
) -> StrategyDecisionFact:
    """Project accepted Strategy V1 diagnostics from domain or shared-runtime form."""

    if isinstance(evaluation, StrategyEvaluatorResult):
        evaluation = evaluation.evaluation
    return StrategyDecisionFact.create(
        instrument_id=evaluation.instrument_id,
        interval=evaluation.interval,
        strategy=StrategyIdentity("intraday_momentum_v1", "1.0.0"),
        decision_kind=V1_DECISION_KIND,
        qualified=evaluation.qualified,
        actionable=evaluation.actionable,
        reasons=tuple(reason.value for reason in evaluation.reasons),
        diagnostics={
            "adx_passed": evaluation.momentum.adx_passed,
            "macd_signal_positive": evaluation.momentum.macd_signal_positive,
            "momentum_passed": evaluation.momentum.passed,
            "rsi_passed": evaluation.momentum.rsi_passed,
            "setup_passed": evaluation.setup.passed,
            "trend_passed": evaluation.trend.passed,
        },
    )


def project_rsi_mean_reversion_decision(
    decision: RsiMeanReversionDecision,
) -> StrategyDecisionFact:
    """Project reference-strategy RSI diagnostics without V1-shaped fields."""

    return StrategyDecisionFact.create(
        instrument_id=decision.instrument_id,
        interval=decision.interval,
        strategy=StrategyIdentity("rsi_mean_reversion_v1", "1.0.0"),
        decision_kind=RSI_MEAN_REVERSION_DECISION_KIND,
        qualified=decision.qualified,
        actionable=decision.actionable,
        reasons=decision.reasons,
        diagnostics={
            "rsi14": None if decision.rsi14 is None else canonical_decimal(decision.rsi14),
            "rsi_ready": decision.rsi14 is not None,
        },
    )
