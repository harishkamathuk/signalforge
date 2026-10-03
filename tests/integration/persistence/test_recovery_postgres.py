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
from signalforge.domain.indicators import EmaRequirement, IndicatorRequirements, RsiRequirement
from signalforge.domain.market import CandleQuality, CompletedCandle
from signalforge.domain.money import Price
from signalforge.domain.position_outcomes import PositionOpenOutcome, PositionOpenOutcomeType
from signalforge.domain.positions import PositionState
from signalforge.domain.time import CandleInterval
from signalforge.domain.trades import TradeState
from signalforge.persistence.coordinator import PersistenceCoordinator
from signalforge.persistence.errors import ContradictoryFactError
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
from signalforge.runtime.indicators import (
    V1_INDICATOR_REQUIREMENTS,
    IndicatorEngine,
    IndicatorEngineState,
)
from signalforge.runtime.recovery import RecoveryBootstrap, RecoveryDisposition
from tests.integration.persistence.test_repository_adapters_postgres import (
    Facts,
    _commit_armed_setup,
    _commit_open_position,
    _transition,
    facts,
)


def _checkpoint_state(value: Facts) -> IndicatorEngineState:
    engine = IndicatorEngine(
        value.signal.instrument_id,
        value.run.engine_calculation_version,
        requirements=V1_INDICATOR_REQUIREMENTS,
    )
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


def _persist_armed_graph(postgres_engine: Engine, value: Facts) -> None:
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
        PersistenceCoordinator(session).persist_actionable_evaluation(
            evaluation=value.decision_fact,
            signal=value.signal,
            setup=value.setup,
            setup_transition=transition,
        )


def _persist_open_graph(postgres_engine: Engine, value: Facts) -> PositionOpenOutcome:
    _persist_armed_graph(postgres_engine, value)
    triggered = replace(value.setup)
    triggered.trigger(at=value.trigger.observed_at)
    trigger_transition = _transition(
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
    with Session(postgres_engine) as session:
        coordinator = PersistenceCoordinator(session)
        coordinator.persist_trigger_intent(
            trigger=value.trigger,
            intent=value.intent,
            setup=triggered,
            setup_transition=trigger_transition,
        )
        coordinator.persist_opened_entry(
            fill=value.fill,
            outcome=outcome,
            trade=value.trade,
            position=value.position,
            trade_transition=trade_transition,
            position_transition=position_transition,
        )
    return outcome


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
            session=session,
            requested_run=value.run,
            instrument_id=value.signal.instrument_id,
            indicator_requirements=V1_INDICATOR_REQUIREMENTS,
        )
        assert result.disposition is RecoveryDisposition.NEW
        assert not session.new and not session.dirty
    with Session(postgres_engine) as session:
        PostgresRunProvenanceRepository(session).add(value.run)
        session.commit()
    with Session(postgres_engine) as session:
        result = bootstrap.inspect(
            session=session,
            requested_run=value.run,
            instrument_id=value.signal.instrument_id,
            indicator_requirements=V1_INDICATOR_REQUIREMENTS,
        )
        assert result.disposition is RecoveryDisposition.RESUMABLE
        assert result.indicator_state is None
        assert not session.new and not session.dirty


def test_recovery_postgres_discovers_armed_and_open_graphs(postgres_engine: Engine) -> None:
    armed = facts(f"recovery-armed-{uuid4().hex[:8]}")
    _persist_armed_graph(postgres_engine, armed)
    with Session(postgres_engine) as session:
        result = RecoveryBootstrap().inspect(
            session=session,
            requested_run=armed.run,
            instrument_id=armed.signal.instrument_id,
            indicator_requirements=V1_INDICATOR_REQUIREMENTS,
        )
        assert result.lifecycle.setup is not None
        assert result.lifecycle.setup.state is ArmedSetupState.ARMED
        assert result.lifecycle.signal == armed.signal
        assert len(result.lifecycle.transitions) == 1

    opened = facts(f"recovery-open-{uuid4().hex[:8]}")
    outcome = _persist_open_graph(postgres_engine, opened)
    with Session(postgres_engine) as session:
        result = RecoveryBootstrap().inspect(
            session=session,
            requested_run=opened.run,
            instrument_id=opened.signal.instrument_id,
            indicator_requirements=V1_INDICATOR_REQUIREMENTS,
        )
        assert result.lifecycle.setup is not None
        assert result.lifecycle.setup.state is ArmedSetupState.TRIGGERED
        assert result.lifecycle.signal == opened.signal
        assert result.lifecycle.trigger == opened.trigger
        assert result.lifecycle.intent == opened.intent
        assert result.lifecycle.fill == opened.fill
        assert result.lifecycle.outcome == outcome
        assert result.lifecycle.trade == opened.trade
        assert result.lifecycle.position == opened.position
        assert len(result.lifecycle.transitions) == 4


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
            session=session,
            requested_run=value.run,
            instrument_id=value.signal.instrument_id,
            indicator_requirements=V1_INDICATOR_REQUIREMENTS,
        )
        assert result.lifecycle.trade is not None
        assert result.lifecycle.trade.state is TradeState.CLOSED
        assert result.lifecycle.trade.trade_id == closed_trade.trade_id
        assert result.lifecycle.trade.exit_id == value.exit_fact.exit_id
        assert result.lifecycle.position is not None
        assert result.lifecycle.position.state is PositionState.CLOSED
        assert result.lifecycle.position.position_id == closed_position.position_id
        assert result.lifecycle.position.trade_id == closed_trade.trade_id
        assert result.lifecycle.outcome == outcome
        assert result.lifecycle.signal == value.signal
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
            session=session,
            requested_run=value.run,
            instrument_id=value.signal.instrument_id,
            indicator_requirements=V1_INDICATOR_REQUIREMENTS,
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
    _persist_armed_graph(postgres_engine, value)
    with Session(postgres_engine) as session:
        before = _durable_counts(session)
    with Session(postgres_engine) as session:
        result = RecoveryBootstrap().inspect(
            session=session,
            requested_run=value.run,
            instrument_id=value.signal.instrument_id,
            indicator_requirements=V1_INDICATOR_REQUIREMENTS,
        )
        assert result.disposition is RecoveryDisposition.RESUMABLE
    with Session(postgres_engine) as session:
        assert _durable_counts(session) == before



def test_recovery_postgres_restores_rsi_only_checkpoint_and_validates_requirements(
    postgres_engine: Engine,
) -> None:
    value = facts(f"recovery-rsi-only-{uuid4().hex[:8]}")
    requirements = IndicatorRequirements.of(RsiRequirement(14))
    engine = IndicatorEngine(
        value.signal.instrument_id,
        value.run.engine_calculation_version,
        requirements=requirements,
    )
    for offset in range(20):
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
                open=Price(close),
                high=Price(close + Decimal("0.02")),
                low=Price(close - Decimal("0.03")),
                close=Price(close),
                volume=100 + offset,
                source="recovery-rsi-only",
                source_event_count=1,
            )
        )
    state = engine.state

    with Session(postgres_engine) as session:
        PostgresRunProvenanceRepository(session).add(value.run)
        PostgresIndicatorCheckpointRepository(session).upsert(value.run, state)
        session.commit()

    with Session(postgres_engine) as session:
        matched = RecoveryBootstrap().inspect(
            session=session,
            requested_run=value.run,
            instrument_id=value.signal.instrument_id,
            indicator_requirements=requirements,
        )
        assert matched.indicator_state == state
        assert matched.indicator_state is not None
        assert matched.indicator_state.ema_states == ()
        assert matched.indicator_state.adx_state is None
        assert matched.indicator_state.macd_state is None
        restored_state = matched.indicator_state

    next_offset = 20
    next_close = Decimal("100.12345678901234567890") + Decimal(next_offset) / Decimal(
        "10000000000000000000"
    )
    next_candle = CompletedCandle(
        instrument_id=value.signal.instrument_id,
        interval=CandleInterval.five_minutes(
            value.evaluation.interval.start + timedelta(minutes=5 * next_offset)
        ),
        quality=CandleQuality.VALID,
        open=Price(next_close),
        high=Price(next_close + Decimal("0.02")),
        low=Price(next_close - Decimal("0.03")),
        close=Price(next_close),
        volume=100 + next_offset,
        source="recovery-rsi-only",
        source_event_count=1,
    )
    expected = engine.update(next_candle)
    resumed = IndicatorEngine(
        value.signal.instrument_id,
        value.run.engine_calculation_version,
        requirements=requirements,
        state=restored_state,
    )
    actual = resumed.update(next_candle)
    assert actual == expected
    assert resumed.state == engine.state

    with Session(postgres_engine) as session:
        with pytest.raises(
            ContradictoryFactError,
            match="checkpoint requirements contradict requested strategy",
        ):
            RecoveryBootstrap().inspect(
                session=session,
                requested_run=value.run,
                instrument_id=value.signal.instrument_id,
                indicator_requirements=IndicatorRequirements.of(
                    RsiRequirement(14),
                    EmaRequirement(9),
                ),
            )
