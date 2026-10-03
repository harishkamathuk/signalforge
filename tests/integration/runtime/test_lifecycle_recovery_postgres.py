from __future__ import annotations

import os
from collections.abc import Iterator
from dataclasses import replace
from datetime import date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from signalforge.config.strategy_v1 import StrategyV1EvaluationConfig
from signalforge.domain.armed import ArmedSetup
from signalforge.domain.audit import StateTransition, TransitionEntityType
from signalforge.domain.execution import EntryIntent, ExecutionMode, Fill, TriggerEvent
from signalforge.domain.ids import InstrumentId, RunId
from signalforge.domain.instruments import TickSizeRule, TickSizeSchedule
from signalforge.domain.market import CandleQuality, CompletedCandle, MarketEvent
from signalforge.domain.money import Price, Quantity
from signalforge.domain.position_outcomes import PositionOpenOutcome, PositionOpenOutcomeType
from signalforge.domain.positions import Position
from signalforge.domain.provenance import RunIdentity
from signalforge.domain.signals import Signal
from signalforge.domain.time import IST, CandleInterval
from signalforge.domain.trades import Trade
from signalforge.persistence.coordinator import PersistenceCoordinator
from signalforge.persistence.models import (
    ArmedSetupRecord,
    EntryIntentRecord,
    FillRecord,
    IndicatorCheckpointRecord,
    PositionOpenOutcomeRecord,
    PositionRecord,
    RunRecord,
    SignalRecord,
    StateTransitionRecord,
    TradeRecord,
    TriggerEventRecord,
)
from signalforge.persistence.repositories import (
    PostgresArmedSetupRepository,
    PostgresIndicatorCheckpointRepository,
    PostgresRunProvenanceRepository,
    PostgresSignalRepository,
    PostgresStateTransitionRepository,
)
from signalforge.runtime.indicator_recovery import IndicatorRecoveryReconciler
from signalforge.runtime.indicators import IndicatorEngine
from signalforge.runtime.lifecycle import LifecycleCoordinator, LifecycleState
from signalforge.runtime.lifecycle_recovery import LifecycleRecoveryHydrator
from signalforge.runtime.recovery import RecoveryBootstrap
from signalforge.runtime.strategy_v1 import IntradayMomentumV1Strategy

INSTRUMENT = InstrumentId("NSE:SF051PG")
AT = datetime(2026, 10, 3, 10, 0, tzinfo=IST)


@pytest.fixture(scope="module")
def postgres_engine() -> Iterator[Engine]:
    database_url = os.environ.get("DATABASE_URL")
    if database_url is None:
        pytest.fail("DATABASE_URL is required")
    engine = sa.create_engine(database_url)
    try:
        yield engine
    finally:
        engine.dispose()


def _schedule() -> TickSizeSchedule:
    return TickSizeSchedule(
        instrument_id=INSTRUMENT,
        rules=(TickSizeRule(Price(Decimal("0.05")), date(2026, 1, 1)),),
    )


def _transition(
    *,
    run: RunIdentity,
    entity: TransitionEntityType,
    entity_id: str,
    before: str,
    after: str,
    cause_type: str,
    cause_id: str,
    occurred_at: datetime,
) -> StateTransition:
    return StateTransition.create(
        entity_type=entity,
        entity_id=entity_id,
        from_state=before,
        to_state=after,
        cause_type=cause_type,
        cause_id=cause_id,
        occurred_at=occurred_at,
        run=run,
    )


def _durable_counts(session: Session) -> dict[str, int]:
    records = (
        RunRecord,
        SignalRecord,
        ArmedSetupRecord,
        TriggerEventRecord,
        EntryIntentRecord,
        FillRecord,
        PositionOpenOutcomeRecord,
        TradeRecord,
        PositionRecord,
        StateTransitionRecord,
        IndicatorCheckpointRecord,
    )
    return {
        record.__tablename__: session.scalar(sa.select(sa.func.count()).select_from(record)) or 0
        for record in records
    }


def test_postgres_open_restart_hydrates_read_only_and_continues_from_frozen_economics(
    postgres_engine: Engine,
) -> None:
    strategy = IntradayMomentumV1Strategy(StrategyV1EvaluationConfig())
    run = RunIdentity(
        run_id=RunId(f"sf051-pg-{uuid4().hex}"),
        strategy=strategy.identity,
        config_id=strategy.config_identity.config_id,
        config_hash=strategy.config_identity.config_hash,
        engine_calculation_version="engine-v1",
    )
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
        raw_trigger=Price(Decimal("101.101")),
        tradable_trigger=Price(Decimal("101.15")),
        signal_low=signal.signal_low,
        armed_at=interval.end,
        valid_until=interval.end + timedelta(minutes=5),
    )
    arm_transition = _transition(
        run=run,
        entity=TransitionEntityType.ARMED_SETUP,
        entity_id=str(signal.signal_id),
        before="none",
        after="armed",
        cause_type="strategy_evaluation",
        cause_id="persisted-evaluation",
        occurred_at=setup.armed_at,
    )
    trigger = TriggerEvent.create(
        signal_id=signal.signal_id,
        instrument_id=INSTRUMENT,
        reference_price=setup.tradable_trigger,
        observed_price=Price(Decimal("101.20")),
        observed_at=setup.armed_at + timedelta(minutes=1),
        run=run,
    )
    triggered = replace(setup)
    triggered.trigger(at=trigger.observed_at)
    trigger_transition = _transition(
        run=run,
        entity=TransitionEntityType.ARMED_SETUP,
        entity_id=str(signal.signal_id),
        before="armed",
        after="triggered",
        cause_type="trigger_event",
        cause_id=str(trigger.trigger_event_id),
        occurred_at=trigger.observed_at,
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
    fill = Fill.create(
        entry_intent_id=intent.entry_intent_id,
        trigger_event_id=trigger.trigger_event_id,
        signal_id=signal.signal_id,
        instrument_id=INSTRUMENT,
        reference_price=trigger.reference_price,
        fill_price=trigger.observed_price,
        quantity=intent.quantity,
        execution_mode=ExecutionMode.PAPER,
        filled_at=trigger.observed_at,
        run=run,
    )
    trade = Trade.open_from_fill(
        entry_fill=fill,
        stop_price=signal.signal_low,
        raw_target_price=Price(Decimal("103.00")),
        tradable_target_price=Price(Decimal("103.00")),
    )
    position = Position.open_from_trade(trade=trade)
    outcome = PositionOpenOutcome.create(
        fill_id=fill.fill_id,
        signal_id=signal.signal_id,
        outcome=PositionOpenOutcomeType.OPENED,
        decided_at=fill.filled_at,
        run=run,
    )
    trade_transition = _transition(
        run=run,
        entity=TransitionEntityType.TRADE,
        entity_id=str(trade.trade_id),
        before="none",
        after="open",
        cause_type="fill",
        cause_id=str(fill.fill_id),
        occurred_at=trade.opened_at,
    )
    position_transition = _transition(
        run=run,
        entity=TransitionEntityType.POSITION,
        entity_id=str(position.position_id),
        before="none",
        after="open",
        cause_type="trade",
        cause_id=str(trade.trade_id),
        occurred_at=position.opened_at,
    )

    indicator_engine = IndicatorEngine(
        INSTRUMENT,
        run.engine_calculation_version,
        requirements=strategy.indicator_requirements,
    )
    indicator_engine.update(
        CompletedCandle(
            instrument_id=INSTRUMENT,
            interval=interval,
            quality=CandleQuality.VALID,
            open=Price(Decimal("100.50")),
            high=Price(Decimal("102.00")),
            low=signal.signal_low,
            close=signal.signal_close,
            volume=1000,
            source="sf051-postgres",
            source_event_count=4,
        )
    )

    with Session(postgres_engine) as session:
        PostgresRunProvenanceRepository(session).add(run)
        PostgresSignalRepository(session).append(signal)
        PostgresArmedSetupRepository(session).upsert(run.run_id, setup)
        PostgresStateTransitionRepository(session).append(arm_transition)
        PostgresIndicatorCheckpointRepository(session).upsert(run, indicator_engine.state)
        session.commit()

    with Session(postgres_engine) as session:
        coordinator = PersistenceCoordinator(session)
        coordinator.persist_trigger_intent(
            trigger=trigger,
            intent=intent,
            setup=triggered,
            setup_transition=trigger_transition,
        )
        coordinator.persist_opened_entry(
            fill=fill,
            outcome=outcome,
            trade=trade,
            position=position,
            trade_transition=trade_transition,
            position_transition=position_transition,
        )

    with Session(postgres_engine) as session:
        before = _durable_counts(session)
        recovered = RecoveryBootstrap().inspect(
            session=session,
            requested_run=run,
            instrument_id=INSTRUMENT,
            indicator_requirements=strategy.indicator_requirements,
        )
    assert recovered.indicator_state is not None
    indicator_result = IndicatorRecoveryReconciler(recovered.indicator_state).reconcile(())

    coordinator = LifecycleCoordinator(
        run=run,
        tick_schedule=_schedule(),
        quantity=Quantity(10),
        strategy=strategy,
    )
    hydrated = LifecycleRecoveryHydrator().hydrate(
        indicator_result=indicator_result,
        recovered=recovered.lifecycle,
        coordinator=coordinator,
    )

    assert hydrated.snapshot.state is LifecycleState.OPEN
    assert hydrated.snapshot.execution is not None
    assert hydrated.snapshot.execution.entry_intent == intent
    assert hydrated.snapshot.execution.fill == fill
    assert hydrated.snapshot.open_result is not None
    assert hydrated.snapshot.open_result.trade is recovered.lifecycle.trade
    assert hydrated.snapshot.open_result.position is recovered.lifecycle.position
    assert hydrated.snapshot.open_result.trade is not None
    assert hydrated.snapshot.open_result.trade.trade_id == trade.trade_id
    assert hydrated.snapshot.open_result.trade.entry_fill_id == trade.entry_fill_id
    assert hydrated.snapshot.open_result.trade.entry_price == fill.fill_price
    assert hydrated.snapshot.open_result.trade.stop_price == signal.signal_low
    assert hydrated.snapshot.open_result.trade.raw_target_price == Price(Decimal("103.00"))
    assert hydrated.snapshot.open_result.trade.tradable_target_price == Price(Decimal("103.00"))
    assert hydrated.snapshot.open_result.trade.risk_per_share == trade.risk_per_share
    assert hydrated.snapshot.open_result.trade.quantity == trade.quantity
    assert hydrated.snapshot.open_result.position is not None
    assert hydrated.snapshot.open_result.position.position_id == position.position_id
    assert hydrated.snapshot.open_result.position.trade_id == trade.trade_id
    assert hydrated.snapshot.open_result.position.quantity == position.quantity
    assert (
        hydrated.snapshot.open_result.position.average_entry_price
        == position.average_entry_price
    )

    with Session(postgres_engine) as session:
        assert _durable_counts(session) == before

    exit_at = fill.filled_at + timedelta(minutes=1)
    exit_event = MarketEvent(
        instrument_id=INSTRUMENT,
        exchange_timestamp=exit_at,
        received_timestamp=exit_at + timedelta(milliseconds=1),
        price=Price(Decimal("103.10")),
        quantity=1,
        source="sf051-postgres",
        source_event_id="sf051-target",
    )
    first = coordinator.process_market_event(exit_event)
    second = coordinator.process_market_event(exit_event)

    assert first.state is LifecycleState.CLOSED
    assert first.exit is not None
    assert second.exit is first.exit
