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

from signalforge.domain.armed import ArmedSetup, ArmedSetupState, ExpiryReason
from signalforge.domain.audit import StateTransition, TransitionEntityType
from signalforge.domain.execution import EntryIntent, ExecutionMode, Fill, TriggerEvent
from signalforge.domain.exits import Exit, ExitReason
from signalforge.domain.ids import ConfigId, FillId, InstrumentId, RunId
from signalforge.domain.money import Price, Quantity
from signalforge.domain.position_outcomes import PositionOpenOutcome, PositionOpenOutcomeType
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
from signalforge.domain.time import IST, CandleInterval
from signalforge.domain.trades import Trade, TradeState
from signalforge.persistence.errors import ContradictoryFactError, PersistenceDependencyError
from signalforge.persistence.models import RunRecord, StrategyConfigRecord
from signalforge.persistence.repositories import (
    PostgresArmedSetupRepository,
    PostgresEntryIntentRepository,
    PostgresExitRepository,
    PostgresFillRepository,
    PostgresPositionOpenOutcomeRepository,
    PostgresPositionRepository,
    PostgresRunProvenanceRepository,
    PostgresSignalRepository,
    PostgresStateTransitionRepository,
    PostgresStrategyEvaluationRepository,
    PostgresTradeRepository,
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
    setup: ArmedSetup
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
    setup = ArmedSetup(
        signal_id=signal.signal_id,
        raw_trigger=Price(Decimal("101.15")),
        tradable_trigger=Price(Decimal("101.15")),
        signal_low=signal.signal_low,
        armed_at=interval.end,
        valid_until=interval.end + timedelta(minutes=5),
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
        setup,
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
        PostgresStrategyEvaluationRepository(session).append(value.run.run_id, value.evaluation)
        == value.evaluation
    )
    assert PostgresSignalRepository(session).append(value.signal) == value.signal
    assert PostgresTriggerEventRepository(session).append(value.trigger) == value.trigger
    assert PostgresEntryIntentRepository(session).append(value.intent) == value.intent
    assert PostgresFillRepository(session).append(value.fill) == value.fill
    assert (
        PostgresArmedSetupRepository(session).upsert(value.run.run_id, value.setup).state
        is ArmedSetupState.ARMED
    )
    assert PostgresTradeRepository(session).upsert(value.trade).state is TradeState.OPEN
    assert PostgresPositionRepository(session).upsert(value.position).state is PositionState.OPEN
    assert PostgresExitRepository(session).append(value.exit_fact) == value.exit_fact
    assert PostgresStateTransitionRepository(session).append(value.transition) == value.transition


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
        evaluations.get(value.run.run_id, INSTRUMENT, value.evaluation.interval) == value.evaluation
    )
    assert signals.append(value.signal) == signals.get(value.signal.signal_id) == value.signal
    assert (
        triggers.append(value.trigger)
        == triggers.get(value.trigger.trigger_event_id)
        == value.trigger
    )
    assert intents.append(value.intent) == intents.get(value.intent.entry_intent_id) == value.intent
    assert fills.append(value.fill) == fills.get(value.fill.fill_id) == value.fill
    assert exits.append(value.exit_fact) == exits.get(value.exit_fact.exit_id) == value.exit_fact
    assert (
        transitions.append(value.transition)
        == transitions.get(value.transition.transition_id)
        == value.transition
    )
    stored_exit = exits.get(value.exit_fact.exit_id)
    stored_signal = signals.get(value.signal.signal_id)
    assert stored_exit is not None and stored_signal is not None
    assert stored_exit.realised_r.as_tuple() == value.exit_fact.realised_r.as_tuple()
    assert stored_signal.created_at == value.signal.created_at


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


def test_authoritative_repositories_apply_forward_transitions_and_terminal_retries(
    session: Session,
) -> None:
    value = facts("authoritative", at=AT + timedelta(hours=7))
    persist_graph(session, value)

    setups = PostgresArmedSetupRepository(session)
    trades = PostgresTradeRepository(session)
    positions = PostgresPositionRepository(session)

    assert setups.upsert(value.run.run_id, value.setup).state is ArmedSetupState.ARMED
    triggered = replace(value.setup)
    triggered.trigger(at=value.setup.armed_at + timedelta(minutes=1))
    assert triggered.terminal_at is not None
    assert setups.upsert(value.run.run_id, triggered).terminal_at == triggered.terminal_at
    assert setups.upsert(value.run.run_id, triggered).terminal_at == triggered.terminal_at
    stored_triggered = setups.get(value.setup.signal_id)
    assert stored_triggered is not None
    assert stored_triggered.state is ArmedSetupState.TRIGGERED

    closed_trade = replace(value.trade)
    closed_trade.close(exit_id=value.exit_fact.exit_id, at=value.exit_fact.exited_at)
    assert closed_trade.closed_at is not None
    closed_position = replace(value.position)
    closed_position.close(at=value.exit_fact.exited_at)
    assert closed_position.closed_at is not None
    assert trades.upsert(closed_trade).closed_at == closed_trade.closed_at
    assert trades.upsert(closed_trade).closed_at == closed_trade.closed_at
    assert positions.upsert(closed_position).closed_at == closed_position.closed_at
    assert positions.upsert(closed_position).closed_at == closed_position.closed_at

    expired_value = facts("expired", at=AT + timedelta(hours=8))
    persist_graph(session, expired_value)
    expired = replace(expired_value.setup)
    expired.expire(at=expired.valid_until, reason=ExpiryReason.VALIDITY_WINDOW_END)
    assert (
        setups.upsert(expired_value.run.run_id, expired).expiry_reason
        is ExpiryReason.VALIDITY_WINDOW_END
    )
    assert (
        setups.upsert(expired_value.run.run_id, expired).expiry_reason
        is ExpiryReason.VALIDITY_WINDOW_END
    )
    stored_expired = setups.get(expired.signal_id)
    assert stored_expired is not None
    assert stored_expired.state is ArmedSetupState.EXPIRED


def test_position_open_outcome_is_exactly_one_idempotent_fact_per_fill(session: Session) -> None:
    value = facts("position-open-outcome", at=AT + timedelta(hours=13))
    persist_graph(session, value)
    repository = PostgresPositionOpenOutcomeRepository(session)
    opened = PositionOpenOutcome.create(
        fill_id=value.fill.fill_id,
        outcome=PositionOpenOutcomeType.OPENED,
        run=value.run,
    )

    assert repository.append(opened) == opened
    assert repository.append(opened) == opened

    rejected = PositionOpenOutcome.create(
        fill_id=value.fill.fill_id,
        outcome=PositionOpenOutcomeType.REJECTED_NON_POSITIVE_RISK,
        run=value.run,
    )
    with pytest.raises(ContradictoryFactError):
        repository.append(rejected)


def test_authoritative_repositories_reject_conflicts_and_keep_outer_transaction_usable(
    session: Session,
) -> None:
    value = facts("state-conflict", at=AT + timedelta(hours=9))
    persist_graph(session, value)
    setups = PostgresArmedSetupRepository(session)
    trades = PostgresTradeRepository(session)
    positions = PostgresPositionRepository(session)

    with pytest.raises(ContradictoryFactError):
        setups.upsert(value.run.run_id, replace(value.setup, raw_trigger=Price(Decimal("101.14"))))

    triggered = replace(value.setup)
    triggered.trigger(at=value.setup.armed_at + timedelta(minutes=1))
    assert triggered.terminal_at is not None
    assert setups.upsert(value.run.run_id, triggered).terminal_at == triggered.terminal_at
    with pytest.raises(ContradictoryFactError):
        setups.upsert(value.run.run_id, value.setup)
    with pytest.raises(ContradictoryFactError):
        setups.upsert(
            value.run.run_id,
            replace(triggered, terminal_at=triggered.terminal_at + timedelta(seconds=1)),
        )
    with pytest.raises(ContradictoryFactError):
        setups.upsert(
            value.run.run_id,
            replace(
                triggered,
                state=ArmedSetupState.EXPIRED,
                expiry_reason=ExpiryReason.VALIDITY_WINDOW_END,
            ),
        )

    changed_economics = replace(
        value.trade,
        stop_price=Price(Decimal("100.10")),
        risk_per_share=Price(Decimal("1.10")),
        raw_target_price=Price(Decimal("102.85")),
        tradable_target_price=Price(Decimal("102.85")),
    )
    with pytest.raises(ContradictoryFactError):
        trades.upsert(changed_economics)

    closed_trade = replace(value.trade)
    closed_trade.close(exit_id=value.exit_fact.exit_id, at=value.exit_fact.exited_at)
    assert closed_trade.closed_at is not None
    assert trades.upsert(closed_trade).closed_at == closed_trade.closed_at
    with pytest.raises(ContradictoryFactError):
        trades.upsert(value.trade)
    with pytest.raises(ContradictoryFactError):
        trades.upsert(
            replace(closed_trade, closed_at=closed_trade.closed_at + timedelta(seconds=1))
        )

    with pytest.raises(ContradictoryFactError):
        positions.upsert(replace(value.position, average_entry_price=Price(Decimal("101.25"))))
    closed_position = replace(value.position)
    closed_position.close(at=value.exit_fact.exited_at)
    assert closed_position.closed_at is not None
    assert positions.upsert(closed_position).closed_at == closed_position.closed_at
    with pytest.raises(ContradictoryFactError):
        positions.upsert(value.position)
    with pytest.raises(ContradictoryFactError):
        positions.upsert(
            replace(closed_position, closed_at=closed_position.closed_at + timedelta(seconds=1))
        )

    follow_up = facts("after-state-conflict", at=AT + timedelta(hours=10))
    persist_graph(session, follow_up)


def test_authoritative_repository_writes_are_owned_by_caller_rollback(
    postgres_engine: Engine,
) -> None:
    value = facts("state-rollback", at=AT + timedelta(hours=11))
    with Session(postgres_engine) as caller_session:
        persist_graph(caller_session, value)
        caller_session.rollback()

    with Session(postgres_engine) as observer:
        assert PostgresArmedSetupRepository(observer).get(value.setup.signal_id) is None
        assert PostgresTradeRepository(observer).get(value.trade.trade_id) is None
        assert PostgresPositionRepository(observer).get(value.position.position_id) is None


def test_authoritative_repositories_require_persisted_dependencies(session: Session) -> None:
    value = facts("missing-dependencies", at=AT + timedelta(hours=12))

    with pytest.raises(PersistenceDependencyError):
        PostgresArmedSetupRepository(session).upsert(value.run.run_id, value.setup)
    with pytest.raises(PersistenceDependencyError):
        PostgresTradeRepository(session).upsert(value.trade)
    with pytest.raises(PersistenceDependencyError):
        PostgresPositionRepository(session).upsert(value.position)
