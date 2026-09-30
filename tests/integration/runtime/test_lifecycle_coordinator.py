from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from signalforge.config.strategy_v1 import StrategyV1EvaluationConfig
from signalforge.domain.armed import ExpiryReason
from signalforge.domain.audit import TransitionEntityType
from signalforge.domain.ids import ConfigId, InstrumentId, RunId
from signalforge.domain.indicators import IndicatorSnapshot
from signalforge.domain.instruments import TickSizeRule, TickSizeSchedule
from signalforge.domain.market import CandleQuality, CompletedCandle, MarketEvent
from signalforge.domain.money import Price, Quantity
from signalforge.domain.provenance import RunIdentity, StrategyIdentity
from signalforge.domain.time import IST, CandleInterval
from signalforge.runtime.eligibility import MarketDataFeedState
from signalforge.runtime.indicators import IndicatorContinuity
from signalforge.runtime.lifecycle import LifecycleCoordinator, LifecycleState
from signalforge.runtime.strategy import ArmIntent
from signalforge.runtime.strategy_evaluator import (
    StrategyEvaluationContext,
    StrategyEvaluator,
)
from signalforge.runtime.strategy_v1 import IntradayMomentumV1Strategy

INSTRUMENT = InstrumentId("NSE:RELIANCE")


def _run() -> RunIdentity:
    return RunIdentity(
        run_id=RunId("run-037"),
        strategy=StrategyIdentity("intraday_momentum_v1", "1.0.0"),
        config_id=ConfigId("config-037"),
        config_hash="hash-037",
        engine_calculation_version="engine-v1",
    )


def _schedule() -> TickSizeSchedule:
    return TickSizeSchedule(
        instrument_id=INSTRUMENT,
        rules=(TickSizeRule(Price(Decimal("0.10")), date(2026, 1, 1)),),
    )


def _candle(*, end_minute: int = 0) -> CompletedCandle:
    end = datetime(2026, 8, 31, 10, end_minute, tzinfo=IST)
    return CompletedCandle(
        instrument_id=INSTRUMENT,
        interval=CandleInterval(start=end - timedelta(minutes=5), end=end),
        quality=CandleQuality.VALID,
        open=Price(Decimal("100.00")),
        high=Price(Decimal("102.00")),
        low=Price(Decimal("99.00")),
        close=Price(Decimal("100.11")),
        volume=100,
        source="test",
        source_event_count=4,
    )


def _evaluation(candle: CompletedCandle):
    snapshot = IndicatorSnapshot(
        instrument_id=INSTRUMENT,
        interval=candle.interval,
        ready=True,
        calculation_version="engine-v1",
        ema9=Decimal("99"),
        ema20=Decimal("101"),
        ema50=Decimal("100"),
        rsi14=Decimal("60"),
        adx14=Decimal("23"),
        macd_line=Decimal("1"),
        macd_signal=Decimal("0.5"),
        macd_histogram=Decimal("0.5"),
    )
    return StrategyEvaluator(StrategyV1EvaluationConfig()).evaluate(
        candle,
        snapshot,
        StrategyEvaluationContext(
            completed_regular_session_candles=250,
            continuity=IndicatorContinuity.HEALTHY,
            feed_state=MarketDataFeedState.HEALTHY,
        ),
    )


def _event(price: str, minute: int, *, instrument: InstrumentId = INSTRUMENT) -> MarketEvent:
    at = datetime(2026, 8, 31, 10, minute, tzinfo=IST)
    return MarketEvent(
        instrument_id=instrument,
        exchange_timestamp=at,
        received_timestamp=at,
        price=Price(Decimal(price)),
        quantity=1,
        source="test",
        source_event_id=f"evt-{minute}-{price}",
    )


def _coordinator() -> LifecycleCoordinator:
    return LifecycleCoordinator(
        run=_run(),
        tick_schedule=_schedule(),
        quantity=Quantity(10),
        strategy=IntradayMomentumV1Strategy(StrategyV1EvaluationConfig()),
    )


def test_actionable_evaluation_arms_and_duplicate_is_idempotent() -> None:
    coordinator = _coordinator()
    candle = _candle()
    result = _evaluation(candle)

    first = coordinator.process_evaluation(candle, result)
    second = coordinator.process_evaluation(candle, result)

    assert first.state is LifecycleState.ARMED
    assert second.arming is first.arming
    assert len(coordinator.audit_transitions) == 1
    transition = coordinator.audit_transitions[0]
    assert transition.entity_type is TransitionEntityType.ARMED_SETUP
    assert (transition.from_state, transition.to_state) == ("none", "armed")


def test_trigger_routes_through_paper_fill_to_open_and_audits_all_transitions() -> None:
    coordinator = _coordinator()
    candle = _candle()
    coordinator.process_evaluation(candle, _evaluation(candle))

    snapshot = coordinator.process_market_event(_event("100.30", 1))

    assert snapshot.state is LifecycleState.OPEN
    assert snapshot.execution is not None
    assert snapshot.execution.fill.fill_price == Price(Decimal("100.30"))
    assert snapshot.open_result is not None and snapshot.open_result.opened
    transitions = coordinator.audit_transitions
    assert [(t.entity_type.value, t.from_state, t.to_state) for t in transitions] == [
        ("armed_setup", "none", "armed"),
        ("armed_setup", "armed", "triggered"),
        ("trade", "none", "open"),
        ("position", "none", "open"),
    ]


def test_open_position_blocks_later_actionable_evaluation_from_pyramiding() -> None:
    coordinator = _coordinator()
    first_candle = _candle()
    coordinator.process_evaluation(first_candle, _evaluation(first_candle))
    coordinator.process_market_event(_event("100.30", 1))

    later = _candle(end_minute=5)
    snapshot = coordinator.process_evaluation(later, _evaluation(later))

    assert snapshot.state is LifecycleState.OPEN
    assert snapshot.arming is not None
    assert snapshot.arming.signal.interval == first_candle.interval


def test_exit_closes_trade_and_position_once_and_duplicate_is_idempotent() -> None:
    coordinator = _coordinator()
    candle = _candle()
    coordinator.process_evaluation(candle, _evaluation(candle))
    coordinator.process_market_event(_event("100.30", 1))

    first = coordinator.process_market_event(_event("102.30", 2))
    audit_count = len(coordinator.audit_transitions)
    second = coordinator.process_market_event(_event("102.30", 2))

    assert first.state is LifecycleState.CLOSED
    assert first.exit is not None
    assert second.exit is first.exit
    assert len(coordinator.audit_transitions) == audit_count
    closing_transitions = [
        (t.entity_type.value, t.from_state, t.to_state)
        for t in coordinator.audit_transitions[-2:]
    ]
    assert closing_transitions == [
        ("trade", "open", "closed"),
        ("position", "open", "closed"),
    ]


def test_expiry_via_time_is_audited() -> None:
    coordinator = _coordinator()
    candle = _candle()
    coordinator.process_evaluation(candle, _evaluation(candle))

    snapshot = coordinator.process_time(datetime(2026, 8, 31, 15, 5, tzinfo=IST))

    assert snapshot.state is LifecycleState.EXPIRED
    assert coordinator.audit_transitions[-1].to_state == "expired"


def test_invalid_market_event_contract_fails_explicitly_when_open() -> None:
    coordinator = _coordinator()
    candle = _candle()
    coordinator.process_evaluation(candle, _evaluation(candle))
    coordinator.process_market_event(_event("100.30", 1))

    with pytest.raises(ValueError, match="instruments must match"):
        coordinator.process_market_event(
            _event("101.00", 2, instrument=InstrumentId("NSE:TCS"))
        )


def test_new_actionable_signal_can_start_after_closed_without_losing_audit_history() -> None:
    coordinator = _coordinator()
    candle = _candle()
    coordinator.process_evaluation(candle, _evaluation(candle))
    coordinator.process_market_event(_event("100.30", 1))
    coordinator.process_market_event(_event("102.30", 2))
    prior_audit_count = len(coordinator.audit_transitions)

    later = _candle(end_minute=5)
    snapshot = coordinator.process_evaluation(later, _evaluation(later))

    assert snapshot.state is LifecycleState.ARMED
    assert snapshot.exit is None
    assert len(coordinator.audit_transitions) == prior_audit_count + 1



class _LateTriggerStrategy(IntradayMomentumV1Strategy):
    def arm_intent(self, candle, decision):
        if candle.low is None:
            raise ValueError("test candle requires low")
        return ArmIntent(
            raw_trigger=Price(Decimal("100.20")),
            stop_price=candle.low,
            valid_until=candle.interval.end.replace(hour=16, minute=0),
        )

    def evaluate_armed_market_event(self, signal, setup, event):
        from signalforge.runtime.strategy import ArmedEventAction, ArmedEventDecision

        return ArmedEventDecision(ArmedEventAction.TRIGGER, at=event.exchange_timestamp)


class _NonPositiveRiskStrategy(IntradayMomentumV1Strategy):
    def arm_intent(self, candle, decision):
        return ArmIntent(
            raw_trigger=Price(Decimal("100.20")),
            stop_price=Price(Decimal("101.00")),
            valid_until=candle.interval.end + timedelta(minutes=5),
        )

    def post_fill_economics(self, fill, setup, tick_size):
        raise AssertionError("post-fill target economics must not run for non-positive risk")


def test_shared_session_safety_blocks_strategy_trigger_after_1515() -> None:
    strategy = _LateTriggerStrategy(StrategyV1EvaluationConfig())
    coordinator = LifecycleCoordinator(
        run=_run(),
        tick_schedule=_schedule(),
        quantity=Quantity(10),
        strategy=strategy,
    )
    candle = _candle()
    coordinator.process_evaluation(candle, _evaluation(candle))
    late_at = datetime(2026, 8, 31, 15, 16, tzinfo=IST)
    late_event = MarketEvent(
        instrument_id=INSTRUMENT,
        exchange_timestamp=late_at,
        received_timestamp=late_at,
        price=Price(Decimal("200.00")),
        quantity=1,
        source="test",
        source_event_id="late-trigger",
    )

    snapshot = coordinator.process_market_event(late_event)

    assert snapshot.state is LifecycleState.EXPIRED
    assert snapshot.execution is None
    assert snapshot.arming is not None
    assert snapshot.arming.armed_setup.expiry_reason is ExpiryReason.ENTRY_CUTOFF_REACHED
    assert snapshot.arming.armed_setup.terminal_at == datetime(
        2026, 8, 31, 15, 15, tzinfo=IST
    )


def test_non_positive_risk_rejects_before_post_fill_target_economics() -> None:
    strategy = _NonPositiveRiskStrategy(StrategyV1EvaluationConfig())
    coordinator = LifecycleCoordinator(
        run=_run(),
        tick_schedule=_schedule(),
        quantity=Quantity(10),
        strategy=strategy,
    )
    candle = _candle()
    coordinator.process_evaluation(candle, _evaluation(candle))

    snapshot = coordinator.process_market_event(_event("100.30", 1))

    assert snapshot.execution is not None
    assert snapshot.open_result is not None
    assert snapshot.open_result.opened is False
    assert snapshot.open_result.rejection is not None
