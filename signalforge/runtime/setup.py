"""Strategy V1 setup evaluation."""

from signalforge.config.strategy_v1 import StrategyV1EvaluationConfig
from signalforge.domain.indicators import IndicatorSnapshot
from signalforge.domain.market import CompletedCandle
from signalforge.domain.strategy import SetupResult


def evaluate_setup(
    candle: CompletedCandle,
    snapshot: IndicatorSnapshot,
    config: StrategyV1EvaluationConfig,
) -> SetupResult:
    """Evaluate the accepted strict signal-candle close > EMA9 setup rule."""

    if config.setup_ema_period != 9:
        raise ValueError("IndicatorSnapshot exposes only EMA9 for Strategy V1 setup evaluation")
    if candle.instrument_id != snapshot.instrument_id:
        raise ValueError("Candle and IndicatorSnapshot instrument identities must match")
    if candle.interval != snapshot.interval:
        raise ValueError("Candle and IndicatorSnapshot intervals must match")

    if candle.close is None or snapshot.ema9 is None:
        return SetupResult(passed=False)

    return SetupResult(passed=candle.close.value > snapshot.ema9)
