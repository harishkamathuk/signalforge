from __future__ import annotations

import os
from collections.abc import Iterator
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

import signalforge.persistence.coordinator as coordinator_module
from signalforge.domain.armed import ArmedSetup, ArmedSetupState, ExpiryReason
from signalforge.domain.audit import StateTransition, TransitionEntityType
from signalforge.domain.execution import EntryIntent, ExecutionMode, Fill, TriggerEvent
from signalforge.domain.exits import Exit, ExitReason
from signalforge.domain.ids import ConfigId, FillId, InstrumentId, RunId, SignalId
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
from signalforge.persistence.coordinator import PersistenceCoordinator
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


class InjectedFailure(RuntimeError):
    pass


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


def _transition(
    value: Facts,
    *,
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
        run=value.run,
    )


def _inject_after(monkeypatch: pytest.MonkeyPatch, *, after: int, names: tuple[str, ...]) -> None:
    count = 0
    for name in names:
        repository = getattr(coordinator_module, name)
        original = (
            repository.append
            if name
            not in {
                "PostgresArmedSetupRepository",
                "PostgresTradeRepository",
                "PostgresPositionRepository",
            }
            else repository.upsert
        )

        def wrapped(
            self: object, *args: object, _original: object = original, **kwargs: object
        ) -> object:
            nonlocal count
            result = _original(self, *args, **kwargs)  # type: ignore[operator]
            count += 1
            if count == after:
                raise InjectedFailure
            return result

        monkeypatch.setattr(
            repository,
            "append"
            if name
            not in {
                "PostgresArmedSetupRepository",
                "PostgresTradeRepository",
                "PostgresPositionRepository",
            }
            else "upsert",
            wrapped,
        )


@pytest.mark.parametrize("after", (1, 2, 3, 4))
def test_coordinator_arming_boundary_rolls_back_each_write(
    postgres_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
    after: int,
) -> None:
    value = facts(f"sf046-arm-{after}-{uuid4().hex}", at=AT + timedelta(days=after))
    transition = _transition(
        value,
        entity=TransitionEntityType.ARMED_SETUP,
        entity_id=str(value.signal.signal_id),
        before="none",
        after="armed",
        cause_type="strategy_evaluation",
        cause_id="evaluation",
        occurred_at=value.setup.armed_at,
    )
    with Session(postgres_engine) as setup_session:
        PostgresRunProvenanceRepository(setup_session).add(value.run)
        setup_session.commit()
    _inject_after(
        monkeypatch,
        after=after,
        names=(
            "PostgresStrategyEvaluationRepository",
            "PostgresSignalRepository",
            "PostgresArmedSetupRepository",
            "PostgresStateTransitionRepository",
        ),
    )
    with Session(postgres_engine) as session:
        with pytest.raises(InjectedFailure):
            PersistenceCoordinator(session).persist_actionable_evaluation(
                evaluation=value.evaluation,
                signal=value.signal,
                setup=value.setup,
                setup_transition=transition,
            )
    with Session(postgres_engine) as observer:
        assert PostgresSignalRepository(observer).get(value.signal.signal_id) is None
        assert PostgresArmedSetupRepository(observer).get(value.signal.signal_id) is None
        assert PostgresStateTransitionRepository(observer).get(transition.transition_id) is None


def _commit_armed_setup(postgres_engine: Engine, value: Facts) -> None:
    with Session(postgres_engine) as session:
        PostgresRunProvenanceRepository(session).add(value.run)
        PostgresSignalRepository(session).append(value.signal)
        PostgresArmedSetupRepository(session).upsert(value.run.run_id, value.setup)
        session.commit()


@pytest.mark.parametrize("after", (1, 2, 3, 4))
def test_coordinator_trigger_boundary_rolls_back_each_write(
    postgres_engine: Engine, monkeypatch: pytest.MonkeyPatch, after: int
) -> None:
    value = facts(f"sf046-trigger-{after}-{uuid4().hex}", at=AT + timedelta(days=10 + after))
    _commit_armed_setup(postgres_engine, value)
    triggered = replace(value.setup)
    triggered.trigger(at=value.trigger.observed_at)
    transition = _transition(
        value,
        entity=TransitionEntityType.ARMED_SETUP,
        entity_id=str(value.signal.signal_id),
        before="armed",
        after="triggered",
        cause_type="trigger_event",
        cause_id=str(value.trigger.trigger_event_id),
        occurred_at=value.trigger.observed_at,
    )
    _inject_after(
        monkeypatch,
        after=after,
        names=(
            "PostgresTriggerEventRepository",
            "PostgresEntryIntentRepository",
            "PostgresArmedSetupRepository",
            "PostgresStateTransitionRepository",
        ),
    )
    with Session(postgres_engine) as session:
        with pytest.raises(InjectedFailure):
            PersistenceCoordinator(session).persist_trigger_intent(
                trigger=value.trigger,
                intent=value.intent,
                setup=triggered,
                setup_transition=transition,
            )
    with Session(postgres_engine) as observer:
        stored = PostgresArmedSetupRepository(observer).get(value.signal.signal_id)
        assert stored is not None and stored.state is ArmedSetupState.ARMED
        assert PostgresTriggerEventRepository(observer).get(value.trigger.trigger_event_id) is None
        assert PostgresEntryIntentRepository(observer).get(value.intent.entry_intent_id) is None
        assert PostgresStateTransitionRepository(observer).get(transition.transition_id) is None


@pytest.mark.parametrize("after", (1, 2))
def test_coordinator_expiry_boundary_rolls_back_each_write(
    postgres_engine: Engine, monkeypatch: pytest.MonkeyPatch, after: int
) -> None:
    value = facts(f"sf046-expiry-{after}-{uuid4().hex}", at=AT + timedelta(days=20 + after))
    _commit_armed_setup(postgres_engine, value)
    expired = replace(value.setup)
    expired.expire(at=expired.valid_until, reason=ExpiryReason.VALIDITY_WINDOW_END)
    transition = _transition(
        value,
        entity=TransitionEntityType.ARMED_SETUP,
        entity_id=str(value.signal.signal_id),
        before="armed",
        after="expired",
        cause_type="completed_candle",
        cause_id="candle",
        occurred_at=expired.terminal_at or expired.valid_until,
    )
    _inject_after(
        monkeypatch,
        after=after,
        names=("PostgresArmedSetupRepository", "PostgresStateTransitionRepository"),
    )
    with Session(postgres_engine) as session:
        with pytest.raises(InjectedFailure):
            PersistenceCoordinator(session).persist_expiry(
                run_id=value.run.run_id, setup=expired, setup_transition=transition
            )
    with Session(postgres_engine) as observer:
        stored = PostgresArmedSetupRepository(observer).get(value.signal.signal_id)
        assert stored is not None and stored.state is ArmedSetupState.ARMED
        assert PostgresStateTransitionRepository(observer).get(transition.transition_id) is None


def _commit_trigger_intent(postgres_engine: Engine, value: Facts) -> None:
    _commit_armed_setup(postgres_engine, value)
    triggered = replace(value.setup)
    triggered.trigger(at=value.trigger.observed_at)
    with Session(postgres_engine) as session:
        PostgresTriggerEventRepository(session).append(value.trigger)
        PostgresEntryIntentRepository(session).append(value.intent)
        PostgresArmedSetupRepository(session).upsert(value.run.run_id, triggered)
        session.commit()


@pytest.mark.parametrize("after", (1, 2, 3, 4, 5, 6))
def test_coordinator_opened_entry_boundary_rolls_back_each_write(
    postgres_engine: Engine, monkeypatch: pytest.MonkeyPatch, after: int
) -> None:
    value = facts(f"sf046-open-{after}-{uuid4().hex}", at=AT + timedelta(days=130 + after))
    _commit_trigger_intent(postgres_engine, value)
    outcome = PositionOpenOutcome.create(
        fill_id=value.fill.fill_id,
        signal_id=value.fill.signal_id,
        outcome=PositionOpenOutcomeType.OPENED,
        decided_at=value.fill.filled_at,
        run=value.run,
    )
    trade_transition = _transition(
        value,
        entity=TransitionEntityType.TRADE,
        entity_id=str(value.trade.trade_id),
        before="none",
        after="open",
        cause_type="fill",
        cause_id=str(value.fill.fill_id),
        occurred_at=value.trade.opened_at,
    )
    position_transition = _transition(
        value,
        entity=TransitionEntityType.POSITION,
        entity_id=str(value.position.position_id),
        before="none",
        after="open",
        cause_type="trade",
        cause_id=str(value.trade.trade_id),
        occurred_at=value.position.opened_at,
    )
    _inject_after(
        monkeypatch,
        after=after,
        names=(
            "PostgresFillRepository",
            "PostgresPositionOpenOutcomeRepository",
            "PostgresTradeRepository",
            "PostgresPositionRepository",
            "PostgresStateTransitionRepository",
            "PostgresStateTransitionRepository",
        ),
    )
    with Session(postgres_engine) as session:
        with pytest.raises(InjectedFailure):
            PersistenceCoordinator(session).persist_opened_entry(
                fill=value.fill,
                outcome=outcome,
                trade=value.trade,
                position=value.position,
                trade_transition=trade_transition,
                position_transition=position_transition,
            )
    with Session(postgres_engine) as observer:
        assert PostgresFillRepository(observer).get(value.fill.fill_id) is None
        assert PostgresPositionOpenOutcomeRepository(observer).get(outcome.outcome_id) is None
        assert PostgresTradeRepository(observer).get(value.trade.trade_id) is None
        assert PostgresPositionRepository(observer).get(value.position.position_id) is None
        assert (
            PostgresStateTransitionRepository(observer).get(trade_transition.transition_id) is None
        )
        assert (
            PostgresStateTransitionRepository(observer).get(position_transition.transition_id)
            is None
        )


@pytest.mark.parametrize("after", (1, 2))
def test_coordinator_rejected_entry_boundary_rolls_back_each_write(
    postgres_engine: Engine, monkeypatch: pytest.MonkeyPatch, after: int
) -> None:
    value = facts(f"sf046-reject-{after}-{uuid4().hex}", at=AT + timedelta(days=140 + after))
    _commit_trigger_intent(postgres_engine, value)
    outcome = PositionOpenOutcome.create(
        fill_id=value.fill.fill_id,
        signal_id=value.fill.signal_id,
        decided_at=value.fill.filled_at,
        outcome=PositionOpenOutcomeType.REJECTED_NON_POSITIVE_RISK,
        run=value.run,
    )
    _inject_after(
        monkeypatch,
        after=after,
        names=("PostgresFillRepository", "PostgresPositionOpenOutcomeRepository"),
    )
    with Session(postgres_engine) as session:
        with pytest.raises(InjectedFailure):
            PersistenceCoordinator(session).persist_rejected_entry(fill=value.fill, outcome=outcome)
    with Session(postgres_engine) as observer:
        assert PostgresFillRepository(observer).get(value.fill.fill_id) is None
        assert PostgresPositionOpenOutcomeRepository(observer).get(outcome.outcome_id) is None
        assert PostgresTradeRepository(observer).get(value.trade.trade_id) is None
        assert PostgresPositionRepository(observer).get(value.position.position_id) is None


def _commit_open_position(postgres_engine: Engine, value: Facts) -> None:
    _commit_trigger_intent(postgres_engine, value)
    with Session(postgres_engine) as session:
        PostgresFillRepository(session).append(value.fill)
        PostgresTradeRepository(session).upsert(value.trade)
        PostgresPositionRepository(session).upsert(value.position)
        session.commit()


@pytest.mark.parametrize("after", (1, 2, 3, 4, 5))
def test_coordinator_exit_boundary_rolls_back_each_write(
    postgres_engine: Engine, monkeypatch: pytest.MonkeyPatch, after: int
) -> None:
    value = facts(f"sf046-exit-{after}-{uuid4().hex}", at=AT + timedelta(days=150 + after))
    _commit_open_position(postgres_engine, value)
    closed_trade = replace(value.trade)
    closed_trade.close(exit_id=value.exit_fact.exit_id, at=value.exit_fact.exited_at)
    closed_position = replace(value.position)
    closed_position.close(at=value.exit_fact.exited_at)
    trade_transition = _transition(
        value,
        entity=TransitionEntityType.TRADE,
        entity_id=str(value.trade.trade_id),
        before="open",
        after="closed",
        cause_type="exit",
        cause_id=str(value.exit_fact.exit_id),
        occurred_at=value.exit_fact.exited_at,
    )
    position_transition = _transition(
        value,
        entity=TransitionEntityType.POSITION,
        entity_id=str(value.position.position_id),
        before="open",
        after="closed",
        cause_type="exit",
        cause_id=str(value.exit_fact.exit_id),
        occurred_at=value.exit_fact.exited_at,
    )
    _inject_after(
        monkeypatch,
        after=after,
        names=(
            "PostgresExitRepository",
            "PostgresTradeRepository",
            "PostgresPositionRepository",
            "PostgresStateTransitionRepository",
            "PostgresStateTransitionRepository",
        ),
    )
    with Session(postgres_engine) as session:
        with pytest.raises(InjectedFailure):
            PersistenceCoordinator(session).persist_exit(
                exit_fact=value.exit_fact,
                trade=closed_trade,
                position=closed_position,
                trade_transition=trade_transition,
                position_transition=position_transition,
            )
    with Session(postgres_engine) as observer:
        assert PostgresExitRepository(observer).get(value.exit_fact.exit_id) is None
        trade = PostgresTradeRepository(observer).get(value.trade.trade_id)
        position = PostgresPositionRepository(observer).get(value.position.position_id)
        assert trade is not None and trade.state is TradeState.OPEN
        assert position is not None and position.state is PositionState.OPEN
        assert (
            PostgresStateTransitionRepository(observer).get(trade_transition.transition_id) is None
        )
        assert (
            PostgresStateTransitionRepository(observer).get(position_transition.transition_id)
            is None
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
        signal_id=value.fill.signal_id,
        decided_at=value.fill.filled_at,
        outcome=PositionOpenOutcomeType.OPENED,
        run=value.run,
    )

    assert repository.append(opened) == opened
    assert repository.append(opened) == opened

    rejected = PositionOpenOutcome.create(
        fill_id=value.fill.fill_id,
        signal_id=value.fill.signal_id,
        decided_at=value.fill.filled_at,
        outcome=PositionOpenOutcomeType.REJECTED_NON_POSITIVE_RISK,
        run=value.run,
    )
    with pytest.raises(ContradictoryFactError):
        repository.append(rejected)
    assert opened.outcome_id == rejected.outcome_id
    assert repository.get(opened.outcome_id) == opened
    stored_opened = repository.get(opened.outcome_id)
    assert stored_opened is not None
    assert stored_opened.signal_id == value.fill.signal_id
    assert stored_opened.decided_at == value.fill.filled_at
    assert stored_opened.decided_at.tzinfo is not None

    missing_signal = PositionOpenOutcome.create(
        fill_id=value.fill.fill_id,
        signal_id=SignalId("sf046-missing-signal"),
        decided_at=value.fill.filled_at,
        outcome=PositionOpenOutcomeType.OPENED,
        run=value.run,
    )
    with pytest.raises(PersistenceDependencyError):
        repository.append(missing_signal)

    other_interval = CandleInterval.five_minutes(value.signal.created_at + timedelta(minutes=5))
    other_signal = Signal.create(
        instrument_id=value.signal.instrument_id,
        interval=other_interval,
        signal_close=value.signal.signal_close,
        signal_low=value.signal.signal_low,
        run=value.run,
        created_at=other_interval.end,
    )
    assert PostgresSignalRepository(session).append(other_signal) == other_signal
    mismatched_signal = PositionOpenOutcome.create(
        fill_id=value.fill.fill_id,
        signal_id=other_signal.signal_id,
        decided_at=value.fill.filled_at,
        outcome=PositionOpenOutcomeType.OPENED,
        run=value.run,
    )
    with pytest.raises(ContradictoryFactError):
        repository.append(mismatched_signal)

    reverse = facts("position-open-outcome-reverse", at=AT + timedelta(hours=14))
    persist_graph(session, reverse)
    reverse_rejected = PositionOpenOutcome.create(
        fill_id=reverse.fill.fill_id,
        signal_id=reverse.fill.signal_id,
        decided_at=reverse.fill.filled_at,
        outcome=PositionOpenOutcomeType.REJECTED_NON_POSITIVE_RISK,
        run=reverse.run,
    )
    reverse_opened = PositionOpenOutcome.create(
        fill_id=reverse.fill.fill_id,
        signal_id=reverse.fill.signal_id,
        decided_at=reverse.fill.filled_at,
        outcome=PositionOpenOutcomeType.OPENED,
        run=reverse.run,
    )
    assert reverse_rejected.outcome_id == reverse_opened.outcome_id
    assert repository.append(reverse_rejected) == reverse_rejected
    with pytest.raises(ContradictoryFactError):
        repository.append(reverse_opened)
    assert repository.get(reverse_rejected.outcome_id) == reverse_rejected

    missing_fill = facts("position-open-outcome-missing-fill", at=AT + timedelta(hours=15))
    missing_outcome = PositionOpenOutcome.create(
        fill_id=missing_fill.fill.fill_id,
        signal_id=missing_fill.fill.signal_id,
        decided_at=missing_fill.fill.filled_at,
        outcome=PositionOpenOutcomeType.OPENED,
        run=missing_fill.run,
    )
    with pytest.raises(PersistenceDependencyError):
        repository.append(missing_outcome)


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


def test_coordinator_exact_and_committed_retries_for_all_boundaries(
    postgres_engine: Engine,
) -> None:
    """Coordinator retries preserve deterministic rows for all accepted cases."""
    arm = facts(f"retry-arm-{uuid4().hex}", at=AT + timedelta(days=300))
    arm_transition = _transition(
        arm,
        entity=TransitionEntityType.ARMED_SETUP,
        entity_id=str(arm.signal.signal_id),
        before="none",
        after="armed",
        cause_type="strategy_evaluation",
        cause_id="evaluation",
        occurred_at=arm.setup.armed_at,
    )
    with Session(postgres_engine) as session:
        PostgresRunProvenanceRepository(session).add(arm.run)
        session.commit()
        coordinator = PersistenceCoordinator(session)
        first = coordinator.persist_actionable_evaluation(
            evaluation=arm.evaluation,
            signal=arm.signal,
            setup=arm.setup,
            setup_transition=arm_transition,
        )
        assert first[0] == arm.evaluation
        assert first[1] == arm.signal
        assert first[2].signal_id == arm.setup.signal_id
        assert first[2].state is ArmedSetupState.ARMED
        assert first[2].armed_at == arm.setup.armed_at
        assert first[3].transition_id == arm_transition.transition_id
        assert (
            coordinator.persist_actionable_evaluation(
                evaluation=arm.evaluation,
                signal=arm.signal,
                setup=arm.setup,
                setup_transition=arm_transition,
            )
            is not None
        )
    with Session(postgres_engine) as session:
        assert (
            PersistenceCoordinator(session).persist_actionable_evaluation(
                evaluation=arm.evaluation,
                signal=arm.signal,
                setup=arm.setup,
                setup_transition=arm_transition,
            )
            is not None
        )

    trigger = facts(f"retry-trigger-{uuid4().hex}", at=AT + timedelta(days=301))
    _commit_armed_setup(postgres_engine, trigger)
    triggered = replace(trigger.setup)
    triggered.trigger(at=trigger.trigger.observed_at)
    trigger_transition = _transition(
        trigger,
        entity=TransitionEntityType.ARMED_SETUP,
        entity_id=str(trigger.signal.signal_id),
        before="armed",
        after="triggered",
        cause_type="trigger_event",
        cause_id=str(trigger.trigger.trigger_event_id),
        occurred_at=trigger.trigger.observed_at,
    )
    with Session(postgres_engine) as session:
        coordinator = PersistenceCoordinator(session)
        first = coordinator.persist_trigger_intent(
            trigger=trigger.trigger,
            intent=trigger.intent,
            setup=triggered,
            setup_transition=trigger_transition,
        )
        assert first[0] == trigger.trigger
        assert first[1] == trigger.intent
        assert first[2].signal_id == trigger.setup.signal_id
        assert first[2].state is ArmedSetupState.TRIGGERED
        assert first[2].terminal_at == triggered.terminal_at
        assert first[3].transition_id == trigger_transition.transition_id
        assert (
            coordinator.persist_trigger_intent(
                trigger=trigger.trigger,
                intent=trigger.intent,
                setup=triggered,
                setup_transition=trigger_transition,
            )
            is not None
        )
    with Session(postgres_engine) as session:
        assert (
            PersistenceCoordinator(session).persist_trigger_intent(
                trigger=trigger.trigger,
                intent=trigger.intent,
                setup=triggered,
                setup_transition=trigger_transition,
            )
            is not None
        )

    expired = facts(f"retry-expiry-{uuid4().hex}", at=AT + timedelta(days=302))
    _commit_armed_setup(postgres_engine, expired)
    expired_setup = replace(expired.setup)
    expired_setup.expire(at=expired_setup.valid_until, reason=ExpiryReason.VALIDITY_WINDOW_END)
    expiry_transition = _transition(
        expired,
        entity=TransitionEntityType.ARMED_SETUP,
        entity_id=str(expired.signal.signal_id),
        before="armed",
        after="expired",
        cause_type="completed_candle",
        cause_id="candle",
        occurred_at=expired_setup.valid_until,
    )
    with Session(postgres_engine) as session:
        coordinator = PersistenceCoordinator(session)
        first = coordinator.persist_expiry(
            run_id=expired.run.run_id, setup=expired_setup, setup_transition=expiry_transition
        )
        assert first[0].signal_id == expired.setup.signal_id
        assert first[0].state is ArmedSetupState.EXPIRED
        assert first[0].terminal_at == expired_setup.terminal_at
        assert first[0].expiry_reason is ExpiryReason.VALIDITY_WINDOW_END
        assert first[1].transition_id == expiry_transition.transition_id
        assert (
            coordinator.persist_expiry(
                run_id=expired.run.run_id, setup=expired_setup, setup_transition=expiry_transition
            )
            is not None
        )
    with Session(postgres_engine) as session:
        assert (
            PersistenceCoordinator(session).persist_expiry(
                run_id=expired.run.run_id, setup=expired_setup, setup_transition=expiry_transition
            )
            is not None
        )
    opened = facts(f"retry-open-{uuid4().hex}", at=AT + timedelta(days=303))
    _commit_trigger_intent(postgres_engine, opened)
    opened_outcome = PositionOpenOutcome.create(
        fill_id=opened.fill.fill_id,
        signal_id=opened.fill.signal_id,
        outcome=PositionOpenOutcomeType.OPENED,
        decided_at=opened.fill.filled_at,
        run=opened.run,
    )
    trade_open = _transition(
        opened,
        entity=TransitionEntityType.TRADE,
        entity_id=str(opened.trade.trade_id),
        before="none",
        after="open",
        cause_type="fill",
        cause_id=str(opened.fill.fill_id),
        occurred_at=opened.trade.opened_at,
    )
    position_open = _transition(
        opened,
        entity=TransitionEntityType.POSITION,
        entity_id=str(opened.position.position_id),
        before="none",
        after="open",
        cause_type="trade",
        cause_id=str(opened.trade.trade_id),
        occurred_at=opened.position.opened_at,
    )
    with Session(postgres_engine) as session:
        coordinator = PersistenceCoordinator(session)
        first = coordinator.persist_opened_entry(
            fill=opened.fill,
            outcome=opened_outcome,
            trade=opened.trade,
            position=opened.position,
            trade_transition=trade_open,
            position_transition=position_open,
        )
        assert first[0] == opened.fill
        assert first[1] == opened_outcome
        assert first[2].trade_id == opened.trade.trade_id
        assert first[2].state is TradeState.OPEN
        assert first[2].opened_at == opened.trade.opened_at
        assert first[3].position_id == opened.position.position_id
        assert first[3].state is PositionState.OPEN
        assert first[3].opened_at == opened.position.opened_at
        assert first[4].transition_id == trade_open.transition_id
        assert first[5].transition_id == position_open.transition_id
        assert (
            coordinator.persist_opened_entry(
                fill=opened.fill,
                outcome=opened_outcome,
                trade=opened.trade,
                position=opened.position,
                trade_transition=trade_open,
                position_transition=position_open,
            )
            is not None
        )
    with Session(postgres_engine) as session:
        assert (
            PersistenceCoordinator(session).persist_opened_entry(
                fill=opened.fill,
                outcome=opened_outcome,
                trade=opened.trade,
                position=opened.position,
                trade_transition=trade_open,
                position_transition=position_open,
            )
            is not None
        )

    rejected = facts(f"retry-reject-{uuid4().hex}", at=AT + timedelta(days=304))
    _commit_trigger_intent(postgres_engine, rejected)
    rejected_outcome = PositionOpenOutcome.create(
        fill_id=rejected.fill.fill_id,
        signal_id=rejected.fill.signal_id,
        decided_at=rejected.fill.filled_at,
        outcome=PositionOpenOutcomeType.REJECTED_NON_POSITIVE_RISK,
        run=rejected.run,
    )
    with Session(postgres_engine) as session:
        coordinator = PersistenceCoordinator(session)
        first = coordinator.persist_rejected_entry(fill=rejected.fill, outcome=rejected_outcome)
        assert first[0] == rejected.fill
        assert first[1] == rejected_outcome
        assert (
            coordinator.persist_rejected_entry(fill=rejected.fill, outcome=rejected_outcome)
            is not None
        )
    with Session(postgres_engine) as session:
        assert (
            PersistenceCoordinator(session).persist_rejected_entry(
                fill=rejected.fill, outcome=rejected_outcome
            )
            is not None
        )

    exiting = facts(f"retry-exit-{uuid4().hex}", at=AT + timedelta(days=305))
    _commit_open_position(postgres_engine, exiting)
    closed_trade = replace(exiting.trade)
    closed_trade.close(exit_id=exiting.exit_fact.exit_id, at=exiting.exit_fact.exited_at)
    closed_position = replace(exiting.position)
    closed_position.close(at=exiting.exit_fact.exited_at)
    trade_close = _transition(
        exiting,
        entity=TransitionEntityType.TRADE,
        entity_id=str(exiting.trade.trade_id),
        before="open",
        after="closed",
        cause_type="exit",
        cause_id=str(exiting.exit_fact.exit_id),
        occurred_at=exiting.exit_fact.exited_at,
    )
    position_close = _transition(
        exiting,
        entity=TransitionEntityType.POSITION,
        entity_id=str(exiting.position.position_id),
        before="open",
        after="closed",
        cause_type="exit",
        cause_id=str(exiting.exit_fact.exit_id),
        occurred_at=exiting.exit_fact.exited_at,
    )
    with Session(postgres_engine) as session:
        coordinator = PersistenceCoordinator(session)
        first = coordinator.persist_exit(
            exit_fact=exiting.exit_fact,
            trade=closed_trade,
            position=closed_position,
            trade_transition=trade_close,
            position_transition=position_close,
        )
        assert first[0] == exiting.exit_fact
        assert first[1].trade_id == exiting.trade.trade_id
        assert first[1].state is TradeState.CLOSED
        assert first[1].closed_at == exiting.exit_fact.exited_at
        assert first[1].exit_id == exiting.exit_fact.exit_id
        assert first[2].position_id == exiting.position.position_id
        assert first[2].state is PositionState.CLOSED
        assert first[2].closed_at == exiting.exit_fact.exited_at
        assert first[3].transition_id == trade_close.transition_id
        assert first[4].transition_id == position_close.transition_id
        assert (
            coordinator.persist_exit(
                exit_fact=exiting.exit_fact,
                trade=closed_trade,
                position=closed_position,
                trade_transition=trade_close,
                position_transition=position_close,
            )
            is not None
        )
    with Session(postgres_engine) as session:
        assert (
            PersistenceCoordinator(session).persist_exit(
                exit_fact=exiting.exit_fact,
                trade=closed_trade,
                position=closed_position,
                trade_transition=trade_close,
                position_transition=position_close,
            )
            is not None
        )

    # A separate Session sees the same deterministic logical identities and no
    # different terminal/current state after each committed retry.
    with Session(postgres_engine) as observer:
        stored_arm = PostgresArmedSetupRepository(observer).get(arm.setup.signal_id)
        assert stored_arm is not None
        assert stored_arm.state is ArmedSetupState.ARMED
        assert stored_arm.armed_at == arm.setup.armed_at
        assert (
            PostgresStateTransitionRepository(observer).get(arm_transition.transition_id)
            == arm_transition
        )

        stored_trigger = PostgresArmedSetupRepository(observer).get(trigger.setup.signal_id)
        assert stored_trigger is not None
        assert stored_trigger.state is ArmedSetupState.TRIGGERED
        assert stored_trigger.terminal_at == triggered.terminal_at
        assert (
            PostgresTriggerEventRepository(observer).get(trigger.trigger.trigger_event_id)
            == trigger.trigger
        )
        assert (
            PostgresEntryIntentRepository(observer).get(trigger.intent.entry_intent_id)
            == trigger.intent
        )
        assert (
            PostgresStateTransitionRepository(observer).get(trigger_transition.transition_id)
            == trigger_transition
        )

        stored_expiry = PostgresArmedSetupRepository(observer).get(expired.setup.signal_id)
        assert stored_expiry is not None
        assert stored_expiry.state is ArmedSetupState.EXPIRED
        assert stored_expiry.terminal_at == expired_setup.terminal_at
        assert stored_expiry.expiry_reason is ExpiryReason.VALIDITY_WINDOW_END
        assert (
            PostgresStateTransitionRepository(observer).get(expiry_transition.transition_id)
            == expiry_transition
        )

        stored_trade = PostgresTradeRepository(observer).get(opened.trade.trade_id)
        stored_position = PostgresPositionRepository(observer).get(opened.position.position_id)
        assert stored_trade is not None and stored_trade.state is TradeState.OPEN
        assert stored_position is not None and stored_position.state is PositionState.OPEN
        assert stored_trade.opened_at == opened.trade.opened_at
        assert stored_position.opened_at == opened.position.opened_at
        assert PostgresFillRepository(observer).get(opened.fill.fill_id) == opened.fill
        assert (
            PostgresPositionOpenOutcomeRepository(observer).get(opened_outcome.outcome_id)
            == opened_outcome
        )
        assert (
            PostgresStateTransitionRepository(observer).get(trade_open.transition_id) == trade_open
        )
        assert (
            PostgresStateTransitionRepository(observer).get(position_open.transition_id)
            == position_open
        )

        assert PostgresFillRepository(observer).get(rejected.fill.fill_id) == rejected.fill
        assert (
            PostgresPositionOpenOutcomeRepository(observer).get(rejected_outcome.outcome_id)
            == rejected_outcome
        )
        assert PostgresTradeRepository(observer).get(rejected.trade.trade_id) is None
        assert PostgresPositionRepository(observer).get(rejected.position.position_id) is None

        stored_closed_trade = PostgresTradeRepository(observer).get(exiting.trade.trade_id)
        stored_closed_position = PostgresPositionRepository(observer).get(
            exiting.position.position_id
        )
        assert stored_closed_trade is not None and stored_closed_trade.state is TradeState.CLOSED
        assert (
            stored_closed_position is not None
            and stored_closed_position.state is PositionState.CLOSED
        )
        assert stored_closed_trade.closed_at == exiting.exit_fact.exited_at
        assert stored_closed_trade.exit_id == exiting.exit_fact.exit_id
        assert stored_closed_position.closed_at == exiting.exit_fact.exited_at
        assert PostgresExitRepository(observer).get(exiting.exit_fact.exit_id) == exiting.exit_fact
        assert (
            PostgresStateTransitionRepository(observer).get(trade_close.transition_id)
            == trade_close
        )
        assert (
            PostgresStateTransitionRepository(observer).get(position_close.transition_id)
            == position_close
        )


def test_coordinator_opened_entry_classifies_partial_graphs_explicitly(
    postgres_engine: Engine,
) -> None:
    """Exact Fill-only partials complete; conflicting outcome partials do not."""
    exact = facts(f"partial-exact-{uuid4().hex}", at=AT + timedelta(days=306))
    _commit_trigger_intent(postgres_engine, exact)
    exact_outcome = PositionOpenOutcome.create(
        fill_id=exact.fill.fill_id,
        signal_id=exact.fill.signal_id,
        decided_at=exact.fill.filled_at,
        outcome=PositionOpenOutcomeType.OPENED,
        run=exact.run,
    )
    exact_trade_transition = _transition(
        exact,
        entity=TransitionEntityType.TRADE,
        entity_id=str(exact.trade.trade_id),
        before="none",
        after="open",
        cause_type="fill",
        cause_id=str(exact.fill.fill_id),
        occurred_at=exact.trade.opened_at,
    )
    exact_position_transition = _transition(
        exact,
        entity=TransitionEntityType.POSITION,
        entity_id=str(exact.position.position_id),
        before="none",
        after="open",
        cause_type="trade",
        cause_id=str(exact.trade.trade_id),
        occurred_at=exact.position.opened_at,
    )
    with Session(postgres_engine) as session:
        assert PostgresFillRepository(session).append(exact.fill) == exact.fill
        session.commit()
    with Session(postgres_engine) as session:
        persisted = PersistenceCoordinator(session).persist_opened_entry(
            fill=exact.fill,
            outcome=exact_outcome,
            trade=exact.trade,
            position=exact.position,
            trade_transition=exact_trade_transition,
            position_transition=exact_position_transition,
        )
        assert persisted[1] == exact_outcome
        assert persisted[2].trade_id == exact.trade.trade_id
        assert persisted[3].position_id == exact.position.position_id

    conflicting = facts(f"partial-conflict-{uuid4().hex}", at=AT + timedelta(days=307))
    _commit_trigger_intent(postgres_engine, conflicting)
    rejected = PositionOpenOutcome.create(
        fill_id=conflicting.fill.fill_id,
        signal_id=conflicting.fill.signal_id,
        decided_at=conflicting.fill.filled_at,
        outcome=PositionOpenOutcomeType.REJECTED_NON_POSITIVE_RISK,
        run=conflicting.run,
    )
    conflicting_opened = PositionOpenOutcome.create(
        fill_id=conflicting.fill.fill_id,
        signal_id=conflicting.fill.signal_id,
        decided_at=conflicting.fill.filled_at,
        outcome=PositionOpenOutcomeType.OPENED,
        run=conflicting.run,
    )
    trade_transition = _transition(
        conflicting,
        entity=TransitionEntityType.TRADE,
        entity_id=str(conflicting.trade.trade_id),
        before="none",
        after="open",
        cause_type="fill",
        cause_id=str(conflicting.fill.fill_id),
        occurred_at=conflicting.trade.opened_at,
    )
    position_transition = _transition(
        conflicting,
        entity=TransitionEntityType.POSITION,
        entity_id=str(conflicting.position.position_id),
        before="none",
        after="open",
        cause_type="trade",
        cause_id=str(conflicting.trade.trade_id),
        occurred_at=conflicting.position.opened_at,
    )
    with Session(postgres_engine) as session:
        PostgresFillRepository(session).append(conflicting.fill)
        PostgresPositionOpenOutcomeRepository(session).append(rejected)
        session.commit()
    with Session(postgres_engine) as session:
        with pytest.raises(ContradictoryFactError):
            PersistenceCoordinator(session).persist_opened_entry(
                fill=conflicting.fill,
                outcome=conflicting_opened,
                trade=conflicting.trade,
                position=conflicting.position,
                trade_transition=trade_transition,
                position_transition=position_transition,
            )
    with Session(postgres_engine) as observer:
        assert PostgresPositionOpenOutcomeRepository(observer).get(rejected.outcome_id) == rejected
        assert PostgresTradeRepository(observer).get(conflicting.trade.trade_id) is None
        assert PostgresPositionRepository(observer).get(conflicting.position.position_id) is None
        assert (
            PostgresStateTransitionRepository(observer).get(trade_transition.transition_id) is None
        )
        assert (
            PostgresStateTransitionRepository(observer).get(position_transition.transition_id)
            is None
        )
