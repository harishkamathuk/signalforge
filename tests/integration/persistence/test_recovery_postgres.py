import os
from collections.abc import Iterator
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from signalforge.domain.armed import ArmedSetupState
from signalforge.domain.audit import TransitionEntityType
from signalforge.domain.market import CandleQuality, CompletedCandle
from signalforge.domain.money import Price
from signalforge.domain.position_outcomes import PositionOpenOutcome, PositionOpenOutcomeType
from signalforge.domain.positions import PositionState
from signalforge.domain.time import CandleInterval
from signalforge.domain.trades import TradeState
from signalforge.persistence.coordinator import PersistenceCoordinator
from signalforge.persistence.models import (
    ArmedSetupRecord,
    ExitRecord,
    FillRecord,
    IndicatorCheckpointRecord,
    PositionOpenOutcomeRecord,
    PositionRecord,
    RunRecord,
    SignalRecord,
    StateTransitionRecord,
    TradeRecord,
)
from signalforge.persistence.repositories import (
    PostgresIndicatorCheckpointRepository,
    PostgresPositionOpenOutcomeRepository,
    PostgresRunProvenanceRepository,
)
from signalforge.runtime.indicators import IndicatorEngine, IndicatorEngineState
from signalforge.runtime.recovery import RecoveryBootstrap, RecoveryDisposition
from tests.integration.persistence.test_repository_adapters_postgres import (
    Facts,
    _commit_armed_setup,
    _commit_open_position,
    _transition,
    facts,
)


def _checkpoint_state(value: Facts) -> IndicatorEngineState:
    engine = IndicatorEngine(value.signal.instrument_id, value.run.engine_calculation_version)
    for offset in range(40):
        close = Decimal("100.12345678901234567890") + Decimal(offset) / Decimal(
            "10000000000000000000"
        )
        engine.update(
            CompletedCandle(
                instrument_id=value.signal.instrument_id,
                interval=CandleInterval.five_minutes(
                    value.evaluation.interval.start + timedelta(minutes=5 * offset)
                ),
                quality=CandleQuality.VALID,
                open=Price(close - Decimal("0.01")),
                high=Price(close + Decimal("0.02")),
                low=Price(close - Decimal("0.03")),
                close=Price(close),
                volume=100 + offset,
                source="recovery-test",
                source_event_count=1,
            )
        )
    return engine.state


def _durable_counts(session: Session) -> dict[str, int]:
    records = (
        RunRecord,
        SignalRecord,
        ArmedSetupRecord,
        FillRecord,
        PositionOpenOutcomeRecord,
        TradeRecord,
        PositionRecord,
        ExitRecord,
        StateTransitionRecord,
        IndicatorCheckpointRecord,
    )
    return {
        record.__tablename__: session.scalar(sa.select(sa.func.count()).select_from(record)) or 0
        for record in records
    }


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


def test_recovery_postgres_clean_and_pre_checkpoint_run_are_read_only(
    postgres_engine: Engine,
) -> None:
    value = facts(f"recovery-{uuid4().hex[:8]}")
    bootstrap = RecoveryBootstrap()
    with Session(postgres_engine) as session:
        result = bootstrap.inspect(
            session=session, requested_run=value.run, instrument_id=value.signal.instrument_id
        )
        assert result.disposition is RecoveryDisposition.NEW
        assert not session.new and not session.dirty
    with Session(postgres_engine) as session:
        PostgresRunProvenanceRepository(session).add(value.run)
        session.commit()
    with Session(postgres_engine) as session:
        result = bootstrap.inspect(
            session=session, requested_run=value.run, instrument_id=value.signal.instrument_id
        )
        assert result.disposition is RecoveryDisposition.RESUMABLE
        assert result.indicator_state is None
        assert not session.new and not session.dirty


def test_recovery_postgres_discovers_armed_and_open_graphs(postgres_engine: Engine) -> None:
    armed = facts(f"recovery-armed-{uuid4().hex[:8]}")
    _commit_armed_setup(postgres_engine, armed)
    with Session(postgres_engine) as session:
        result = RecoveryBootstrap().inspect(
            session=session, requested_run=armed.run, instrument_id=armed.signal.instrument_id
        )
        assert result.lifecycle.setup is not None
        assert result.lifecycle.setup.state is ArmedSetupState.ARMED
        assert result.lifecycle.signal == armed.signal
    opened = facts(f"recovery-open-{uuid4().hex[:8]}")
    _commit_open_position(postgres_engine, opened)
    outcome = PositionOpenOutcome.create(
        fill_id=opened.fill.fill_id,
        signal_id=opened.signal.signal_id,
        outcome=PositionOpenOutcomeType.OPENED,
        decided_at=opened.fill.filled_at,
        run=opened.run,
    )
    with Session(postgres_engine) as session:
        PostgresPositionOpenOutcomeRepository(session).append(outcome)
        session.commit()
    with Session(postgres_engine) as session:
        result = RecoveryBootstrap().inspect(
            session=session, requested_run=opened.run, instrument_id=opened.signal.instrument_id
        )
        assert (
            result.lifecycle.trade is not None and result.lifecycle.trade.state is TradeState.OPEN
        )
        assert (
            result.lifecycle.position is not None
            and result.lifecycle.position.state is PositionState.OPEN
        )
        assert result.lifecycle.outcome is not None


def test_recovery_postgres_validates_closed_lifecycle(postgres_engine: Engine) -> None:
    value = facts(f"recovery-closed-{uuid4().hex[:8]}")
    _commit_open_position(postgres_engine, value)
    outcome = PositionOpenOutcome.create(
        fill_id=value.fill.fill_id,
        signal_id=value.signal.signal_id,
        outcome=PositionOpenOutcomeType.OPENED,
        decided_at=value.fill.filled_at,
        run=value.run,
    )
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
        PostgresPositionOpenOutcomeRepository(session).append(outcome)
        session.commit()
        PersistenceCoordinator(session).persist_exit(
            exit_fact=value.exit_fact,
            trade=closed_trade,
            position=closed_position,
            trade_transition=trade_transition,
            position_transition=position_transition,
        )
    with Session(postgres_engine) as session:
        result = RecoveryBootstrap().inspect(
            session=session, requested_run=value.run, instrument_id=value.signal.instrument_id
        )
        assert result.lifecycle.trade is None
        assert result.lifecycle.position is None
        assert result.lifecycle.exit_fact == value.exit_fact


def test_recovery_postgres_restores_exact_indicator_checkpoint(postgres_engine: Engine) -> None:
    value = facts(f"recovery-checkpoint-{uuid4().hex[:8]}")
    state = _checkpoint_state(value)
    with Session(postgres_engine) as session:
        PostgresRunProvenanceRepository(session).add(value.run)
        PostgresIndicatorCheckpointRepository(session).upsert(value.run, state)
        session.commit()
    with Session(postgres_engine) as session:
        result = RecoveryBootstrap().inspect(
            session=session, requested_run=value.run, instrument_id=value.signal.instrument_id
        )
    assert result.disposition is RecoveryDisposition.RESUMABLE
    assert result.indicator_state == state
    assert result.indicator_state is not None
    restored = result.indicator_state
    assert restored is not None
    assert restored.instrument_id == state.instrument_id
    assert restored.calculation_version == state.calculation_version
    assert restored.last_interval == state.last_interval
    assert restored.continuity == state.continuity
    assert restored.ema9 == state.ema9
    assert restored.ema20 == state.ema20
    assert restored.ema50 == state.ema50
    assert restored.rsi14 == state.rsi14
    assert restored.adx14 == state.adx14
    assert restored.macd == state.macd


def test_recovery_postgres_inspection_does_not_change_durable_graph(
    postgres_engine: Engine,
) -> None:
    value = facts(f"recovery-read-only-{uuid4().hex[:8]}")
    _commit_armed_setup(postgres_engine, value)
    with Session(postgres_engine) as session:
        before = _durable_counts(session)
    with Session(postgres_engine) as session:
        result = RecoveryBootstrap().inspect(
            session=session, requested_run=value.run, instrument_id=value.signal.instrument_id
        )
        assert result.disposition is RecoveryDisposition.RESUMABLE
    with Session(postgres_engine) as session:
        assert _durable_counts(session) == before
