from __future__ import annotations

import os
from collections.abc import Iterator
from dataclasses import replace
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from signalforge.domain.armed import ArmedSetupState, ExpiryReason
from signalforge.domain.audit import TransitionEntityType
from signalforge.domain.position_outcomes import PositionOpenOutcome, PositionOpenOutcomeType
from signalforge.domain.positions import PositionState
from signalforge.domain.trades import TradeState
from signalforge.persistence.coordinator import PersistenceCoordinator
from signalforge.persistence.repositories import (
    PostgresArmedSetupRepository,
    PostgresFillRepository,
    PostgresIndicatorCheckpointRepository,
    PostgresPositionOpenOutcomeRepository,
    PostgresPositionRepository,
    PostgresRunProvenanceRepository,
    PostgresStateTransitionRepository,
    PostgresStrategyDecisionRepository,
    PostgresTradeRepository,
)
from signalforge.runtime.indicators import V1_INDICATOR_REQUIREMENTS, IndicatorEngine
from tests.integration.persistence.test_repository_adapters_postgres import (
    InjectedFailure,
    _commit_armed_setup,
    _commit_open_position,
    _commit_trigger_intent,
    _inject_after,
    _transition,
    facts,
)


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


def test_completed_evaluation_rollback_can_retry_exactly_once(
    postgres_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    value = facts(f"sf052-completed-{uuid4().hex[:8]}")
    decision = replace(
        value.decision_fact,
        qualified=False,
        actionable=False,
        reasons=("not_actionable",),
    )
    state = IndicatorEngine(
        value.signal.instrument_id,
        value.run.engine_calculation_version,
        requirements=V1_INDICATOR_REQUIREMENTS,
    ).state
    with Session(postgres_engine) as session:
        PostgresRunProvenanceRepository(session).add(value.run)
        session.commit()

    _inject_after(
        monkeypatch,
        after=1,
        names=("PostgresIndicatorCheckpointRepository", "PostgresStrategyDecisionRepository"),
    )
    with Session(postgres_engine) as session:
        with pytest.raises(InjectedFailure):
            PersistenceCoordinator(session).persist_completed_evaluation(
                run=value.run,
                state=state,
                evaluation=decision,
            )
    monkeypatch.undo()

    with Session(postgres_engine) as observer:
        assert (
            PostgresIndicatorCheckpointRepository(observer).get(
                value.run.run_id, value.signal.instrument_id
            )
            is None
        )
        assert (
            PostgresStrategyDecisionRepository(observer).get(
                value.run.run_id,
                value.signal.instrument_id,
                value.evaluation.interval,
            )
            is None
        )

    with Session(postgres_engine) as session:
        persisted_state, persisted_decision = (
            PersistenceCoordinator(session).persist_completed_evaluation(
                run=value.run,
                state=state,
                evaluation=decision,
            )
        )
    assert persisted_state == state
    assert persisted_decision == decision

    with Session(postgres_engine) as observer:
        assert (
            PostgresIndicatorCheckpointRepository(observer).get(
                value.run.run_id, value.signal.instrument_id
            )
            == state
        )
        assert (
            PostgresStrategyDecisionRepository(observer).get(
                value.run.run_id,
                value.signal.instrument_id,
                value.evaluation.interval,
            )
            == decision
        )


def test_actionable_rollback_can_retry_exactly_once(
    postgres_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    value = facts(f"sf052-arm-{uuid4().hex[:8]}")
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
    with Session(postgres_engine) as session:
        PostgresRunProvenanceRepository(session).add(value.run)
        session.commit()

    _inject_after(
        monkeypatch,
        after=3,
        names=(
            "PostgresStrategyDecisionRepository",
            "PostgresSignalRepository",
            "PostgresArmedSetupRepository",
            "PostgresStateTransitionRepository",
        ),
    )
    with Session(postgres_engine) as session:
        with pytest.raises(InjectedFailure):
            PersistenceCoordinator(session).persist_actionable_evaluation(
                evaluation=decision,
                signal=value.signal,
                setup=value.setup,
                setup_transition=transition,
            )
    monkeypatch.undo()

    with Session(postgres_engine) as observer:
        assert PostgresArmedSetupRepository(observer).get(value.signal.signal_id) is None
        assert PostgresStateTransitionRepository(observer).get(transition.transition_id) is None

    with Session(postgres_engine) as session:
        PersistenceCoordinator(session).persist_actionable_evaluation(
            evaluation=decision,
            signal=value.signal,
            setup=value.setup,
            setup_transition=transition,
        )

    with Session(postgres_engine) as observer:
        setup = PostgresArmedSetupRepository(observer).get(value.signal.signal_id)
        assert setup is not None and setup.state is ArmedSetupState.ARMED
        assert (
            PostgresStateTransitionRepository(observer).get(transition.transition_id)
            == transition
        )


def test_trigger_rollback_can_retry_exactly_once(
    postgres_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    value = facts(f"sf052-trigger-{uuid4().hex[:8]}")
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
        after=2,
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
    monkeypatch.undo()

    with Session(postgres_engine) as session:
        PersistenceCoordinator(session).persist_trigger_intent(
            trigger=value.trigger,
            intent=value.intent,
            setup=triggered,
            setup_transition=transition,
        )

    with Session(postgres_engine) as observer:
        setup = PostgresArmedSetupRepository(observer).get(value.signal.signal_id)
        assert setup is not None and setup.state is ArmedSetupState.TRIGGERED
        assert (
            PostgresStateTransitionRepository(observer).get(transition.transition_id)
            == transition
        )


def test_expiry_rollback_can_retry_exactly_once(
    postgres_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    value = facts(f"sf052-expiry-{uuid4().hex[:8]}")
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
        cause_id="expiry-boundary",
        occurred_at=expired.valid_until,
    )

    _inject_after(
        monkeypatch,
        after=1,
        names=("PostgresArmedSetupRepository", "PostgresStateTransitionRepository"),
    )
    with Session(postgres_engine) as session:
        with pytest.raises(InjectedFailure):
            PersistenceCoordinator(session).persist_expiry(
                setup=expired,
                run_id=value.run.run_id,
                setup_transition=transition,
            )
    monkeypatch.undo()

    with Session(postgres_engine) as observer:
        setup = PostgresArmedSetupRepository(observer).get(value.signal.signal_id)
        assert setup is not None and setup.state is ArmedSetupState.ARMED

    with Session(postgres_engine) as session:
        PersistenceCoordinator(session).persist_expiry(
            setup=expired,
            run_id=value.run.run_id,
            setup_transition=transition,
        )

    with Session(postgres_engine) as observer:
        setup = PostgresArmedSetupRepository(observer).get(value.signal.signal_id)
        assert setup is not None and setup.state is ArmedSetupState.EXPIRED
        assert (
            PostgresStateTransitionRepository(observer).get(transition.transition_id)
            == transition
        )


def test_open_rollback_can_retry_exactly_once(
    postgres_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    value = facts(f"sf052-open-{uuid4().hex[:8]}")
    _commit_trigger_intent(postgres_engine, value)
    outcome = PositionOpenOutcome.create(
        fill_id=value.fill.fill_id,
        signal_id=value.signal.signal_id,
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
        after=4,
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
    monkeypatch.undo()

    with Session(postgres_engine) as observer:
        assert PostgresFillRepository(observer).get(value.fill.fill_id) is None
        assert PostgresTradeRepository(observer).get(value.trade.trade_id) is None
        assert PostgresPositionRepository(observer).get(value.position.position_id) is None

    with Session(postgres_engine) as session:
        PersistenceCoordinator(session).persist_opened_entry(
            fill=value.fill,
            outcome=outcome,
            trade=value.trade,
            position=value.position,
            trade_transition=trade_transition,
            position_transition=position_transition,
        )

    with Session(postgres_engine) as observer:
        trade = PostgresTradeRepository(observer).get(value.trade.trade_id)
        position = PostgresPositionRepository(observer).get(value.position.position_id)
        assert trade is not None and trade.state is TradeState.OPEN
        assert position is not None and position.state is PositionState.OPEN
        assert PostgresPositionOpenOutcomeRepository(observer).get(outcome.outcome_id) == outcome


def test_rejected_entry_rollback_can_retry_exactly_once(
    postgres_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    value = facts(f"sf052-reject-{uuid4().hex[:8]}")
    _commit_trigger_intent(postgres_engine, value)
    outcome = PositionOpenOutcome.create(
        fill_id=value.fill.fill_id,
        signal_id=value.signal.signal_id,
        outcome=PositionOpenOutcomeType.REJECTED_NON_POSITIVE_RISK,
        decided_at=value.fill.filled_at,
        run=value.run,
    )

    _inject_after(
        monkeypatch,
        after=1,
        names=("PostgresFillRepository", "PostgresPositionOpenOutcomeRepository"),
    )
    with Session(postgres_engine) as session:
        with pytest.raises(InjectedFailure):
            PersistenceCoordinator(session).persist_rejected_entry(
                fill=value.fill,
                outcome=outcome,
            )
    monkeypatch.undo()

    with Session(postgres_engine) as observer:
        assert PostgresFillRepository(observer).get(value.fill.fill_id) is None

    with Session(postgres_engine) as session:
        PersistenceCoordinator(session).persist_rejected_entry(
            fill=value.fill,
            outcome=outcome,
        )

    with Session(postgres_engine) as observer:
        assert PostgresFillRepository(observer).get(value.fill.fill_id) == value.fill
        assert PostgresPositionOpenOutcomeRepository(observer).get(outcome.outcome_id) == outcome
        assert PostgresTradeRepository(observer).find_for_run_instrument(
            value.run.run_id, value.signal.instrument_id
        ) == ()


def test_exit_rollback_can_retry_exactly_once(
    postgres_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    value = facts(f"sf052-exit-{uuid4().hex[:8]}")
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
        after=3,
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
    monkeypatch.undo()

    with Session(postgres_engine) as observer:
        trade = PostgresTradeRepository(observer).get(value.trade.trade_id)
        position = PostgresPositionRepository(observer).get(value.position.position_id)
        assert trade is not None and trade.state is TradeState.OPEN
        assert position is not None and position.state is PositionState.OPEN

    with Session(postgres_engine) as session:
        PersistenceCoordinator(session).persist_exit(
            exit_fact=value.exit_fact,
            trade=closed_trade,
            position=closed_position,
            trade_transition=trade_transition,
            position_transition=position_transition,
        )

    with Session(postgres_engine) as observer:
        trade = PostgresTradeRepository(observer).get(value.trade.trade_id)
        position = PostgresPositionRepository(observer).get(value.position.position_id)
        assert trade is not None and trade.state is TradeState.CLOSED
        assert position is not None and position.state is PositionState.CLOSED
