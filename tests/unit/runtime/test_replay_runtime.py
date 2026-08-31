from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from signalforge.config.strategy_v1 import StrategyV1EvaluationConfig
from signalforge.domain.ids import ConfigId, InstrumentId, RunId
from signalforge.domain.instruments import TickSizeRule, TickSizeSchedule
from signalforge.domain.market import MarketEvent
from signalforge.domain.money import Price, Quantity
from signalforge.domain.provenance import RunIdentity, StrategyIdentity
from signalforge.domain.time import IST
from signalforge.runtime.eligibility import MarketDataFeedState
from signalforge.runtime.indicators import IndicatorContinuity
from signalforge.runtime.lifecycle import LifecycleState
from signalforge.runtime.replay import InMemoryReplaySource, ReplayInput
from signalforge.runtime.replay_runtime import ReplayRuntime
from signalforge.runtime.strategy_evaluator import StrategyEvaluationContext

INSTRUMENT = InstrumentId("NSE:RELIANCE")


def _run() -> RunIdentity:
    return RunIdentity(
        run_id=RunId("run-040"),
        strategy=StrategyIdentity("intraday_momentum_v1", "1.0.0"),
        config_id=ConfigId("config-040"),
        config_hash="hash-040",
        engine_calculation_version="engine-v1",
    )


def _schedule(instrument_id: InstrumentId = INSTRUMENT) -> TickSizeSchedule:
    return TickSizeSchedule(
        instrument_id=instrument_id,
        rules=(TickSizeRule(Price(Decimal("0.10")), date(2026, 1, 1)),),
    )


def _event(minute: int, price: str) -> MarketEvent:
    at = datetime(2026, 8, 31, 10, minute, tzinfo=IST)
    return MarketEvent(
        instrument_id=INSTRUMENT,
        exchange_timestamp=at,
        received_timestamp=at + timedelta(milliseconds=1),
        price=Price(Decimal(price)),
        quantity=1,
        source="replay-test",
        source_event_id=f"evt-{minute}-{price}",
    )


def _context_factory(_candle):
    return StrategyEvaluationContext(
        completed_regular_session_candles=250,
        continuity=IndicatorContinuity.HEALTHY,
        feed_state=MarketDataFeedState.HEALTHY,
    )


def _runtime(events: tuple[MarketEvent, ...]) -> ReplayRuntime:
    source = InMemoryReplaySource(instrument_id=INSTRUMENT, events=events)
    return ReplayRuntime(
        source=source,
        run=_run(),
        tick_schedule=_schedule(),
        quantity=Quantity(10),
        strategy_config=StrategyV1EvaluationConfig(),
        evaluation_context_factory=_context_factory,
    )


def test_processes_market_events_and_only_evaluates_completed_candles() -> None:
    runtime = _runtime((_event(0, "100"), _event(1, "101"), _event(5, "102")))

    steps = runtime.run_all()

    assert len(steps) == 3
    assert steps[0].completed_candle is None
    assert steps[0].indicator_snapshot is None
    assert steps[0].evaluation is None
    assert steps[1].completed_candle is None
    assert steps[2].completed_candle is not None
    assert steps[2].completed_candle.open == Price(Decimal("100"))
    assert steps[2].completed_candle.close == Price(Decimal("101"))
    assert steps[2].indicator_snapshot is not None
    assert steps[2].evaluation is not None
    assert runtime.indicator_engine.state.ema9.samples == 1


def test_runtime_keeps_one_authoritative_lifecycle_instance() -> None:
    runtime = _runtime((_event(0, "100"), _event(5, "101"), _event(10, "102")))

    steps = runtime.run_all()

    assert all(step.lifecycle.state is LifecycleState.IDLE for step in steps)
    assert steps[-1].lifecycle == runtime.lifecycle.snapshot()


def test_evaluation_context_is_requested_only_for_completed_candles() -> None:
    calls = []

    def context_factory(candle):
        calls.append(candle.interval)
        return _context_factory(candle)

    source = InMemoryReplaySource(
        instrument_id=INSTRUMENT,
        events=(_event(0, "100"), _event(1, "101"), _event(5, "102")),
    )
    runtime = ReplayRuntime(
        source=source,
        run=_run(),
        tick_schedule=_schedule(),
        quantity=Quantity(10),
        strategy_config=StrategyV1EvaluationConfig(),
        evaluation_context_factory=context_factory,
    )

    runtime.run_all()

    assert len(calls) == 1


def test_rejects_tick_schedule_for_different_instrument() -> None:
    source = InMemoryReplaySource(instrument_id=INSTRUMENT, events=())

    with pytest.raises(ValueError, match="tick schedule instruments must match"):
        ReplayRuntime(
            source=source,
            run=_run(),
            tick_schedule=_schedule(InstrumentId("NSE:TCS")),
            quantity=Quantity(10),
            strategy_config=StrategyV1EvaluationConfig(),
            evaluation_context_factory=_context_factory,
        )


def test_rejects_replay_input_from_different_source_identity() -> None:
    runtime = _runtime((_event(0, "100"),))
    foreign_source = InMemoryReplaySource(instrument_id=INSTRUMENT, events=(_event(1, "101"),))
    foreign_input = next(iter(foreign_source))

    with pytest.raises(ValueError, match="source identity"):
        runtime.process_input(foreign_input)


def test_process_input_is_serial_and_does_not_consume_future_source_items() -> None:
    events = (_event(0, "100"), _event(5, "101"))
    source = InMemoryReplaySource(instrument_id=INSTRUMENT, events=events)
    runtime = ReplayRuntime(
        source=source,
        run=_run(),
        tick_schedule=_schedule(),
        quantity=Quantity(10),
        strategy_config=StrategyV1EvaluationConfig(),
        evaluation_context_factory=_context_factory,
    )
    iterator = iter(source)
    first: ReplayInput = next(iterator)

    step = runtime.process_input(first)

    assert step.replay_input.sequence == 0
    assert runtime.candle_engine.active_interval is not None
    assert runtime.indicator_engine.state.ema9.samples == 0
    assert next(iterator).sequence == 1
