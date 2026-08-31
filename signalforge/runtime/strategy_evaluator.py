"""Composite Strategy V1 evaluator over canonical candle and indicator facts."""

from __future__ import annotations

from dataclasses import dataclass

from signalforge.config.strategy_v1 import StrategyV1EvaluationConfig
from signalforge.domain.indicators import IndicatorSnapshot
from signalforge.domain.market import CompletedCandle
from signalforge.domain.strategy import DecisionReason, StrategyEvaluation
from signalforge.runtime.eligibility import (
    EvaluationGuardResult,
    MarketDataFeedState,
    evaluate_guard,
)
from signalforge.runtime.indicators import IndicatorContinuity
from signalforge.runtime.momentum import evaluate_momentum
from signalforge.runtime.setup import evaluate_setup
from signalforge.runtime.trend import evaluate_trend


@dataclass(frozen=True, slots=True)
class StrategyEvaluationContext:
    """Non-qualification context required to decide evaluation actionability."""

    completed_regular_session_candles: int
    continuity: IndicatorContinuity
    feed_state: MarketDataFeedState | None = None


@dataclass(frozen=True, slots=True)
class StrategyEvaluatorResult:
    """Canonical strategy decision plus its explicit eligibility/actionability guard result."""

    evaluation: StrategyEvaluation
    guard: EvaluationGuardResult

    def __post_init__(self) -> None:
        expected_actionable = self.evaluation.qualified and self.guard.actionable
        if self.evaluation.actionable != expected_actionable:
            raise ValueError(
                "StrategyEvaluation actionability must equal qualified AND guard actionable"
            )


class StrategyEvaluator:
    """Broker-independent Strategy V1 evaluator."""

    def __init__(self, config: StrategyV1EvaluationConfig) -> None:
        self.config = config

    def evaluate(
        self,
        candle: CompletedCandle,
        snapshot: IndicatorSnapshot,
        context: StrategyEvaluationContext,
    ) -> StrategyEvaluatorResult:
        """Compose guard, trend, momentum, and setup into one immutable decision."""

        guard = evaluate_guard(
            candle,
            snapshot,
            self.config,
            completed_regular_session_candles=context.completed_regular_session_candles,
            continuity=context.continuity,
            feed_state=context.feed_state,
        )
        trend = evaluate_trend(snapshot, self.config)
        momentum = evaluate_momentum(snapshot, self.config)
        setup = evaluate_setup(candle, snapshot, self.config)
        qualified = trend.passed and momentum.passed and setup.passed
        evaluation = StrategyEvaluation(
            instrument_id=candle.instrument_id,
            interval=candle.interval,
            trend=trend,
            momentum=momentum,
            setup=setup,
            qualified=qualified,
            actionable=qualified and guard.actionable,
            reasons=_decision_reasons(
                trend.passed,
                momentum.passed,
                setup.passed,
                guard.actionable,
            ),
        )
        return StrategyEvaluatorResult(evaluation=evaluation, guard=guard)


def _decision_reasons(
    trend_passed: bool,
    momentum_passed: bool,
    setup_passed: bool,
    guard_actionable: bool,
) -> tuple[DecisionReason, ...]:
    """Return the existing domain reason ordering for the composed decision."""

    qualified = trend_passed and momentum_passed and setup_passed
    if qualified:
        if guard_actionable:
            return (DecisionReason.QUALIFIED, DecisionReason.ACTIONABLE)
        return (DecisionReason.QUALIFIED, DecisionReason.QUALIFIED_NOT_ACTIONABLE)

    reasons: list[DecisionReason] = []
    if not trend_passed:
        reasons.append(DecisionReason.TREND_NOT_MET)
    if not momentum_passed:
        reasons.append(DecisionReason.MOMENTUM_NOT_MET)
    if not setup_passed:
        reasons.append(DecisionReason.SETUP_NOT_MET)
    return tuple(reasons)
