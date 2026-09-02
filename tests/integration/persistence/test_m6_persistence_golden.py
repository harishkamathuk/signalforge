import os
from collections.abc import Iterator
from dataclasses import replace
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from signalforge.domain.armed import ArmedSetupState
from signalforge.domain.audit import TransitionEntityType
from signalforge.domain.position_outcomes import PositionOpenOutcome, PositionOpenOutcomeType
from signalforge.domain.positions import PositionState
from signalforge.domain.trades import TradeState
from signalforge.persistence.coordinator import PersistenceCoordinator
from signalforge.persistence.repositories import (
    PostgresArmedSetupRepository,
    PostgresEntryIntentRepository,
    PostgresExitRepository,
    PostgresFillRepository,
    PostgresIndicatorCheckpointRepository,
    PostgresPositionOpenOutcomeRepository,
    PostgresPositionRepository,
    PostgresRunProvenanceRepository,
    PostgresSignalRepository,
    PostgresStateTransitionRepository,
    PostgresStrategyEvaluationRepository,
    PostgresTradeRepository,
    PostgresTriggerEventRepository,
)
from signalforge.runtime.indicators import IndicatorEngine
from tests.integration.persistence.test_repository_adapters_postgres import (
    _transition,
    facts,
)


@pytest.fixture(scope="module")
def postgres_engine() -> Iterator[Engine]:
    database_url = os.environ.get("DATABASE_URL")
    if database_url is None:
        pytest.fail("DATABASE_URL is required for PostgreSQL integration tests")
    engine = sa.create_engine(database_url)
    try:
        yield engine
    finally:
        engine.dispose()


def test_m6_complete_lifecycle_is_durable_and_idempotent(postgres_engine: Engine) -> None:
    value = facts(f"m6-{uuid4().hex[:8]}")
    checkpoint = IndicatorEngine(value.signal.instrument_id, "checkpoint-v1").state
    arm = _transition(
        value,
        entity=TransitionEntityType.ARMED_SETUP,
        entity_id=str(value.signal.signal_id),
        before="none",
        after="armed",
        cause_type="strategy_evaluation",
        cause_id="evaluation",
        occurred_at=value.setup.armed_at,
    )
    setup = replace(value.setup)
    setup.trigger(at=value.trigger.observed_at)
    trigger = _transition(
        value,
        entity=TransitionEntityType.ARMED_SETUP,
        entity_id=str(value.signal.signal_id),
        before="armed",
        after="triggered",
        cause_type="trigger_event",
        cause_id=str(value.trigger.trigger_event_id),
        occurred_at=value.trigger.observed_at,
    )
    outcome = PositionOpenOutcome.create(
        fill_id=value.fill.fill_id,
        signal_id=value.signal.signal_id,
        outcome=PositionOpenOutcomeType.OPENED,
        decided_at=value.fill.filled_at,
        run=value.run,
    )
    trade_open = _transition(
        value,
        entity=TransitionEntityType.TRADE,
        entity_id=str(value.trade.trade_id),
        before="none",
        after="open",
        cause_type="fill",
        cause_id=str(value.fill.fill_id),
        occurred_at=value.trade.opened_at,
    )
    position_open = _transition(
        value,
        entity=TransitionEntityType.POSITION,
        entity_id=str(value.position.position_id),
        before="none",
        after="open",
        cause_type="trade",
        cause_id=str(value.trade.trade_id),
        occurred_at=value.position.opened_at,
    )
    trade = replace(value.trade)
    trade.close(exit_id=value.exit_fact.exit_id, at=value.exit_fact.exited_at)
    position = replace(value.position)
    position.close(at=value.exit_fact.exited_at)
    trade_close = _transition(
        value,
        entity=TransitionEntityType.TRADE,
        entity_id=str(value.trade.trade_id),
        before="open",
        after="closed",
        cause_type="exit",
        cause_id=str(value.exit_fact.exit_id),
        occurred_at=value.exit_fact.exited_at,
    )
    position_close = _transition(
        value,
        entity=TransitionEntityType.POSITION,
        entity_id=str(value.position.position_id),
        before="open",
        after="closed",
        cause_type="exit",
        cause_id=str(value.exit_fact.exit_id),
        occurred_at=value.exit_fact.exited_at,
    )
    with Session(postgres_engine) as session:
        PostgresRunProvenanceRepository(session).add(value.run)
        session.commit()
        coordinator = PersistenceCoordinator(session)
        coordinator.persist_actionable_evaluation(
            evaluation=value.evaluation,
            signal=value.signal,
            setup=value.setup,
            setup_transition=arm,
            checkpoint=checkpoint,
        )
        coordinator.persist_trigger_intent(
            trigger=value.trigger, intent=value.intent, setup=setup, setup_transition=trigger
        )
        coordinator.persist_opened_entry(
            fill=value.fill,
            outcome=outcome,
            trade=value.trade,
            position=value.position,
            trade_transition=trade_open,
            position_transition=position_open,
        )
        coordinator.persist_exit(
            exit_fact=value.exit_fact,
            trade=trade,
            position=position,
            trade_transition=trade_close,
            position_transition=position_close,
        )
    with Session(postgres_engine) as observer:
        assert PostgresRunProvenanceRepository(observer).get(value.run.run_id) == value.run
        assert (
            PostgresStrategyEvaluationRepository(observer).get(
                value.run.run_id, value.evaluation.instrument_id, value.evaluation.interval
            )
            == value.evaluation
        )
        assert PostgresSignalRepository(observer).get(value.signal.signal_id) == value.signal
        assert (
            PostgresArmedSetupRepository(observer).get(value.signal.signal_id).state
            is ArmedSetupState.TRIGGERED
        )
        assert (
            PostgresTriggerEventRepository(observer).get(value.trigger.trigger_event_id)
            == value.trigger
        )
        assert (
            PostgresEntryIntentRepository(observer).get(value.intent.entry_intent_id)
            == value.intent
        )
        assert PostgresFillRepository(observer).get(value.fill.fill_id) == value.fill
        assert PostgresPositionOpenOutcomeRepository(observer).get(outcome.outcome_id) == outcome
        assert (
            PostgresTradeRepository(observer).get(value.trade.trade_id).state is TradeState.CLOSED
        )
        assert (
            PostgresPositionRepository(observer).get(value.position.position_id).state
            is PositionState.CLOSED
        )
        assert PostgresExitRepository(observer).get(value.exit_fact.exit_id) == value.exit_fact
        assert (
            PostgresIndicatorCheckpointRepository(observer).get(
                value.run.run_id, value.signal.instrument_id
            )
            == checkpoint
        )
        assert all(
            PostgresStateTransitionRepository(observer).get(item.transition_id) == item
            for item in (arm, trigger, trade_open, position_open, trade_close, position_close)
        )
