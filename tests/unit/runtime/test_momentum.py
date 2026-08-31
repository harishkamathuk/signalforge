from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from signalforge.config.strategy_v1 import StrategyV1EvaluationConfig
from signalforge.domain.ids import InstrumentId
from signalforge.domain.indicators import IndicatorSnapshot
from signalforge.domain.time import IST, CandleInterval
from signalforge.runtime.momentum import evaluate_momentum


def _snapshot(
    *,
    rsi14: Decimal | None = Decimal("60"),
    adx14: Decimal | None = Decimal("23"),
    macd_signal: Decimal | None = Decimal("1"),
) -> IndicatorSnapshot:
    start = datetime(2026, 8, 31, 10, 0, tzinfo=IST)
    return IndicatorSnapshot(
        instrument_id=InstrumentId("NSE:TEST"),
        interval=CandleInterval(start=start, end=start + timedelta(minutes=5)),
        ready=False,
        calculation_version="test",
        rsi14=rsi14,
        adx14=adx14,
        macd_signal=macd_signal,
    )


def test_rsi_bounds_are_inclusive() -> None:
    config = StrategyV1EvaluationConfig()

    assert evaluate_momentum(_snapshot(rsi14=Decimal("58")), config).passed is True
    assert evaluate_momentum(_snapshot(rsi14=Decimal("65")), config).passed is True


def test_rsi_outside_bounds_fails() -> None:
    config = StrategyV1EvaluationConfig()

    below = evaluate_momentum(_snapshot(rsi14=Decimal("57.999")), config)
    above = evaluate_momentum(_snapshot(rsi14=Decimal("65.001")), config)

    assert below.passed is False
    assert below.rsi_passed is False
    assert above.passed is False
    assert above.rsi_passed is False


def test_adx_threshold_is_strict() -> None:
    config = StrategyV1EvaluationConfig()

    at_threshold = evaluate_momentum(_snapshot(adx14=Decimal("22")), config)
    above_threshold = evaluate_momentum(_snapshot(adx14=Decimal("22.0001")), config)

    assert at_threshold.passed is False
    assert at_threshold.adx_passed is False
    assert above_threshold.passed is True
    assert above_threshold.adx_passed is True


@pytest.mark.parametrize(
    ("macd_signal", "expected"),
    [
        (Decimal("1"), True),
        (Decimal("0"), False),
        (Decimal("-1"), False),
        (None, None),
    ],
)
def test_macd_is_diagnostic_only(
    macd_signal: Decimal | None,
    expected: bool | None,
) -> None:
    result = evaluate_momentum(_snapshot(macd_signal=macd_signal), StrategyV1EvaluationConfig())

    assert result.passed is True
    assert result.macd_signal_positive is expected


def test_unavailable_required_indicators_cannot_pass() -> None:
    config = StrategyV1EvaluationConfig()

    missing_rsi = evaluate_momentum(_snapshot(rsi14=None), config)
    missing_adx = evaluate_momentum(_snapshot(adx14=None), config)

    assert missing_rsi.passed is False
    assert missing_rsi.rsi_passed is False
    assert missing_rsi.adx_passed is True
    assert missing_adx.passed is False
    assert missing_adx.rsi_passed is True
    assert missing_adx.adx_passed is False


def test_overall_snapshot_readiness_does_not_suppress_available_momentum_inputs() -> None:
    result = evaluate_momentum(_snapshot(), StrategyV1EvaluationConfig())

    assert result.passed is True


def test_identical_inputs_are_deterministic() -> None:
    snapshot = _snapshot()
    config = StrategyV1EvaluationConfig()

    assert evaluate_momentum(snapshot, config) == evaluate_momentum(snapshot, config)


@pytest.mark.parametrize(
    "config",
    [
        StrategyV1EvaluationConfig(rsi_period=13),
        StrategyV1EvaluationConfig(adx_period=13),
        StrategyV1EvaluationConfig(macd_fast_period=11),
    ],
)
def test_unsupported_indicator_periods_fail_fast(config: StrategyV1EvaluationConfig) -> None:
    with pytest.raises(ValueError, match="IndicatorSnapshot exposes only"):
        evaluate_momentum(_snapshot(), config)
