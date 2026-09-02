from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

from signalforge.domain.armed import ArmedSetup
from signalforge.domain.audit import StateTransition, TransitionEntityType
from signalforge.domain.execution import EntryIntent, ExecutionMode, Fill, TriggerEvent
from signalforge.domain.exits import Exit, ExitReason
from signalforge.domain.ids import ConfigId, InstrumentId, RunId
from signalforge.domain.money import Price, Quantity
from signalforge.domain.position_outcomes import PositionOpenOutcome, PositionOpenOutcomeType
from signalforge.domain.positions import Position
from signalforge.domain.provenance import RunIdentity, StrategyIdentity
from signalforge.domain.signals import Signal
from signalforge.domain.strategy import (
    DecisionReason,
    MomentumResult,
    SetupResult,
    StrategyEvaluation,
    TrendResult,
)
from signalforge.domain.time import IST, CandleInterval
from signalforge.domain.trades import Trade
from signalforge.persistence.mappers import (
    armed_setup_from_record,
    armed_setup_record_from_domain,
    entry_intent_from_record,
    entry_intent_record_from_domain,
    exit_from_record,
    exit_record_from_domain,
    fill_from_record,
    fill_record_from_domain,
    position_from_record,
    position_open_outcome_from_record,
    position_open_outcome_record_from_domain,
    position_record_from_domain,
    run_identity_from_records,
    run_record_from_domain,
    signal_from_record,
    signal_record_from_domain,
    state_transition_from_record,
    state_transition_record_from_domain,
    strategy_config_record_from_domain,
    strategy_evaluation_from_record,
    strategy_evaluation_record_from_domain,
    trade_from_record,
    trade_record_from_domain,
    trigger_event_from_record,
    trigger_event_record_from_domain,
)

INSTRUMENT = InstrumentId("NSE:TEST")
AT = datetime(2026, 8, 31, 10, 0, tzinfo=IST)


def _run() -> RunIdentity:
    return RunIdentity(
        run_id=RunId("run-map"),
        strategy=StrategyIdentity("intraday_momentum_v1", "1.0.0"),
        config_id=ConfigId("config-map"),
        config_hash="hash-map",
        engine_calculation_version="engine-v1",
    )


def _record_values(record: object) -> dict[str, object]:
    table = type(record).__table__
    return {column.name: getattr(record, column.name) for column in table.columns}


def test_provenance_and_evaluation_mappers_round_trip() -> None:
    run = _run()
    assert (
        run_identity_from_records(
            run_record_from_domain(run), strategy_config_record_from_domain(run)
        )
        == run
    )

    evaluation = StrategyEvaluation(
        instrument_id=INSTRUMENT,
        interval=CandleInterval.five_minutes(AT),
        trend=TrendResult(True),
        momentum=MomentumResult(True, True, True, None),
        setup=SetupResult(True),
        qualified=True,
        actionable=True,
        reasons=(DecisionReason.QUALIFIED, DecisionReason.ACTIONABLE),
    )
    record = strategy_evaluation_record_from_domain(run.run_id, evaluation)
    restored = strategy_evaluation_from_record(record)
    assert _record_values(strategy_evaluation_record_from_domain(run.run_id, restored)) == (
        _record_values(record)
    )


def test_business_fact_and_current_state_mappers_round_trip() -> None:
    run = _run()
    interval = CandleInterval.five_minutes(AT)
    signal = Signal.create(
        instrument_id=INSTRUMENT,
        interval=interval,
        signal_close=Price(Decimal("101.00")),
        signal_low=Price(Decimal("100.00")),
        run=run,
        created_at=interval.end,
    )
    signal_record = signal_record_from_domain(signal)
    restored_signal = signal_from_record(signal_record, run)
    assert _record_values(signal_record_from_domain(restored_signal)) == _record_values(
        signal_record
    )

    setup = ArmedSetup(
        signal_id=signal.signal_id,
        raw_trigger=Price(Decimal("101.101")),
        tradable_trigger=Price(Decimal("101.15")),
        signal_low=signal.signal_low,
        armed_at=interval.end,
        valid_until=interval.end + timedelta(minutes=5),
    )
    setup_record = armed_setup_record_from_domain(run.run_id, setup)
    restored_setup = armed_setup_from_record(setup_record)
    assert _record_values(armed_setup_record_from_domain(run.run_id, restored_setup)) == (
        _record_values(setup_record)
    )

    trigger = TriggerEvent.create(
        signal_id=signal.signal_id,
        instrument_id=INSTRUMENT,
        reference_price=setup.tradable_trigger,
        observed_price=Price(Decimal("101.20")),
        observed_at=interval.end + timedelta(minutes=1),
        run=run,
    )
    trigger_record = trigger_event_record_from_domain(trigger)
    restored_trigger = trigger_event_from_record(trigger_record, run)
    assert _record_values(trigger_event_record_from_domain(restored_trigger)) == _record_values(
        trigger_record
    )

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
    intent_record = entry_intent_record_from_domain(intent)
    restored_intent = entry_intent_from_record(intent_record, run)
    assert _record_values(entry_intent_record_from_domain(restored_intent)) == _record_values(
        intent_record
    )

    fill = Fill.create(
        entry_intent_id=intent.entry_intent_id,
        trigger_event_id=trigger.trigger_event_id,
        signal_id=signal.signal_id,
        instrument_id=INSTRUMENT,
        reference_price=trigger.reference_price,
        fill_price=Price(Decimal("101.20")),
        quantity=intent.quantity,
        execution_mode=intent.execution_mode,
        filled_at=trigger.observed_at,
        run=run,
    )
    fill_record = fill_record_from_domain(fill)
    restored_fill = fill_from_record(fill_record, run)
    assert _record_values(fill_record_from_domain(restored_fill)) == _record_values(fill_record)

    outcome = PositionOpenOutcome.create(
        fill_id=fill.fill_id,
        signal_id=fill.signal_id,
        outcome=PositionOpenOutcomeType.OPENED,
        decided_at=fill.filled_at,
        run=run,
    )
    outcome_record = position_open_outcome_record_from_domain(outcome)
    restored_outcome = position_open_outcome_from_record(outcome_record, run)
    assert restored_outcome.decided_at.tzinfo is not None
    assert _record_values(position_open_outcome_record_from_domain(restored_outcome)) == (
        _record_values(outcome_record)
    )

    trade = Trade.open_from_fill(
        entry_fill=fill,
        stop_price=signal.signal_low,
        target_tick_size=Price(Decimal("0.05")),
    )
    position = Position.open_from_trade(trade=trade)
    exit_fact = Exit.create(
        trade=trade,
        position=position,
        exit_fill_id=fill.fill_id,
        reason=ExitReason.TARGET,
        reference_price=trade.tradable_target_price,
        fill_price=Price(Decimal("103.05")),
        quantity=trade.quantity,
        execution_mode=ExecutionMode.PAPER,
        exited_at=trigger.observed_at + timedelta(minutes=5),
    )

    exit_record = exit_record_from_domain(exit_fact)
    restored_exit = exit_from_record(exit_record, run)
    assert _record_values(exit_record_from_domain(restored_exit)) == _record_values(exit_record)

    trade.close(exit_id=exit_fact.exit_id, at=exit_fact.exited_at)
    position.close(at=exit_fact.exited_at)
    trade_record = trade_record_from_domain(trade)
    position_record = position_record_from_domain(position)
    assert _record_values(trade_record_from_domain(trade_from_record(trade_record, run))) == (
        _record_values(trade_record)
    )
    assert _record_values(
        position_record_from_domain(position_from_record(position_record, run))
    ) == _record_values(position_record)

    transition = StateTransition.create(
        entity_type=TransitionEntityType.TRADE,
        entity_id=str(trade.trade_id),
        from_state="open",
        to_state="closed",
        cause_type="exit",
        cause_id=str(exit_fact.exit_id),
        occurred_at=exit_fact.exited_at,
        run=run,
    )
    transition_record = state_transition_record_from_domain(transition)
    restored_transition = state_transition_from_record(transition_record, run)
    assert _record_values(state_transition_record_from_domain(restored_transition)) == (
        _record_values(transition_record)
    )
