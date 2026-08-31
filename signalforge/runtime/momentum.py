"""Isolated Strategy V1 momentum evaluation."""

from __future__ import annotations

from signalforge.config.strategy_v1 import StrategyV1EvaluationConfig
from signalforge.domain.indicators import IndicatorSnapshot
from signalforge.domain.strategy import MomentumResult


def evaluate_momentum(
    snapshot: IndicatorSnapshot,
    config: StrategyV1EvaluationConfig,
) -> MomentumResult:
    """Evaluate the accepted RSI/ADX momentum rule with diagnostic MACD metadata."""

    _require_supported_periods(config)

    rsi_passed = (
        snapshot.rsi14 is not None
        and config.rsi_min <= snapshot.rsi14 <= config.rsi_max
    )
    adx_passed = (
        snapshot.adx14 is not None
        and snapshot.adx14 > config.adx_threshold
    )

    macd_signal_positive: bool | None
    if snapshot.macd_signal is None:
        macd_signal_positive = None
    else:
        macd_signal_positive = snapshot.macd_signal > 0

    return MomentumResult(
        passed=rsi_passed and adx_passed,
        rsi_passed=rsi_passed,
        adx_passed=adx_passed,
        macd_signal_positive=macd_signal_positive,
    )


def _require_supported_periods(config: StrategyV1EvaluationConfig) -> None:
    if config.rsi_period != 14:
        raise ValueError("IndicatorSnapshot exposes only RSI(14)")
    if config.adx_period != 14:
        raise ValueError("IndicatorSnapshot exposes only ADX(14)")
    if (
        config.macd_fast_period,
        config.macd_slow_period,
        config.macd_signal_period,
    ) != (12, 26, 9):
        raise ValueError("IndicatorSnapshot exposes only MACD(12,26,9)")
