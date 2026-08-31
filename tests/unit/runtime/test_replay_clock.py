from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from signalforge.config.strategy_v1 import StrategyV1EvaluationConfig
from signalforge.domain.armed import ExpiryReason
from signalforge.domain.exits import ExitReason
from signalforge.domain.ids import ConfigId, InstrumentId, RunId
from signalforge.domain.indicators import IndicatorSnapshot
from signalforge.domain.instruments import TickSizeRule, TickSizeSchedule
from signalforge.domain.market import CandleQuality, CompletedCandle, MarketEvent
from signalforge.domain.money import Price, Quantity
from signalforge.domain.provenance import RunIdentity, StrategyIdentity
from signalforge.domain.time import IST, CandleInterval
from signalforge.runtime.eligibility import MarketDataFeedState
from signalforge.runtime.indicators import IndicatorContinuity
from signalforge.runtime.lifecycle import LifecycleState
from signalforge.runtime.replay import InMemoryReplaySource
from signalforge.runtime.replay_clock import ReplaySessionClock
from signalforge.runtime.replay_runtime import ReplayRuntime
from signalforge.runtime.strategy_evaluator import StrategyEvaluationContext, StrategyEvaluator

INSTRUMENT = InstrumentId("NSE:RELIANCE")


def _run() -> RunIdentity:
    return RunIdentity(
        run_id=RunId("run-041"),
        strategy=StrategyIdentity("intraday_momentum_v1", "1.0.0"),
        config_id=ConfigId("config-041"),
        config_hash="hash-041",
        engine_calculation_version="engine-v1",
    )


def _schedule() -> TickSizeSchedule:
    return TickSizeSchedule(
        instrument_id=INSTRUMENT,
        rules=(TickSizeRule(Price(Decimal("0.10")), date(2026, 1, 1)),),
    )


def _event(hour: int, minute: int, price: str) -> MarketEvent:
    at = datetime(2026, 8, 31, hour, minute, tzinfo=IST)
    return MarketEvent(
        instrument_id=INSTRUMENT,
        exchange_timestamp=at,
        received_timestamp=at + timedelta(milliseconds=1),
        price=Price(Decimal(price)),
        quantity=1,
        source="replay-clock-test",
        source_event_id=f"evt-{hour:02d}{minute:02d}-{price}",
    )


def _context_factory(_candle: CompletedCandle) -> StrategyEvaluationContext:
    return StrategyEvaluationContext(
        completed_regular_session_candles=250,
        continuity=IndicatorContinuity.HEALTHY,
        feed_state=MarketDataFeedState.HEALTHY,
    )


def _runtime(events: tuple[MarketEvent, ...]) -> ReplayRuntime:
    return ReplayRuntime(
        source=InMemoryReplaySource(instrument_id=INSTRUMENT, events=events),
        run=_run(),
        tick_schedule=_schedule(),
        quantity=Quantity(10),
        strategy_config=StrategyV1EvaluationConfig(),
        evaluation_context_factory=_context_factory,
    )


def _signal_candle(*, end_hour: int, end_minute: int) -> CompletedCandle:
    end = datetime(2026, 8, 31, end_hour, end_minute, tzinfo=IST)
    return CompletedCandle(
        instrument_id=INSTRUMENT,
        interval=CandleInterval(start=end - timedelta(minutes=5), end=end),
        quality=CandleQuality.VALID,
        open=Price(Decimal("100.00")),
        high=Price(Decimal("101.00")),
        low=Price(Decimal("99.00")),
        close=Price(Decimal("100.11")),
        volume=100,
        source="replay-clock-test",
        source_event_count=4,
    )


def _actionable(candle: CompletedCandle):
    snapshot = IndicatorSnapshot(
        instrument_id=INSTRUMENT,
        interval=candle.interval,
        ready=True,
        calculation_version="engine-v1",
        ema9=Decimal("99.90"),
        ema20=Decimal("101.00"),
        ema50=Decimal("100.00"),
        rsi14=Decimal("60"),
        adx14=Decimal("23"),
        macd_line=Decimal("1"),
        macd_signal=Decimal("0.50"),
        macd_histogram=Decimal("0.50"),
    )
    return StrategyEvaluator(StrategyV1EvaluationConfig()).evaluate(
        candle,
        snapshot,
        _context_factory(candle),
    )


def _arm(runtime: ReplayRuntime, *, end_hour: int, end_minute: int) -> None:
    candle = _signal_candle(end_hour=end_hour, end_minute=end_minute)
    result = runtime.lifecycle.process_evaluation(candle, _actionable(candle))
    assert result.state is LifecycleState.ARMED


def test_clock_expires_setup_at_valid_until_before_later_market_event() -> None:
    runtime = _runtime((_event(10, 6, "101.00"),))
    _arm(runtime, end_hour=10, end_minute=0)
    clock = ReplaySessionClock(runtime=runtime)

    step = clock.run_all()[0]

    assert step.time_dispatch is not None
    assert step.time_dispatch.boundary_at == datetime(2026, 8, 31, 10, 5, tzinfo=IST)
    assert step.runtime_step.lifecycle.state is LifecycleState.EXPIRED
    assert step.runtime_step.lifecycle.arming is not None
    setup = step.runtime_step.lifecycle.arming.armed_setup
    assert setup.expiry_reason is ExpiryReason.VALIDITY_WINDOW_END
    assert setup.terminal_at == datetime(2026, 8, 31, 10, 5, tzinfo=IST)
    assert step.runtime_step.lifecycle.execution is None


def test_clock_reproduces_1505_cutoff_with_cutoff_precedence() -> None:
    runtime = _runtime((_event(15, 5, "101.00"),))
    _arm(runtime, end_hour=15, end_minute=0)
    clock = ReplaySessionClock(runtime=runtime)

    step = clock.run_all()[0]

    assert step.time_dispatch is not None
    assert step.time_dispatch.boundary_at == datetime(2026, 8, 31, 15, 5, tzinfo=IST)
    assert step.runtime_step.lifecycle.arming is not None
    setup = step.runtime_step.lifecycle.arming.armed_setup
    assert setup.expiry_reason is ExpiryReason.ENTRY_CUTOFF_REACHED
    assert step.runtime_step.lifecycle.execution is None


def test_1515_does_not_create_synthetic_exit_and_first_real_event_forces_exit() -> None:
    runtime = _runtime((_event(15, 16, "100.00"),))
    _arm(runtime, end_hour=14, end_minute=55)
    opened = runtime.lifecycle.process_market_event(_event(14, 56, "100.50"))
    assert opened.state is LifecycleState.OPEN

    clock = ReplaySessionClock(runtime=runtime)
    step = clock.run_all()[0]

    assert step.time_dispatch is None
    assert step.runtime_step.lifecycle.state is LifecycleState.CLOSED
    assert step.runtime_step.lifecycle.exit is not None
    assert step.runtime_step.lifecycle.exit.reason is ExitReason.FORCED_SESSION_EXIT
    assert step.runtime_step.lifecycle.exit.exited_at == datetime(
        2026, 8, 31, 15, 16, tzinfo=IST
    )


def test_clock_processes_only_current_input_without_future_peek() -> None:
    runtime = _runtime((_event(10, 0, "100"), _event(10, 5, "101")))
    clock = ReplaySessionClock(runtime=runtime)
    iterator = iter(runtime.source)
    first = next(iterator)

    step = clock.process_input(first)

    assert step.replay_input.sequence == 0
    assert clock.last_event_at == datetime(2026, 8, 31, 10, 0, tzinfo=IST)
    assert next(iterator).sequence == 1


def test_clock_rejects_manual_backward_processing() -> None:
    runtime = _runtime((_event(10, 0, "100"), _event(10, 5, "101")))
    clock = ReplaySessionClock(runtime=runtime)
    inputs = tuple(runtime.source)

    clock.process_input(inputs[1])
    with pytest.raises(ValueError, match="non-decreasing"):
        clock.process_input(inputs[0])
