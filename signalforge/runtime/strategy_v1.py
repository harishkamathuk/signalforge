"""Strategy V1 adapter for the shared completed-candle strategy contract."""

from __future__ import annotations

from signalforge.config.identity import ConfigIdentity
from signalforge.config.strategy_v1 import StrategyV1EvaluationConfig
from signalforge.domain.provenance import StrategyIdentity
from signalforge.runtime.strategy import CompletedCandleStrategyContext, StrategyDecision
from signalforge.runtime.strategy_evaluator import StrategyEvaluationContext, StrategyEvaluator


class IntradayMomentumV1Strategy:
    """Thin adapter preserving accepted intraday_momentum_v1 evaluator behavior."""

    def __init__(self, config: StrategyV1EvaluationConfig) -> None:
        self.config = config
        self._config_identity = config.identify()
        self._evaluator = StrategyEvaluator(config)

    @property
    def identity(self) -> StrategyIdentity:
        return self.config.strategy_identity

    @property
    def config_identity(self) -> ConfigIdentity:
        return self._config_identity

    def evaluate_completed_candle(
        self,
        context: CompletedCandleStrategyContext,
    ) -> StrategyDecision:
        return self._evaluator.evaluate(
            context.candle,
            context.indicators,
            StrategyEvaluationContext(
                completed_regular_session_candles=context.completed_regular_session_candles,
                continuity=context.continuity,
                feed_state=context.feed_state,
            ),
        )
