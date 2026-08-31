from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from signalforge.config.strategy_v1 import StrategyV1EvaluationConfig
from signalforge.domain.ids import InstrumentId
from signalforge.domain.indicators import IndicatorSnapshot
from signalforge.domain.market import CandleQuality, CompletedCandle
from signalforge.domain.money import Price
from signalforge.domain.time import IST, CandleInterval
from signalforge.runtime.setup import evaluate_setup


def _facts(
    *,
    close: Decimal = Decimal("101"),
    ema9: Decimal | None = Decimal("100"),
    candle_instrument: InstrumentId | None = None,
    snapshot_instrument: InstrumentId | None = None,
    snapshot_interval_shift_minutes: int = 0,
    quality: CandleQuality = CandleQuality.VALID,
) -> tuple[CompletedCandle, IndicatorSnapshot]:
    instrument = InstrumentId("NSE:TEST")
    candle_instrument = candle_instrument or instrument
    snapshot_instrument = snapshot_instrument or instrument
    start = datetime(2026, 8, 31, 10, 0, tzinfo=IST)
    candle_interval = CandleInterval(start=start, end=start + timedelta(minutes=5))
    snapshot_start = start + timedelta(minutes=snapshot_interval_shift_minutes)
    snapshot_interval = CandleInterval(
        start=snapshot_start,
        end=snapshot_start + timedelta(minutes=5),
    )
    candle = CompletedCandle(
        instrument_id=candle_instrument,
        interval=candle_interval,
        quality=quality,
        open=Price(close),
        high=Price(close + Decimal("1")),
        low=Price(close - Decimal("1")),
        close=Price(close),
        volume=100,
        source="test",
        source_event_count=1,
    )
    snapshot = IndicatorSnapshot(
        instrument_id=snapshot_instrument,
        interval=snapshot_interval,
        ready=False,
        calculation_version="test",
        ema9=ema9,
    )
    return candle, snapshot


def test_close_strictly_above_ema9_passes() -> None:
    candle, snapshot = _facts(close=Decimal("100.0001"), ema9=Decimal("100"))
    assert evaluate_setup(candle, snapshot, StrategyV1EvaluationConfig()).passed is True


def test_close_equal_to_ema9_fails() -> None:
    candle, snapshot = _facts(close=Decimal("100"), ema9=Decimal("100"))
    assert evaluate_setup(candle, snapshot, StrategyV1EvaluationConfig()).passed is False


def test_close_below_ema9_fails() -> None:
    candle, snapshot = _facts(close=Decimal("99.9999"), ema9=Decimal("100"))
    assert evaluate_setup(candle, snapshot, StrategyV1EvaluationConfig()).passed is False


def test_unavailable_ema9_cannot_pass() -> None:
    candle, snapshot = _facts(ema9=None)
    assert evaluate_setup(candle, snapshot, StrategyV1EvaluationConfig()).passed is False


def test_mismatched_instrument_is_rejected() -> None:
    candle, snapshot = _facts(snapshot_instrument=InstrumentId("NSE:OTHER"))
    with pytest.raises(ValueError, match="instrument identities"):
        evaluate_setup(candle, snapshot, StrategyV1EvaluationConfig())


def test_mismatched_interval_is_rejected() -> None:
    candle, snapshot = _facts(snapshot_interval_shift_minutes=5)
    with pytest.raises(ValueError, match="intervals must match"):
        evaluate_setup(candle, snapshot, StrategyV1EvaluationConfig())


def test_candle_quality_does_not_change_isolated_setup_truth() -> None:
    candle, snapshot = _facts(quality=CandleQuality.STALE)
    assert evaluate_setup(candle, snapshot, StrategyV1EvaluationConfig()).passed is True


def test_unsupported_setup_period_fails_fast() -> None:
    candle, snapshot = _facts()
    config = StrategyV1EvaluationConfig(setup_ema_period=10)
    with pytest.raises(ValueError, match="exposes only EMA9"):
        evaluate_setup(candle, snapshot, config)


def test_identical_inputs_are_deterministic() -> None:
    candle, snapshot = _facts()
    config = StrategyV1EvaluationConfig()
    assert evaluate_setup(candle, snapshot, config) == evaluate_setup(candle, snapshot, config)
