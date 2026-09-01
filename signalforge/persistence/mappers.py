"""Explicit Data Mappers between domain/runtime objects and SQLAlchemy records."""

from __future__ import annotations

from signalforge.domain.armed import ArmedSetup, ArmedSetupState, ExpiryReason
from signalforge.domain.audit import StateTransition, TransitionEntityType
from signalforge.domain.execution import EntryIntent, ExecutionMode, Fill, TriggerEvent
from signalforge.domain.exits import Exit, ExitReason
from signalforge.domain.ids import (
    ConfigId,
    EntryIntentId,
    ExitId,
    FillId,
    InstrumentId,
    PositionId,
    RunId,
    SignalId,
    StateTransitionId,
    TradeId,
    TriggerEventId,
)
from signalforge.domain.money import Price, Quantity
from signalforge.domain.positions import Position, PositionState
from signalforge.domain.provenance import RunIdentity, StrategyIdentity
from signalforge.domain.signals import Signal
from signalforge.domain.strategy import (
    DecisionReason,
    MomentumResult,
    SetupResult,
    StrategyEvaluation,
    TrendResult,
)
from signalforge.domain.time import CandleInterval
from signalforge.domain.trades import Trade, TradeState
from signalforge.persistence.models import (
    ArmedSetupRecord,
    EntryIntentRecord,
    ExitRecord,
    FillRecord,
    PositionRecord,
    RunRecord,
    SignalRecord,
    StateTransitionRecord,
    StrategyConfigRecord,
    StrategyEvaluationRecord,
    TradeRecord,
    TriggerEventRecord,
)


def strategy_config_record_from_domain(run: RunIdentity) -> StrategyConfigRecord:
    return StrategyConfigRecord(
        config_id=str(run.config_id),
        strategy_id=run.strategy.strategy_id,
        strategy_version=run.strategy.strategy_version,
        config_hash=run.config_hash,
    )


def run_record_from_domain(run: RunIdentity) -> RunRecord:
    return RunRecord(
        run_id=str(run.run_id),
        config_id=str(run.config_id),
        engine_calculation_version=run.engine_calculation_version,
    )


def run_identity_from_records(
    run: RunRecord,
    config: StrategyConfigRecord,
) -> RunIdentity:
    if run.config_id != config.config_id:
        raise ValueError("RunRecord and StrategyConfigRecord config identities do not match")
    return RunIdentity(
        run_id=RunId(run.run_id),
        strategy=StrategyIdentity(config.strategy_id, config.strategy_version),
        config_id=ConfigId(config.config_id),
        config_hash=config.config_hash,
        engine_calculation_version=run.engine_calculation_version,
    )


def strategy_evaluation_record_from_domain(
    run_id: RunId,
    evaluation: StrategyEvaluation,
) -> StrategyEvaluationRecord:
    return StrategyEvaluationRecord(
        run_id=str(run_id),
        instrument_id=str(evaluation.instrument_id),
        interval_start=evaluation.interval.start,
        interval_end=evaluation.interval.end,
        trend_passed=evaluation.trend.passed,
        momentum_passed=evaluation.momentum.passed,
        rsi_passed=evaluation.momentum.rsi_passed,
        adx_passed=evaluation.momentum.adx_passed,
        macd_signal_positive=evaluation.momentum.macd_signal_positive,
        setup_passed=evaluation.setup.passed,
        qualified=evaluation.qualified,
        actionable=evaluation.actionable,
        reasons=[reason.value for reason in evaluation.reasons],
    )


def strategy_evaluation_from_record(record: StrategyEvaluationRecord) -> StrategyEvaluation:
    return StrategyEvaluation(
        instrument_id=InstrumentId(record.instrument_id),
        interval=CandleInterval(record.interval_start, record.interval_end),
        trend=TrendResult(record.trend_passed),
        momentum=MomentumResult(
            passed=record.momentum_passed,
            rsi_passed=record.rsi_passed,
            adx_passed=record.adx_passed,
            macd_signal_positive=record.macd_signal_positive,
        ),
        setup=SetupResult(record.setup_passed),
        qualified=record.qualified,
        actionable=record.actionable,
        reasons=tuple(DecisionReason(value) for value in record.reasons),
    )


def signal_record_from_domain(signal: Signal) -> SignalRecord:
    return SignalRecord(
        signal_id=str(signal.signal_id),
        run_id=str(signal.run.run_id),
        instrument_id=str(signal.instrument_id),
        interval_start=signal.interval.start,
        interval_end=signal.interval.end,
        signal_close=signal.signal_close.value,
        signal_low=signal.signal_low.value,
        created_at=signal.created_at,
    )


def signal_from_record(record: SignalRecord, run: RunIdentity) -> Signal:
    return Signal(
        signal_id=SignalId(record.signal_id),
        instrument_id=InstrumentId(record.instrument_id),
        interval=CandleInterval(record.interval_start, record.interval_end),
        signal_close=Price(record.signal_close),
        signal_low=Price(record.signal_low),
        run=run,
        created_at=record.created_at,
    )


def armed_setup_record_from_domain(run_id: RunId, setup: ArmedSetup) -> ArmedSetupRecord:
    return ArmedSetupRecord(
        signal_id=str(setup.signal_id),
        run_id=str(run_id),
        raw_trigger=setup.raw_trigger.value,
        tradable_trigger=setup.tradable_trigger.value,
        signal_low=setup.signal_low.value,
        armed_at=setup.armed_at,
        valid_until=setup.valid_until,
        state=setup.state.value,
        terminal_at=setup.terminal_at,
        expiry_reason=None if setup.expiry_reason is None else setup.expiry_reason.value,
    )


def armed_setup_from_record(record: ArmedSetupRecord) -> ArmedSetup:
    return ArmedSetup(
        signal_id=SignalId(record.signal_id),
        raw_trigger=Price(record.raw_trigger),
        tradable_trigger=Price(record.tradable_trigger),
        signal_low=Price(record.signal_low),
        armed_at=record.armed_at,
        valid_until=record.valid_until,
        state=ArmedSetupState(record.state),
        terminal_at=record.terminal_at,
        expiry_reason=None if record.expiry_reason is None else ExpiryReason(record.expiry_reason),
    )


def trigger_event_record_from_domain(event: TriggerEvent) -> TriggerEventRecord:
    return TriggerEventRecord(
        trigger_event_id=str(event.trigger_event_id),
        signal_id=str(event.signal_id),
        run_id=str(event.run.run_id),
        instrument_id=str(event.instrument_id),
        reference_price=event.reference_price.value,
        observed_price=event.observed_price.value,
        observed_at=event.observed_at,
    )


def trigger_event_from_record(record: TriggerEventRecord, run: RunIdentity) -> TriggerEvent:
    return TriggerEvent(
        trigger_event_id=TriggerEventId(record.trigger_event_id),
        signal_id=SignalId(record.signal_id),
        instrument_id=InstrumentId(record.instrument_id),
        reference_price=Price(record.reference_price),
        observed_price=Price(record.observed_price),
        observed_at=record.observed_at,
        run=run,
    )


def entry_intent_record_from_domain(intent: EntryIntent) -> EntryIntentRecord:
    return EntryIntentRecord(
        entry_intent_id=str(intent.entry_intent_id),
        trigger_event_id=str(intent.trigger_event_id),
        signal_id=str(intent.signal_id),
        run_id=str(intent.run.run_id),
        instrument_id=str(intent.instrument_id),
        reference_price=intent.reference_price.value,
        quantity=intent.quantity.value,
        execution_mode=intent.execution_mode.value,
        created_at=intent.created_at,
    )


def entry_intent_from_record(record: EntryIntentRecord, run: RunIdentity) -> EntryIntent:
    return EntryIntent(
        entry_intent_id=EntryIntentId(record.entry_intent_id),
        trigger_event_id=TriggerEventId(record.trigger_event_id),
        signal_id=SignalId(record.signal_id),
        instrument_id=InstrumentId(record.instrument_id),
        reference_price=Price(record.reference_price),
        quantity=Quantity(record.quantity),
        execution_mode=ExecutionMode(record.execution_mode),
        created_at=record.created_at,
        run=run,
    )


def fill_record_from_domain(fill: Fill) -> FillRecord:
    return FillRecord(
        fill_id=str(fill.fill_id),
        entry_intent_id=str(fill.entry_intent_id),
        trigger_event_id=str(fill.trigger_event_id),
        signal_id=str(fill.signal_id),
        run_id=str(fill.run.run_id),
        instrument_id=str(fill.instrument_id),
        reference_price=fill.reference_price.value,
        fill_price=fill.fill_price.value,
        quantity=fill.quantity.value,
        execution_mode=fill.execution_mode.value,
        filled_at=fill.filled_at,
    )


def fill_from_record(record: FillRecord, run: RunIdentity) -> Fill:
    return Fill(
        fill_id=FillId(record.fill_id),
        entry_intent_id=EntryIntentId(record.entry_intent_id),
        trigger_event_id=TriggerEventId(record.trigger_event_id),
        signal_id=SignalId(record.signal_id),
        instrument_id=InstrumentId(record.instrument_id),
        reference_price=Price(record.reference_price),
        fill_price=Price(record.fill_price),
        quantity=Quantity(record.quantity),
        execution_mode=ExecutionMode(record.execution_mode),
        filled_at=record.filled_at,
        run=run,
    )


def trade_record_from_domain(trade: Trade) -> TradeRecord:
    return TradeRecord(
        trade_id=str(trade.trade_id),
        entry_fill_id=str(trade.entry_fill_id),
        signal_id=str(trade.signal_id),
        run_id=str(trade.run.run_id),
        instrument_id=str(trade.instrument_id),
        entry_price=trade.entry_price.value,
        stop_price=trade.stop_price.value,
        raw_target_price=trade.raw_target_price.value,
        tradable_target_price=trade.tradable_target_price.value,
        risk_per_share=trade.risk_per_share.value,
        quantity=trade.quantity.value,
        opened_at=trade.opened_at,
        state=trade.state.value,
        closed_at=trade.closed_at,
        exit_id=None if trade.exit_id is None else str(trade.exit_id),
    )


def trade_from_record(record: TradeRecord, run: RunIdentity) -> Trade:
    return Trade(
        trade_id=TradeId(record.trade_id),
        entry_fill_id=FillId(record.entry_fill_id),
        signal_id=SignalId(record.signal_id),
        instrument_id=InstrumentId(record.instrument_id),
        entry_price=Price(record.entry_price),
        stop_price=Price(record.stop_price),
        raw_target_price=Price(record.raw_target_price),
        tradable_target_price=Price(record.tradable_target_price),
        risk_per_share=Price(record.risk_per_share),
        quantity=Quantity(record.quantity),
        opened_at=record.opened_at,
        run=run,
        state=TradeState(record.state),
        closed_at=record.closed_at,
        exit_id=None if record.exit_id is None else ExitId(record.exit_id),
    )


def position_record_from_domain(position: Position) -> PositionRecord:
    return PositionRecord(
        position_id=str(position.position_id),
        trade_id=str(position.trade_id),
        run_id=str(position.run.run_id),
        instrument_id=str(position.instrument_id),
        quantity=position.quantity.value,
        average_entry_price=position.average_entry_price.value,
        opened_at=position.opened_at,
        state=position.state.value,
        closed_at=position.closed_at,
    )


def position_from_record(record: PositionRecord, run: RunIdentity) -> Position:
    return Position(
        position_id=PositionId(record.position_id),
        trade_id=TradeId(record.trade_id),
        instrument_id=InstrumentId(record.instrument_id),
        quantity=Quantity(record.quantity),
        average_entry_price=Price(record.average_entry_price),
        opened_at=record.opened_at,
        run=run,
        state=PositionState(record.state),
        closed_at=record.closed_at,
    )


def exit_record_from_domain(exit_fact: Exit) -> ExitRecord:
    return ExitRecord(
        exit_id=str(exit_fact.exit_id),
        exit_fill_id=str(exit_fact.exit_fill_id),
        trade_id=str(exit_fact.trade_id),
        position_id=str(exit_fact.position_id),
        run_id=str(exit_fact.run.run_id),
        instrument_id=str(exit_fact.instrument_id),
        reason=exit_fact.reason.value,
        reference_price=exit_fact.reference_price.value,
        fill_price=exit_fact.fill_price.value,
        quantity=exit_fact.quantity.value,
        execution_mode=exit_fact.execution_mode.value,
        exited_at=exit_fact.exited_at,
        realised_pnl=exit_fact.realised_pnl,
        realised_r=exit_fact.realised_r,
    )


def exit_from_record(record: ExitRecord, run: RunIdentity) -> Exit:
    return Exit(
        exit_id=ExitId(record.exit_id),
        exit_fill_id=FillId(record.exit_fill_id),
        trade_id=TradeId(record.trade_id),
        position_id=PositionId(record.position_id),
        instrument_id=InstrumentId(record.instrument_id),
        reason=ExitReason(record.reason),
        reference_price=Price(record.reference_price),
        fill_price=Price(record.fill_price),
        quantity=Quantity(record.quantity),
        execution_mode=ExecutionMode(record.execution_mode),
        exited_at=record.exited_at,
        realised_pnl=record.realised_pnl,
        realised_r=record.realised_r,
        run=run,
    )


def state_transition_record_from_domain(transition: StateTransition) -> StateTransitionRecord:
    return StateTransitionRecord(
        transition_id=str(transition.transition_id),
        run_id=str(transition.run.run_id),
        entity_type=transition.entity_type.value,
        entity_id=transition.entity_id,
        from_state=transition.from_state,
        to_state=transition.to_state,
        cause_type=transition.cause_type,
        cause_id=transition.cause_id,
        occurred_at=transition.occurred_at,
    )


def state_transition_from_record(
    record: StateTransitionRecord,
    run: RunIdentity,
) -> StateTransition:
    return StateTransition(
        transition_id=StateTransitionId(record.transition_id),
        entity_type=TransitionEntityType(record.entity_type),
        entity_id=record.entity_id,
        from_state=record.from_state,
        to_state=record.to_state,
        cause_type=record.cause_type,
        cause_id=record.cause_id,
        occurred_at=record.occurred_at,
        run=run,
    )
