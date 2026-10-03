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
from signalforge.persistence.errors import ContradictoryFactError
from signalforge.persistence.repositories import (
    PostgresRunProvenanceRepository,
)
from signalforge.runtime.indicators import V1_INDICATOR_REQUIREMENTS, IndicatorEngine
from signalforge.runtime.recovery import RecoveryBootstrap, RecoveryDisposition
from tests.integration.persistence.test_recovery_postgres import (
    _persist_armed_graph,
    _persist_open_graph,
)
from tests.integration.persistence.test_repository_adapters_postgres import (
    _commit_trigger_intent,
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


def _inspect(postgres_engine: Engine, value):
    with Session(postgres_engine) as session:
        return RecoveryBootstrap().inspect(
            session=session,
            requested_run=value.run,
            instrument_id=value.signal.instrument_id,
            indicator_requirements=V1_INDICATOR_REQUIREMENTS,
        )


def test_crash_after_completed_evaluation_is_resumable_without_invented_lifecycle(
    postgres_engine: Engine,
) -> None:
    value = facts(f"sf052-eval-boundary-{uuid4().hex[:8]}")
    checkpoint = IndicatorEngine(
        value.signal.instrument_id,
        value.run.engine_calculation_version,
        requirements=V1_INDICATOR_REQUIREMENTS,
    ).state
    with Session(postgres_engine) as session:
        PostgresRunProvenanceRepository(session).add(value.run)
        session.commit()
        PersistenceCoordinator(session).persist_completed_evaluation(
            run=value.run,
            state=checkpoint,
            evaluation=value.decision_fact,
        )

    recovered = _inspect(postgres_engine, value)

    assert recovered.disposition is RecoveryDisposition.RESUMABLE
    assert recovered.indicator_state == checkpoint
    assert recovered.lifecycle.signal is None
    assert recovered.lifecycle.setup is None
    assert recovered.lifecycle.trade is None
    assert recovered.lifecycle.position is None


def test_crash_after_armed_commit_is_resumable_as_armed(
    postgres_engine: Engine,
) -> None:
    value = facts(f"sf052-armed-boundary-{uuid4().hex[:8]}")
    _persist_armed_graph(postgres_engine, value)

    recovered = _inspect(postgres_engine, value)

    assert recovered.disposition is RecoveryDisposition.RESUMABLE
    assert recovered.lifecycle.signal == value.signal
    assert recovered.lifecycle.setup is not None
    assert recovered.lifecycle.setup.state is ArmedSetupState.ARMED
    assert recovered.lifecycle.trade is None
    assert recovered.lifecycle.position is None


def test_crash_after_trigger_intent_commit_fails_closed(
    postgres_engine: Engine,
) -> None:
    value = facts(f"sf052-trigger-boundary-{uuid4().hex[:8]}")
    _commit_trigger_intent(postgres_engine, value)

    with pytest.raises(
        ContradictoryFactError,
        match="pending triggered entry cannot be resumed safely",
    ):
        _inspect(postgres_engine, value)


def test_crash_after_open_commit_is_resumable_as_open(
    postgres_engine: Engine,
) -> None:
    value = facts(f"sf052-open-boundary-{uuid4().hex[:8]}")
    outcome = _persist_open_graph(postgres_engine, value)

    recovered = _inspect(postgres_engine, value)

    assert recovered.disposition is RecoveryDisposition.RESUMABLE
    assert recovered.lifecycle.fill == value.fill
    assert recovered.lifecycle.outcome == outcome
    assert recovered.lifecycle.trade is not None
    assert recovered.lifecycle.trade.state is TradeState.OPEN
    assert recovered.lifecycle.position is not None
    assert recovered.lifecycle.position.state is PositionState.OPEN


def test_crash_after_rejected_entry_commit_is_terminal_non_open(
    postgres_engine: Engine,
) -> None:
    value = facts(f"sf052-rejected-boundary-{uuid4().hex[:8]}")
    _commit_trigger_intent(postgres_engine, value)
    outcome = PositionOpenOutcome.create(
        fill_id=value.fill.fill_id,
        signal_id=value.signal.signal_id,
        outcome=PositionOpenOutcomeType.REJECTED_NON_POSITIVE_RISK,
        decided_at=value.fill.filled_at,
        run=value.run,
    )
    with Session(postgres_engine) as session:
        PersistenceCoordinator(session).persist_rejected_entry(
            fill=value.fill,
            outcome=outcome,
        )

    recovered = _inspect(postgres_engine, value)

    assert recovered.disposition is RecoveryDisposition.RESUMABLE
    assert recovered.lifecycle.trade is None
    assert recovered.lifecycle.position is None


def test_crash_after_expiry_commit_does_not_rearm(
    postgres_engine: Engine,
) -> None:
    value = facts(f"sf052-expiry-boundary-{uuid4().hex[:8]}")
    _persist_armed_graph(postgres_engine, value)
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
    with Session(postgres_engine) as session:
        PersistenceCoordinator(session).persist_expiry(
            setup=expired,
            run_id=value.run.run_id,
            setup_transition=transition,
        )

    recovered = _inspect(postgres_engine, value)

    assert recovered.disposition is RecoveryDisposition.RESUMABLE
    assert recovered.lifecycle.setup is None
    assert recovered.lifecycle.trade is None
    assert recovered.lifecycle.position is None


def test_crash_after_exit_commit_remains_closed(
    postgres_engine: Engine,
) -> None:
    value = facts(f"sf052-exit-boundary-{uuid4().hex[:8]}")
    _persist_open_graph(postgres_engine, value)
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
    with Session(postgres_engine) as session:
        PersistenceCoordinator(session).persist_exit(
            exit_fact=value.exit_fact,
            trade=closed_trade,
            position=closed_position,
            trade_transition=trade_transition,
            position_transition=position_transition,
        )

    recovered = _inspect(postgres_engine, value)

    assert recovered.disposition is RecoveryDisposition.RESUMABLE
    assert recovered.lifecycle.trade is not None
    assert recovered.lifecycle.trade.state is TradeState.CLOSED
    assert recovered.lifecycle.position is not None
    assert recovered.lifecycle.position.state is PositionState.CLOSED
    assert recovered.lifecycle.exit_fact == value.exit_fact
