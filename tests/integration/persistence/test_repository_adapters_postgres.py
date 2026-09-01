from __future__ import annotations

import os
from collections.abc import Iterator
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
import sqlalchemy as sa
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from signalforge.domain.audit import StateTransition, TransitionEntityType
from signalforge.domain.execution import EntryIntent, ExecutionMode, Fill, TriggerEvent
from signalforge.domain.exits import Exit, ExitReason
from signalforge.domain.ids import ConfigId, FillId, InstrumentId, RunId
from signalforge.domain.money import Price, Quantity
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
from signalforge.persistence.errors import ContradictoryFactError
from signalforge.persistence.mappers import (
    position_record_from_domain,
    trade_record_from_domain,
)
from signalforge.persistence.models import RunRecord, StrategyConfigRecord
from signalforge.persistence.repositories import (
    PostgresEntryIntentRepository,
    PostgresExitRepository,
    PostgresFillRepository,
    PostgresRunProvenanceRepository,
    PostgresSignalRepository,
    PostgresStateTransitionRepository,
    PostgresStrategyEvaluationRepository,
    PostgresTriggerEventRepository,
)

AT = datetime(2026, 9, 1, 10, 0, tzinfo=IST)
INSTRUMENT = InstrumentId("NSE:SF045B")


@pytest.fixture(scope="module")
def postgres_engine() -> Iterator[Engine]:
    database_url = os.environ.get("DATABASE_URL")
    if database_url is None:
        pytest.fail("DATABASE_URL is required for SF-045B PostgreSQL integration tests")
    engine = sa.create_engine(database_url)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def session(postgres_engine: Engine) -> Iterator[Session]:
    with Session(postgres_engine) as caller_session:
        try:
            yield caller_session
        finally:
            caller_session.rollback()


@dataclass(frozen=True, slots=True)
class Facts:
    run: RunIdentity
    evaluation: StrategyEvaluation
    signal: Signal
    trigger: TriggerEvent
    intent: EntryIntent
    fill: Fill
    trade: Trade
    position: Position
    exit_fact: Exit
    transition: StateTransition


def facts(suffix: str = "base", *, at: datetime = AT) -> Facts:
    run = RunIdentity(
        run_id=RunId(f"sf045b-run-{suffix}"),
        strategy=StrategyIdentity("intraday_momentum_v1", "1.0.0"),
        config_id=ConfigId(f"sf045b-config-{suffix}"),
        config_hash=f"sf045b-hash-{suffix}",
        engine_calculation_version="engine-v1",
    )
    interval = CandleInterval.five_minutes(at)
    evaluation = StrategyEvaluation(
        instrument_id=INSTRUMENT,
        interval=interval,
        trend=TrendResult(True),
        momentum=MomentumResult(True, True, True, None),
        setup=SetupResult(True),
        qualified=True,
        actionable=True,
        reasons=(DecisionReason.QUALIFIED, DecisionReason.ACTIONABLE),
    )
    signal = Signal.create(
        instrument_id=INSTRUMENT,
        interval=interval,
        signal_close=Price(Decimal("101.00")),
        signal_low=Price(Decimal("100.00")),
        run=run,
        created_at=interval.end,
    )
    trigger = TriggerEvent.create(
        signal_id=signal.signal_id,
        instrument_id=INSTRUMENT,
        reference_price=Price(Decimal("101.15")),
        observed_price=Price(Decimal("101.20")),
        observed_at=interval.end + timedelta(minutes=1),
        run=run,
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
        fill_price=Price(Decimal("101.20")),
        quantity=intent.quantity,
        execution_mode=intent.execution_mode,
        filled_at=trigger.observed_at,
        run=run,
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
        exit_fill_id=FillId(f"sf045b-exit-fill-{suffix}"),
        reason=ExitReason.TARGET,
        reference_price=trade.tradable_target_price,
        fill_price=Price(Decimal("103.123456789012345678")),
        quantity=trade.quantity,
        execution_mode=ExecutionMode.PAPER,
        exited_at=fill.filled_at + timedelta(minutes=5),
    )
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
    return Facts(
        run,
        evaluation,
        signal,
        trigger,
        intent,
        fill,
        trade,
        position,
        exit_fact,
        transition,
    )


def persist_graph(session: Session, value: Facts) -> None:
    assert PostgresRunProvenanceRepository(session).add(value.run) == value.run
    assert (
        PostgresStrategyEvaluationRepository(session).append(
            value.run.run_id, value.evaluation
        )
        == value.evaluation
    )
    assert PostgresSignalRepository(session).append(value.signal) == value.signal
    assert PostgresTriggerEventRepository(session).append(value.trigger) == value.trigger
    assert PostgresEntryIntentRepository(session).append(value.intent) == value.intent
    assert PostgresFillRepository(session).append(value.fill) == value.fill
    session.add(trade_record_from_domain(value.trade))
    session.flush()
    session.add(position_record_from_domain(value.position))
    session.flush()
    assert PostgresExitRepository(session).append(value.exit_fact) == value.exit_fact
    assert (
        PostgresStateTransitionRepository(session).append(value.transition)
        == value.transition
    )


def test_all_immutable_repositories_round_trip_and_retry_exactly(session: Session) -> None:
    value = facts()
    persist_graph(session, value)

    provenance = PostgresRunProvenanceRepository(session)
    evaluations = PostgresStrategyEvaluationRepository(session)
    signals = PostgresSignalRepository(session)
    triggers = PostgresTriggerEventRepository(session)
    intents = PostgresEntryIntentRepository(session)
    fills = PostgresFillRepository(session)
    exits = PostgresExitRepository(session)
    transitions = PostgresStateTransitionRepository(session)

    assert provenance.add(value.run) == provenance.get(value.run.run_id) == value.run
    assert evaluations.append(value.run.run_id, value.evaluation) == value.evaluation
    assert (
        evaluations.get(value.run.run_id, INSTRUMENT, value.evaluation.interval)
        == value.evaluation
    )
    assert signals.append(value.signal) == signals.get(value.signal.signal_id) == value.signal
    assert (
        triggers.append(value.trigger)
        == triggers.get(value.trigger.trigger_event_id)
        == value.trigger
    )
    assert (
        intents.append(value.intent)
        == intents.get(value.intent.entry_intent_id)
        == value.intent
    )
    assert fills.append(value.fill) == fills.get(value.fill.fill_id) == value.fill
    assert (
        exits.append(value.exit_fact)
        == exits.get(value.exit_fact.exit_id)
        == value.exit_fact
    )
    assert (
        transitions.append(value.transition)
        == transitions.get(value.transition.transition_id)
        == value.transition
    )
    assert exits.get(value.exit_fact.exit_id).realised_r.as_tuple() == (
        value.exit_fact.realised_r.as_tuple()
    )
    assert signals.get(value.signal.signal_id).created_at == value.signal.created_at


def test_contradictory_reuse_is_typed_and_outer_transaction_remains_usable(
    session: Session,
) -> None:
    value = facts("conflicts", at=AT + timedelta(hours=1))
    persist_graph(session, value)

    unqualified = StrategyEvaluation(
        instrument_id=INSTRUMENT,
        interval=value.evaluation.interval,
        trend=TrendResult(False),
        momentum=MomentumResult(True, True, True, False),
        setup=SetupResult(True),
        qualified=False,
        actionable=False,
        reasons=(DecisionReason.TREND_NOT_MET,),
    )
    contradictions: tuple[tuple[object, object], ...] = (
        (
            PostgresRunProvenanceRepository(session),
            replace(value.run, engine_calculation_version="engine-v2"),
        ),
        (PostgresStrategyEvaluationRepository(session), unqualified),
        (
            PostgresSignalRepository(session),
            replace(value.signal, signal_close=Price(Decimal("102.00"))),
        ),
        (
            PostgresTriggerEventRepository(session),
            replace(value.trigger, reference_price=Price(Decimal("101.10"))),
        ),
        (
            PostgresEntryIntentRepository(session),
            replace(value.intent, reference_price=Price(Decimal("101.10"))),
        ),
        (
            PostgresFillRepository(session),
            replace(value.fill, reference_price=Price(Decimal("101.10"))),
        ),
        (
            PostgresExitRepository(session),
            replace(value.exit_fact, reason=ExitReason.STOP),
        ),
        (
            PostgresStateTransitionRepository(session),
            replace(
                value.transition,
                run=replace(value.run, engine_calculation_version="engine-v2"),
            ),
        ),
    )

    for repository, contradictory in contradictions:
        with pytest.raises(ContradictoryFactError):
            if isinstance(repository, PostgresRunProvenanceRepository):
                repository.add(contradictory)  # type: ignore[arg-type]
            elif isinstance(repository, PostgresStrategyEvaluationRepository):
                repository.append(value.run.run_id, contradictory)  # type: ignore[arg-type]
            else:
                repository.append(contradictory)  # type: ignore[attr-defined]

    follow_up = facts("after-conflict", at=AT + timedelta(hours=2))
    assert PostgresRunProvenanceRepository(session).add(follow_up.run) == follow_up.run


def test_alternate_unique_collisions_raise_typed_conflicts(session: Session) -> None:
    value = facts("alternate", at=AT + timedelta(hours=3))
    persist_graph(session, value)

    alternate_config = replace(value.run, config_id=ConfigId("sf045b-config-alternate-other"))
    with pytest.raises(ContradictoryFactError):
        PostgresRunProvenanceRepository(session).add(alternate_config)

    alternate_intent = EntryIntent.create(
        trigger_event_id=value.trigger.trigger_event_id,
        signal_id=value.signal.signal_id,
        instrument_id=INSTRUMENT,
        reference_price=value.trigger.reference_price,
        quantity=Quantity(11),
        execution_mode=ExecutionMode.PAPER,
        created_at=value.trigger.observed_at,
        run=value.run,
    )
    with pytest.raises(ContradictoryFactError):
        PostgresEntryIntentRepository(session).append(alternate_intent)

    alternate_fill = Fill.create(
        entry_intent_id=value.intent.entry_intent_id,
        trigger_event_id=value.trigger.trigger_event_id,
        signal_id=value.signal.signal_id,
        instrument_id=INSTRUMENT,
        reference_price=value.trigger.reference_price,
        fill_price=Price(Decimal("101.25")),
        quantity=value.intent.quantity,
        execution_mode=value.intent.execution_mode,
        filled_at=value.fill.filled_at + timedelta(seconds=1),
        run=value.run,
    )
    with pytest.raises(ContradictoryFactError):
        PostgresFillRepository(session).append(alternate_fill)

    second = facts("alternate-second", at=AT + timedelta(hours=4))
    persist_graph(session, second)
    alternate_exit = replace(
        second.exit_fact,
        exit_fill_id=value.exit_fact.exit_fill_id,
    )
    with pytest.raises(ContradictoryFactError):
        PostgresExitRepository(session).append(alternate_exit)


def test_caller_rollback_removes_all_repository_writes(postgres_engine: Engine) -> None:
    value = facts("rollback", at=AT + timedelta(hours=5))
    with Session(postgres_engine) as caller_session:
        PostgresRunProvenanceRepository(caller_session).add(value.run)
        PostgresSignalRepository(caller_session).append(value.signal)
        caller_session.rollback()

    with Session(postgres_engine) as observer:
        assert PostgresRunProvenanceRepository(observer).get(value.run.run_id) is None
        assert PostgresSignalRepository(observer).get(value.signal.signal_id) is None


def test_duplicate_from_prior_committed_transaction_is_idempotent(
    postgres_engine: Engine,
) -> None:
    value = facts("committed", at=AT + timedelta(hours=6))
    with Session(postgres_engine) as first_caller:
        assert PostgresRunProvenanceRepository(first_caller).add(value.run) == value.run
        first_caller.commit()
    try:
        with Session(postgres_engine) as retrying_caller:
            assert PostgresRunProvenanceRepository(retrying_caller).add(value.run) == value.run
            retrying_caller.rollback()
    finally:
        with Session(postgres_engine) as cleanup:
            cleanup.execute(sa.delete(RunRecord).where(RunRecord.run_id == str(value.run.run_id)))
            cleanup.execute(
                sa.delete(StrategyConfigRecord).where(
                    StrategyConfigRecord.config_id == str(value.run.config_id)
                )
            )
            cleanup.commit()
