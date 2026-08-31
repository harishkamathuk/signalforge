from datetime import UTC, datetime
from decimal import Decimal

import pytest

from signalforge.config.strategy_v1 import StrategyV1EvaluationConfig
from signalforge.domain.ids import InstrumentId
from signalforge.domain.indicators import IndicatorSnapshot
from signalforge.domain.strategy import TrendResult
from signalforge.domain.time import CandleInterval
from signalforge.runtime.trend import evaluate_trend


def _snapshot(*, ema20: Decimal | None, ema50: Decimal | None) -> IndicatorSnapshot:
    return IndicatorSnapshot(
        instrument_id=InstrumentId("NSE:TEST"),
        interval=CandleInterval.five_minutes(datetime(2026, 8, 31, 9, 15, tzinfo=UTC)),
        ready=False,
        calculation_version="test-v1",
        ema20=ema20,
        ema50=ema50,
    )


def test_trend_passes_only_when_ema20_is_strictly_above_ema50() -> None:
    config = StrategyV1EvaluationConfig()

    assert evaluate_trend(
        _snapshot(ema20=Decimal("101"), ema50=Decimal("100")), config
    ) == TrendResult(passed=True)
    assert evaluate_trend(
        _snapshot(ema20=Decimal("100"), ema50=Decimal("100")), config
    ) == TrendResult(passed=False)
    assert evaluate_trend(
        _snapshot(ema20=Decimal("99"), ema50=Decimal("100")), config
    ) == TrendResult(passed=False)


def test_unavailable_required_ema_never_passes() -> None:
    config = StrategyV1EvaluationConfig()

    assert evaluate_trend(_snapshot(ema20=None, ema50=Decimal("100")), config).passed is False
    assert evaluate_trend(_snapshot(ema20=Decimal("100"), ema50=None), config).passed is False
    assert evaluate_trend(_snapshot(ema20=None, ema50=None), config).passed is False


def test_snapshot_ready_flag_does_not_override_available_trend_values() -> None:
    config = StrategyV1EvaluationConfig()
    snapshot = _snapshot(ema20=Decimal("100.0000001"), ema50=Decimal("100"))

    assert snapshot.ready is False
    assert evaluate_trend(snapshot, config).passed is True


def test_experimental_periods_fail_fast_instead_of_using_wrong_snapshot_fields() -> None:
    config = StrategyV1EvaluationConfig(
        trend_fast_ema_period=10,
        trend_slow_ema_period=30,
    )

    with pytest.raises(ValueError, match="EMA20/EMA50"):
        evaluate_trend(
            _snapshot(ema20=Decimal("101"), ema50=Decimal("100")),
            config,
        )


def test_identical_inputs_are_deterministic() -> None:
    config = StrategyV1EvaluationConfig()
    snapshot = _snapshot(ema20=Decimal("101.23456789"), ema50=Decimal("101.23456788"))

    assert evaluate_trend(snapshot, config) == evaluate_trend(snapshot, config)
