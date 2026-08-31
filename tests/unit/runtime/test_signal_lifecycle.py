from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

from signalforge.config.strategy_v1 import StrategyV1EvaluationConfig
from signalforge.domain.ids import ConfigId, InstrumentId, RunId
from signalforge.domain.indicators import IndicatorSnapshot
from signalforge.domain.instruments import TickSizeRule, TickSizeSchedule
from signalforge.domain.market import CandleQuality, CompletedCandle
from signalforge.domain.money import Price
from signalforge.domain.provenance import RunIdentity, StrategyIdentity
from signalforge.domain.time import IST, CandleInterval
from signalforge.runtime.eligibility import MarketDataFeedState
from signalforge.runtime.indicators import IndicatorContinuity
from signalforge.runtime.signal_lifecycle import SignalLifecycleManager
from signalforge.runtime.strategy_evaluator import (
    StrategyEvaluationContext,
    StrategyEvaluator,
)

INSTRUMENT = InstrumentId("NSE:RELIANCE")


def _run() -> RunIdentity:
    return RunIdentity(
        run_id=RunId("run-001"),
        strategy=StrategyIdentity("intraday_momentum_v1", "1.0.0"),
        config_id=ConfigId("config-001"),
        config_hash="abc123",
        engine_calculation_version="engine-v1",
    )


def _interval(*, end_hour: int = 10, end_minute: int = 0) -> CandleInterval:
    end = datetime(2026, 8, 31, end_hour, end_minute, tzinfo=IST)
    return CandleInterval(start=end - timedelta(minutes=5), end=end)


def _candle(
    *,
    interval: CandleInterval | None = None,
    close: str = "100.11",
    low: str = "99.00",
) -> CompletedCandle:
    interval = interval or _interval()
    return CompletedCandle(
        instrument_id=INSTRUMENT,
        interval=interval,
        quality=CandleQuality.VALID,
        open=Price(Decimal("100")),
        high=Price(Decimal("102")),
        low=Price(Decimal(low)),
        close=Price(Decimal(close)),
        volume=100,
        source="test",
        source_event_count=4,
    )


def _snapshot(candle: CompletedCandle, *, rsi14: str = "60") -> IndicatorSnapshot:
    return IndicatorSnapshot(
        instrument_id=candle.instrument_id,
        interval=candle.interval,
        ready=True,
        calculation_version="engine-v1",
        ema9=Decimal("99"),
        ema20=Decimal("101"),
        ema50=Decimal("100"),
        rsi14=Decimal(rsi14),
        adx14=Decimal("23"),
        macd_line=Decimal("1"),
        macd_signal=Decimal("0.5"),
        macd_histogram=Decimal("0.5"),
    )


def _evaluation(candle: CompletedCandle, *, rsi14: str = "60"):
    evaluator = StrategyEvaluator(StrategyV1EvaluationConfig())
    return evaluator.evaluate(
        candle,
        _snapshot(candle, rsi14=rsi14),
        StrategyEvaluationContext(
            completed_regular_session_candles=250,
            continuity=IndicatorContinuity.HEALTHY,
            feed_state=MarketDataFeedState.HEALTHY,
        ),
    )


def _schedule() -> TickSizeSchedule:
    return TickSizeSchedule(
        instrument_id=INSTRUMENT,
        rules=(
            TickSizeRule(
                tick_size=Price(Decimal("0.05")),
                effective_from=date(2026, 1, 1),
                effective_to=date(2026, 8, 30),
            ),
            TickSizeRule(
                tick_size=Price(Decimal("0.10")),
                effective_from=date(2026, 8, 31),
            ),
        ),
    )


def test_actionable_evaluation_creates_signal_and_immediately_arms_setup() -> None:
    candle = _candle()
    manager = SignalLifecycleManager(run=_run(), tick_schedule=_schedule())

    result = manager.arm_if_actionable(candle, _evaluation(candle))

    assert result is not None
    assert manager.active is result
    assert result.signal.instrument_id == INSTRUMENT
    assert result.signal.interval == candle.interval
    assert result.signal.signal_close == Price(Decimal("100.11"))
    assert result.signal.signal_low == Price(Decimal("99.00"))
    assert result.signal.run == _run()
    assert result.signal.created_at == candle.interval.end
    assert result.armed_setup.armed_at == candle.interval.end
    assert result.armed_setup.valid_until == candle.interval.end + timedelta(minutes=5)


def test_raw_trigger_is_exact_point_one_percent_and_tradable_trigger_ceil_to_tick() -> None:
    candle = _candle(close="100.11")
    manager = SignalLifecycleManager(run=_run(), tick_schedule=_schedule())

    result = manager.arm_if_actionable(candle, _evaluation(candle))

    assert result is not None
    assert result.armed_setup.raw_trigger == Price(Decimal("100.21011"))
    assert result.armed_setup.tradable_trigger == Price(Decimal("100.30"))
    assert result.armed_setup.signal_low == Price(Decimal("99.00"))


def test_effective_dated_tick_rule_is_resolved_from_signal_trading_date() -> None:
    interval = CandleInterval(
        start=datetime(2026, 8, 30, 9, 55, tzinfo=IST),
        end=datetime(2026, 8, 30, 10, 0, tzinfo=IST),
    )
    candle = _candle(interval=interval, close="100.11")
    manager = SignalLifecycleManager(run=_run(), tick_schedule=_schedule())

    result = manager.arm_if_actionable(candle, _evaluation(candle))

    assert result is not None
    assert result.armed_setup.raw_trigger == Price(Decimal("100.21011"))
    assert result.armed_setup.tradable_trigger == Price(Decimal("100.25"))


def test_duplicate_processing_returns_same_logical_facts() -> None:
    candle = _candle()
    evaluation = _evaluation(candle)
    manager = SignalLifecycleManager(run=_run(), tick_schedule=_schedule())

    first = manager.arm_if_actionable(candle, evaluation)
    second = manager.arm_if_actionable(candle, evaluation)

    assert first is not None
    assert second is first
    assert manager.active is first


def test_existing_armed_setup_blocks_different_actionable_evaluation() -> None:
    first_candle = _candle()
    next_interval = CandleInterval(
        start=first_candle.interval.end,
        end=first_candle.interval.end + timedelta(minutes=5),
    )
    second_candle = _candle(interval=next_interval, close="101.00", low="100.00")
    manager = SignalLifecycleManager(run=_run(), tick_schedule=_schedule())

    first = manager.arm_if_actionable(first_candle, _evaluation(first_candle))
    second = manager.arm_if_actionable(second_candle, _evaluation(second_candle))

    assert first is not None
    assert second is None
    assert manager.active is first


def test_open_position_blocks_new_actionable_setup() -> None:
    candle = _candle()
    manager = SignalLifecycleManager(run=_run(), tick_schedule=_schedule())

    result = manager.arm_if_actionable(candle, _evaluation(candle), open_position=True)

    assert result is None
    assert manager.active is None


def test_non_actionable_evaluation_creates_no_lifecycle_facts() -> None:
    candle = _candle()
    manager = SignalLifecycleManager(run=_run(), tick_schedule=_schedule())

    result = manager.arm_if_actionable(candle, _evaluation(candle, rsi14="57"))

    assert result is None
    assert manager.active is None


def test_tick_schedule_instrument_mismatch_is_rejected() -> None:
    candle = _candle()
    schedule = TickSizeSchedule(
        instrument_id=InstrumentId("NSE:TCS"),
        rules=(
            TickSizeRule(
                tick_size=Price(Decimal("0.05")),
                effective_from=date(2026, 1, 1),
            ),
        ),
    )
    manager = SignalLifecycleManager(run=_run(), tick_schedule=schedule)

    try:
        manager.arm_if_actionable(candle, _evaluation(candle))
    except ValueError as exc:
        assert "TickSizeSchedule instrument" in str(exc)
    else:
        raise AssertionError("Expected mismatched tick schedule to be rejected")
