from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from signalforge.domain.armed import ArmedSetup, ArmedSetupState
from signalforge.domain.audit import StateTransition, TransitionEntityType
from signalforge.domain.execution import EntryIntent, ExecutionMode, Fill, TriggerEvent
from signalforge.domain.exits import Exit, ExitReason
from signalforge.domain.ids import ConfigId, FillId, InstrumentId, RunId
from signalforge.domain.money import Price, Quantity
from signalforge.domain.positions import Position, PositionState
from signalforge.domain.provenance import RunIdentity, StrategyIdentity
from signalforge.domain.signals import Signal
from signalforge.domain.states import InvalidStateTransition
from signalforge.domain.strategy import (
    DecisionReason,
    MomentumResult,
    SetupResult,
    StrategyEvaluation,
    TrendResult,
)
from signalforge.domain.time import CandleInterval
from signalforge.domain.trades import Trade, TradeState

IST = ZoneInfo("Asia/Kolkata")


def test_complete_m1_domain_vertical() -> None:
    run = RunIdentity(
        run_id=RunId("run-m1-vertical"),
        strategy=StrategyIdentity("intraday_momentum_v1", "1.0.0"),
        config_id=ConfigId("config-m1-vertical"),
        config_hash="m1-vertical-config-hash",
        engine_calculation_version="engine-v1",
    )
    instrument_id = InstrumentId("NSE:TEST")
    signal_interval = CandleInterval.five_minutes(
        datetime(2026, 8, 28, 10, 0, tzinfo=IST)
    )

    evaluation = StrategyEvaluation(
        instrument_id=instrument_id,
        interval=signal_interval,
        trend=TrendResult(passed=True),
        momentum=MomentumResult(
            passed=True,
            rsi_passed=True,
            adx_passed=True,
            macd_signal_positive=False,
        ),
        setup=SetupResult(passed=True),
        qualified=True,
        actionable=True,
        reasons=(DecisionReason.QUALIFIED, DecisionReason.ACTIONABLE),
    )
    assert evaluation.qualified is True
    assert evaluation.actionable is True

    signal = Signal.create(
        instrument_id=instrument_id,
        interval=signal_interval,
        signal_close=Price(Decimal("100.00")),
        signal_low=Price(Decimal("98.00")),
        run=run,
        created_at=datetime(2026, 8, 28, 10, 5, tzinfo=IST),
    )
    assert signal.interval == evaluation.interval
    assert signal.instrument_id == evaluation.instrument_id

    setup = ArmedSetup(
        signal_id=signal.signal_id,
        raw_trigger=Price(Decimal("100.10000")),
        tradable_trigger=Price(Decimal("100.10")),
        signal_low=signal.signal_low,
        armed_at=datetime(2026, 8, 28, 10, 5, tzinfo=IST),
        valid_until=datetime(2026, 8, 28, 10, 10, tzinfo=IST),
    )
    assert setup.state is ArmedSetupState.ARMED

    trigger = TriggerEvent.create(
        signal_id=signal.signal_id,
        instrument_id=instrument_id,
        reference_price=setup.tradable_trigger,
        observed_price=Price(Decimal("100.15")),
        observed_at=datetime(2026, 8, 28, 10, 6, tzinfo=IST),
        run=run,
    )
    setup.trigger(at=trigger.observed_at)
    assert setup.state is ArmedSetupState.TRIGGERED

    armed_transition = StateTransition.create(
        entity_type=TransitionEntityType.ARMED_SETUP,
        entity_id=str(signal.signal_id),
        from_state=ArmedSetupState.ARMED.value,
        to_state=ArmedSetupState.TRIGGERED.value,
        cause_type="trigger_event",
        cause_id=str(trigger.trigger_event_id),
        occurred_at=trigger.observed_at,
        run=run,
    )
    assert armed_transition.to_state == ArmedSetupState.TRIGGERED.value

    intent = EntryIntent.create(
        trigger_event_id=trigger.trigger_event_id,
        signal_id=signal.signal_id,
        instrument_id=instrument_id,
        reference_price=setup.tradable_trigger,
        quantity=Quantity(10),
        execution_mode=ExecutionMode.PAPER,
        created_at=datetime(2026, 8, 28, 10, 6, 1, tzinfo=IST),
        run=run,
    )
    fill = Fill.create(
        entry_intent_id=intent.entry_intent_id,
        trigger_event_id=trigger.trigger_event_id,
        signal_id=signal.signal_id,
        instrument_id=instrument_id,
        reference_price=intent.reference_price,
        fill_price=Price(Decimal("100.20")),
        quantity=intent.quantity,
        execution_mode=intent.execution_mode,
        filled_at=datetime(2026, 8, 28, 10, 6, 2, tzinfo=IST),
        run=run,
    )
    assert fill.fill_price != trigger.reference_price

    trade = Trade.open_from_fill(
        entry_fill=fill,
        stop_price=signal.signal_low,
        target_tick_size=Price(Decimal("0.05")),
    )
    position = Position.open_from_trade(trade=trade)

    assert trade.state is TradeState.OPEN
    assert position.state is PositionState.OPEN
    assert trade.trade_id != position.position_id
    assert position.trade_id == trade.trade_id
    assert trade.entry_price == fill.fill_price
    assert trade.risk_per_share == Price(Decimal("2.20"))
    assert trade.raw_target_price == Price(Decimal("103.500"))
    assert trade.tradable_target_price == Price(Decimal("103.50"))

    exit_fact = Exit.create(
        trade=trade,
        position=position,
        exit_fill_id=FillId("exit-fill-m1-vertical"),
        reason=ExitReason.TARGET,
        reference_price=trade.tradable_target_price,
        fill_price=Price(Decimal("103.55")),
        quantity=trade.quantity,
        execution_mode=ExecutionMode.PAPER,
        exited_at=datetime(2026, 8, 28, 10, 30, tzinfo=IST),
    )
    assert exit_fact.realised_pnl == Decimal("33.50")
    assert exit_fact.realised_r == Decimal("3.35") / Decimal("2.20")

    trade.close(exit_id=exit_fact.exit_id, at=exit_fact.exited_at)
    position.close(at=exit_fact.exited_at)

    trade_transition = StateTransition.create(
        entity_type=TransitionEntityType.TRADE,
        entity_id=str(trade.trade_id),
        from_state=TradeState.OPEN.value,
        to_state=TradeState.CLOSED.value,
        cause_type="exit",
        cause_id=str(exit_fact.exit_id),
        occurred_at=exit_fact.exited_at,
        run=run,
    )
    position_transition = StateTransition.create(
        entity_type=TransitionEntityType.POSITION,
        entity_id=str(position.position_id),
        from_state=PositionState.OPEN.value,
        to_state=PositionState.CLOSED.value,
        cause_type="exit",
        cause_id=str(exit_fact.exit_id),
        occurred_at=exit_fact.exited_at,
        run=run,
    )

    assert trade.state is TradeState.CLOSED
    assert position.state is PositionState.CLOSED
    assert trade.exit_id == exit_fact.exit_id
    assert trade_transition.cause_id == position_transition.cause_id

    with pytest.raises(InvalidStateTransition):
        setup.trigger(at=trigger.observed_at)
    with pytest.raises(InvalidStateTransition):
        trade.close(exit_id=exit_fact.exit_id, at=exit_fact.exited_at)
    with pytest.raises(InvalidStateTransition):
        position.close(at=exit_fact.exited_at)
