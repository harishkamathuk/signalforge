from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from signalforge.config.rsi_mean_reversion_v1 import RsiMeanReversionV1Config
from signalforge.config.strategy_v1 import StrategyV1EvaluationConfig
from signalforge.domain.armed import ArmedSetup, ArmedSetupState, ExpiryReason
from signalforge.domain.audit import StateTransition, TransitionEntityType
from signalforge.domain.execution import EntryIntent, ExecutionMode, Fill, TriggerEvent
from signalforge.domain.ids import InstrumentId, RunId
from signalforge.domain.instruments import TickSizeRule, TickSizeSchedule
from signalforge.domain.market import MarketEvent
from signalforge.domain.money import Price, Quantity
from signalforge.domain.position_outcomes import PositionOpenOutcome, PositionOpenOutcomeType
from signalforge.domain.positions import Position
from signalforge.domain.provenance import RunIdentity
from signalforge.domain.signals import Signal
from signalforge.domain.time import IST, CandleInterval
from signalforge.domain.trades import Trade
from signalforge.runtime.indicator_recovery import (
    IndicatorRecoveryReconciler,
    IndicatorRecoveryResult,
)
from signalforge.runtime.indicators import IndicatorEngine
from signalforge.runtime.lifecycle import LifecycleCoordinator, LifecycleState
from signalforge.runtime.lifecycle_recovery import (
    LifecycleRecoveryError,
    LifecycleRecoveryHydrator,
)
from signalforge.runtime.recovery import RecoveredLifecycle
from signalforge.runtime.rsi_mean_reversion_v1 import RsiMeanReversionV1Strategy
from signalforge.runtime.strategy import Strategy
from signalforge.runtime.strategy_v1 import IntradayMomentumV1Strategy

INSTRUMENT = InstrumentId("NSE:SF051")
AT = datetime(2026, 10, 3, 10, 0, tzinfo=IST)


def _schedule() -> TickSizeSchedule:
    return TickSizeSchedule(
        instrument_id=INSTRUMENT,
        rules=(TickSizeRule(Price(Decimal("0.05")), date(2026, 1, 1)),),
    )


def _run(strategy: Strategy, suffix: str) -> RunIdentity:
    return RunIdentity(
        run_id=RunId(f"sf051-{suffix}"),
        strategy=strategy.identity,
        config_id=strategy.config_identity.config_id,
        config_hash=strategy.config_identity.config_hash,
        engine_calculation_version="engine-v1",
    )


def _signal_setup(
    strategy: Strategy, suffix: str
) -> tuple[RunIdentity, Signal, ArmedSetup, StateTransition]:
    run = _run(strategy, suffix)
    interval = CandleInterval.five_minutes(AT)
    signal = Signal.create(
        instrument_id=INSTRUMENT,
        interval=interval,
        signal_close=Price(Decimal("101.00")),
        signal_low=Price(Decimal("100.00")),
        run=run,
        created_at=interval.end,
    )
    setup = ArmedSetup(
        signal_id=signal.signal_id,
        raw_trigger=Price(Decimal("101.10")),
        tradable_trigger=Price(Decimal("101.10")),
        signal_low=Price(Decimal("100.00")),
        armed_at=interval.end,
        valid_until=interval.end + timedelta(minutes=5),
    )
    transition = StateTransition.create(
        entity_type=TransitionEntityType.ARMED_SETUP,
        entity_id=str(signal.signal_id),
        from_state="none",
        to_state="armed",
        cause_type="strategy_evaluation",
        cause_id="persisted-decision",
        occurred_at=setup.armed_at,
        run=run,
    )
    return run, signal, setup, transition


def _indicator_result(strategy: Strategy) -> IndicatorRecoveryResult:
    engine = IndicatorEngine(
        INSTRUMENT,
        "engine-v1",
        requirements=strategy.indicator_requirements,
    )
    return IndicatorRecoveryReconciler(engine.state).reconcile(())


def _coordinator(strategy: Strategy, run: RunIdentity) -> LifecycleCoordinator:
    return LifecycleCoordinator(
        run=run,
        tick_schedule=_schedule(),
        quantity=Quantity(10),
        strategy=strategy,
    )


def _event(price: str, *, minute: int = 6) -> MarketEvent:
    at = AT + timedelta(minutes=minute)
    return MarketEvent(
        instrument_id=INSTRUMENT,
        exchange_timestamp=at,
        received_timestamp=at + timedelta(milliseconds=1),
        price=Price(Decimal(price)),
        quantity=1,
        source="sf051-test",
        source_event_id=f"sf051-{minute}-{price}",
    )


@pytest.mark.parametrize("reference", (False, True))
def test_armed_hydration_restores_exact_persisted_facts(reference: bool) -> None:
    strategy: Strategy = (
        RsiMeanReversionV1Strategy(RsiMeanReversionV1Config())
        if reference
        else IntradayMomentumV1Strategy(StrategyV1EvaluationConfig())
    )
    run, signal, setup, transition = _signal_setup(strategy, f"armed-{reference}")
    recovered = RecoveredLifecycle(
        setup=setup,
        signal=signal,
        trigger=None,
        intent=None,
        fill=None,
        outcome=None,
        trade=None,
        position=None,
        exit_fact=None,
        transitions=(transition,),
    )
    coordinator = _coordinator(strategy, run)

    result = LifecycleRecoveryHydrator().hydrate(
        indicator_result=_indicator_result(strategy),
        recovered=recovered,
        coordinator=coordinator,
    )

    assert result.snapshot.state is LifecycleState.ARMED
    assert result.snapshot.arming is not None
    assert result.snapshot.arming.signal == signal
    assert result.snapshot.arming.armed_setup is setup
    assert result.coordinator.audit_transitions == (transition,)


def test_recovered_armed_policy_remains_strategy_owned() -> None:
    v1 = IntradayMomentumV1Strategy(StrategyV1EvaluationConfig())
    ref = RsiMeanReversionV1Strategy(RsiMeanReversionV1Config())

    v1_run, v1_signal, v1_setup, v1_transition = _signal_setup(v1, "v1-policy")
    ref_run, ref_signal, ref_setup, ref_transition = _signal_setup(ref, "ref-policy")

    v1_coordinator = _coordinator(v1, v1_run)
    ref_coordinator = _coordinator(ref, ref_run)
    hydrator = LifecycleRecoveryHydrator()

    hydrator.hydrate(
        indicator_result=_indicator_result(v1),
        recovered=RecoveredLifecycle(
            v1_setup,
            v1_signal,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            (v1_transition,),
        ),
        coordinator=v1_coordinator,
    )
    hydrator.hydrate(
        indicator_result=_indicator_result(ref),
        recovered=RecoveredLifecycle(
            ref_setup,
            ref_signal,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            (ref_transition,),
        ),
        coordinator=ref_coordinator,
    )

    event = _event("99.90")
    v1_after = v1_coordinator.process_market_event(event)
    ref_after = ref_coordinator.process_market_event(event)

    assert v1_after.state is LifecycleState.EXPIRED
    assert v1_after.arming is not None
    assert v1_after.arming.armed_setup.expiry_reason is ExpiryReason.SIGNAL_LOW_BREACH
    assert ref_after.state is LifecycleState.ARMED
    assert ref_after.arming is not None
    assert ref_after.arming.armed_setup.state is ArmedSetupState.ARMED


def test_open_hydration_restores_frozen_economics_and_continues_exit_logic() -> None:
    strategy = IntradayMomentumV1Strategy(StrategyV1EvaluationConfig())
    run, signal, setup, arm_transition = _signal_setup(strategy, "open")
    trigger = TriggerEvent.create(
        signal_id=signal.signal_id,
        instrument_id=INSTRUMENT,
        reference_price=setup.tradable_trigger,
        observed_price=Price(Decimal("101.20")),
        observed_at=setup.armed_at + timedelta(minutes=1),
        run=run,
    )
    setup.trigger(at=trigger.observed_at)
    intent = EntryIntent.create(
        trigger_event_id=trigger.trigger_event_id,
        signal_id=signal.signal_id,
        instrument_id=INSTRUMENT,
        reference_price=trigger.reference_price,
        quantity=Quantity(10),
        execution_mode=ExecutionMode.PAPER,
        created_at=trigger.observed_at,
        run=run,
    )
    fill = Fill.create(
        entry_intent_id=intent.entry_intent_id,
        trigger_event_id=trigger.trigger_event_id,
        signal_id=signal.signal_id,
        instrument_id=INSTRUMENT,
        reference_price=trigger.reference_price,
        fill_price=Price(Decimal("101.20")),
        quantity=intent.quantity,
        execution_mode=ExecutionMode.PAPER,
        filled_at=trigger.observed_at,
        run=run,
    )
    trade = Trade.open_from_fill(
        entry_fill=fill,
        stop_price=Price(Decimal("100.00")),
        raw_target_price=Price(Decimal("102.40")),
        tradable_target_price=Price(Decimal("102.40")),
    )
    position = Position.open_from_trade(trade=trade)
    outcome = PositionOpenOutcome.create(
        fill_id=fill.fill_id,
        signal_id=signal.signal_id,
        outcome=PositionOpenOutcomeType.OPENED,
        decided_at=fill.filled_at,
        run=run,
    )
    transitions = (
        arm_transition,
        StateTransition.create(
            entity_type=TransitionEntityType.ARMED_SETUP,
            entity_id=str(signal.signal_id),
            from_state="armed",
            to_state="triggered",
            cause_type="trigger_event",
            cause_id=str(trigger.trigger_event_id),
            occurred_at=trigger.observed_at,
            run=run,
        ),
        StateTransition.create(
            entity_type=TransitionEntityType.TRADE,
            entity_id=str(trade.trade_id),
            from_state="none",
            to_state="open",
            cause_type="fill",
            cause_id=str(fill.fill_id),
            occurred_at=trade.opened_at,
            run=run,
        ),
        StateTransition.create(
            entity_type=TransitionEntityType.POSITION,
            entity_id=str(position.position_id),
            from_state="none",
            to_state="open",
            cause_type="trade",
            cause_id=str(trade.trade_id),
            occurred_at=position.opened_at,
            run=run,
        ),
    )
    coordinator = _coordinator(strategy, run)

    result = LifecycleRecoveryHydrator().hydrate(
        indicator_result=_indicator_result(strategy),
        recovered=RecoveredLifecycle(
            setup,
            signal,
            trigger,
            intent,
            fill,
            outcome,
            trade,
            position,
            None,
            transitions,
        ),
        coordinator=coordinator,
    )

    assert result.snapshot.state is LifecycleState.OPEN
    assert result.snapshot.execution is not None
    assert result.snapshot.execution.entry_intent is intent
    assert result.snapshot.execution.fill is fill
    assert result.snapshot.open_result is not None
    assert result.snapshot.open_result.trade is trade
    assert result.snapshot.open_result.position is position
    assert trade.entry_price == Price(Decimal("101.20"))
    assert trade.stop_price == Price(Decimal("100.00"))
    assert trade.raw_target_price == Price(Decimal("102.40"))
    assert trade.tradable_target_price == Price(Decimal("102.40"))
    assert trade.risk_per_share == Price(Decimal("1.20"))

    first = coordinator.process_market_event(_event("102.50", minute=7))
    audit_count = len(coordinator.audit_transitions)
    second = coordinator.process_market_event(_event("102.50", minute=7))

    assert first.state is LifecycleState.CLOSED
    assert first.exit is not None
    assert second.exit is first.exit
    assert len(coordinator.audit_transitions) == audit_count


def test_lifecycle_hydration_rejects_broken_indicator_prerequisite() -> None:
    strategy = IntradayMomentumV1Strategy(StrategyV1EvaluationConfig())
    run, signal, setup, transition = _signal_setup(strategy, "broken-indicators")
    indicator_engine = IndicatorEngine(
        INSTRUMENT,
        "engine-v1",
        requirements=strategy.indicator_requirements,
    )
    indicator_engine.break_continuity()

    with pytest.raises(LifecycleRecoveryError, match="not healthy"):
        LifecycleRecoveryHydrator().hydrate(
            indicator_result=IndicatorRecoveryResult(indicator_engine, ()),
            recovered=RecoveredLifecycle(
                setup,
                signal,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                (transition,),
            ),
            coordinator=_coordinator(strategy, run),
        )


def test_lifecycle_hydration_rejects_strategy_identity_mismatch() -> None:
    strategy = IntradayMomentumV1Strategy(StrategyV1EvaluationConfig())
    reference = RsiMeanReversionV1Strategy(RsiMeanReversionV1Config())
    run, signal, setup, transition = _signal_setup(strategy, "strategy-mismatch")

    with pytest.raises(LifecycleRecoveryError, match="configured strategy identity"):
        LifecycleRecoveryHydrator().hydrate(
            indicator_result=_indicator_result(strategy),
            recovered=RecoveredLifecycle(
                setup,
                signal,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                (transition,),
            ),
            coordinator=_coordinator(reference, run),
        )


def test_lifecycle_hydration_rejects_indicator_identity_mismatch() -> None:
    strategy = IntradayMomentumV1Strategy(StrategyV1EvaluationConfig())
    run, signal, setup, transition = _signal_setup(strategy, "indicator-identity")
    wrong = IndicatorEngine(
        INSTRUMENT,
        "engine-v2",
        requirements=strategy.indicator_requirements,
    )

    with pytest.raises(LifecycleRecoveryError, match="indicator recovery identity"):
        LifecycleRecoveryHydrator().hydrate(
            indicator_result=IndicatorRecoveryReconciler(wrong.state).reconcile(()),
            recovered=RecoveredLifecycle(
                setup,
                signal,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                (transition,),
            ),
            coordinator=_coordinator(strategy, run),
        )


def test_lifecycle_hydration_rejects_indicator_instrument_mismatch() -> None:
    strategy = IntradayMomentumV1Strategy(StrategyV1EvaluationConfig())
    run, signal, setup, transition = _signal_setup(strategy, "indicator-instrument")
    other = IndicatorEngine(
        InstrumentId("NSE:OTHER"),
        "engine-v1",
        requirements=strategy.indicator_requirements,
    )

    with pytest.raises(LifecycleRecoveryError, match="instrument contradicts"):
        LifecycleRecoveryHydrator().hydrate(
            indicator_result=IndicatorRecoveryReconciler(other.state).reconcile(()),
            recovered=RecoveredLifecycle(
                setup,
                signal,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                (transition,),
            ),
            coordinator=_coordinator(strategy, run),
        )


def test_armed_hydration_requires_persisted_signal() -> None:
    strategy = IntradayMomentumV1Strategy(StrategyV1EvaluationConfig())
    run, _signal, setup, transition = _signal_setup(strategy, "missing-signal")

    with pytest.raises(LifecycleRecoveryError, match="requires persisted Signal"):
        LifecycleRecoveryHydrator().hydrate(
            indicator_result=_indicator_result(strategy),
            recovered=RecoveredLifecycle(
                setup,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                (transition,),
            ),
            coordinator=_coordinator(strategy, run),
        )


def test_terminal_or_inactive_recovery_is_not_reopened() -> None:
    strategy = IntradayMomentumV1Strategy(StrategyV1EvaluationConfig())
    run = _run(strategy, "terminal")

    result = LifecycleRecoveryHydrator().hydrate(
        indicator_result=_indicator_result(strategy),
        recovered=RecoveredLifecycle(
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            (),
        ),
        coordinator=_coordinator(strategy, run),
    )

    assert result.snapshot.state is LifecycleState.IDLE


def test_terminal_recovery_rejects_non_idle_coordinator() -> None:
    strategy = IntradayMomentumV1Strategy(StrategyV1EvaluationConfig())
    run, signal, setup, transition = _signal_setup(strategy, "terminal-non-idle")
    coordinator = _coordinator(strategy, run)
    hydrator = LifecycleRecoveryHydrator()
    hydrator.hydrate(
        indicator_result=_indicator_result(strategy),
        recovered=RecoveredLifecycle(
            setup,
            signal,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            (transition,),
        ),
        coordinator=coordinator,
    )

    with pytest.raises(LifecycleRecoveryError, match="fresh IDLE"):
        hydrator.hydrate(
            indicator_result=_indicator_result(strategy),
            recovered=RecoveredLifecycle(
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                (),
            ),
            coordinator=coordinator,
        )
