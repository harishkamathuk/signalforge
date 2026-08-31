"""Strategy V1 trend evaluation over canonical indicator snapshots."""

from signalforge.config.strategy_v1 import StrategyV1EvaluationConfig
from signalforge.domain.indicators import IndicatorSnapshot
from signalforge.domain.strategy import TrendResult


def evaluate_trend(
    snapshot: IndicatorSnapshot,
    config: StrategyV1EvaluationConfig,
) -> TrendResult:
    """Evaluate the accepted Strategy V1 trend rule deterministically."""

    if config.trend_fast_ema_period != 20 or config.trend_slow_ema_period != 50:
        raise ValueError(
            "IndicatorSnapshot supports Strategy V1 trend evaluation only for EMA20/EMA50"
        )

    if snapshot.ema20 is None or snapshot.ema50 is None:
        return TrendResult(passed=False)

    return TrendResult(passed=snapshot.ema20 > snapshot.ema50)
