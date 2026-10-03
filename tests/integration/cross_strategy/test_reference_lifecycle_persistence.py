from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from signalforge.config.rsi_mean_reversion_v1 import RsiMeanReversionV1Config
from signalforge.domain.audit import TransitionEntityType
from signalforge.domain.ids import InstrumentId, RunId
from signalforge.domain.instruments import TickSizeRule, TickSizeSchedule
from signalforge.domain.market import CompletedCandle, MarketEvent
from signalforge.domain.money import Price, Quantity
from signalforge.domain.position_outcomes import PositionOpenOutcome, PositionOpenOutcomeType
from signalforge.domain.provenance import RunIdentity
from signalforge.domain.time import IST
from signalforge.persistence.coordinator import PersistenceCoordinator
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
    PostgresStrategyDecisionRepository,
    PostgresTradeRepository,
    PostgresTriggerEventRepository,
)
from signalforge.runtime.decision_audit import project_rsi_mean_reversion_decision
from signalforge.runtime.eligibility import MarketDataFeedState
from signalforge.runtime.indicators import IndicatorContinuity
from signalforge.runtime.lifecycle import LifecycleState
from signalforge.runtime.replay import InMemoryReplaySource
from signalforge.runtime.replay_runtime import ReplayRuntime
from signalforge.runtime.rsi_mean_reversion_v1 import RsiMeanReversionV1Strategy
from signalforge.runtime.strategy import StrategyRuntimeFacts

INSTRUMENT = InstrumentId("NSE:SF066REF")


@pytest.fixture(scope="module")
def postgres_engine() -> Iterator[Engine]:
    url = os.environ.get("DATABASE_URL")
    if url is None:
        pytest.fail("DATABASE_URL is required for reference lifecycle persistence test")
    engine = sa.create_engine(url)
    try:
        yield engine
    finally:
        engine.dispose()


def _event(at: datetime, price: str, suffix: str) -> MarketEvent:
    return MarketEvent(
        instrument_id=INSTRUMENT,
        exchange_timestamp=at,
        received_timestamp=at + timedelta(milliseconds=1),
        price=Price(Decimal(price)),
        quantity=1,
        source="sf066-reference",
        source_event_id=f"{suffix}-{at.isoformat()}",
    )


def _events() -> tuple[MarketEvent, ...]:
    start = datetime(2026, 10, 3, 10, 0, tzinfo=IST)
    values = [
        _event(start + timedelta(minutes=5 * index), str(100 - index), f"warmup-{index}")
        for index in range(14)
    ]
    values.extend(
        (
            _event(start + timedelta(minutes=70), "85.97", "signal-low"),
            _event(start + timedelta(minutes=74), "86.03", "signal-close"),
            _event(start + timedelta(minutes=75), "85.90", "arm-boundary"),
            _event(start + timedelta(minutes=76), "86.10", "trigger"),
            _event(start + timedelta(minutes=77), "86.30", "target"),
        )
    )
    return tuple(values)


def _facts(_candle: CompletedCandle) -> StrategyRuntimeFacts:
    return StrategyRuntimeFacts(
        completed_regular_session_candles=250,
        continuity=IndicatorContinuity.HEALTHY,
        feed_state=MarketDataFeedState.HEALTHY,
    )


def _transition(runtime: ReplayRuntime, entity: TransitionEntityType, before: str, after: str):
    matches = [
        item
        for item in runtime.lifecycle.audit_transitions
        if item.entity_type is entity
        and item.from_state == before
        and item.to_state == after
    ]
    assert len(matches) == 1
    return matches[0]


def test_reference_full_lifecycle_persists_through_shared_repositories(
    postgres_engine: Engine,
) -> None:
    strategy = RsiMeanReversionV1Strategy(RsiMeanReversionV1Config())
    run = RunIdentity(
        run_id=RunId(f"sf066-reference-{uuid4().hex}"),
        strategy=strategy.identity,
        config_id=strategy.config_identity.config_id,
        config_hash=strategy.config_identity.config_hash,
        engine_calculation_version="engine-v1",
    )
    source = InMemoryReplaySource(instrument_id=INSTRUMENT, events=_events())
    runtime = ReplayRuntime(
        source=source,
        run=run,
        tick_schedule=TickSizeSchedule(
            instrument_id=INSTRUMENT,
            rules=(TickSizeRule(Price(Decimal("0.10")), date(2026, 1, 1)),),
        ),
        quantity=Quantity(10),
        strategy=strategy,
        evaluation_context_factory=_facts,
    )

    with Session(postgres_engine) as session:
        PostgresRunProvenanceRepository(session).add(run)
        session.commit()
        coordinator = PersistenceCoordinator(session)
        arm_persisted = False
        open_persisted = False
        exit_persisted = False

        for replay_input in source:
            step = runtime.process_input(replay_input)
            if step.evaluation is not None:
                fact = project_rsi_mean_reversion_decision(step.evaluation)
                if step.evaluation.actionable and step.lifecycle.arming is not None:
                    coordinator.persist_actionable_evaluation(
                        evaluation=fact,
                        signal=step.lifecycle.arming.signal,
                        setup=step.lifecycle.arming.armed_setup,
                        setup_transition=_transition(
                            runtime,
                            TransitionEntityType.ARMED_SETUP,
                            "none",
                            "armed",
                        ),
                        checkpoint=runtime.indicator_engine.state,
                    )
                    arm_persisted = True
                else:
                    coordinator.persist_completed_evaluation(
                        run=run,
                        state=runtime.indicator_engine.state,
                        evaluation=fact,
                    )

            if (
                runtime.lifecycle.state is LifecycleState.OPEN
                and not open_persisted
            ):
                snapshot = runtime.lifecycle.snapshot()
                assert snapshot.arming is not None
                assert snapshot.execution is not None
                assert snapshot.open_result is not None
                assert snapshot.open_result.trade is not None
                assert snapshot.open_result.position is not None
                trigger = runtime.lifecycle.signal_lifecycle.trigger_event
                assert trigger is not None
                coordinator.persist_trigger_intent(
                    trigger=trigger,
                    intent=snapshot.execution.entry_intent,
                    setup=snapshot.arming.armed_setup,
                    setup_transition=_transition(
                        runtime,
                        TransitionEntityType.ARMED_SETUP,
                        "armed",
                        "triggered",
                    ),
                )
                outcome = PositionOpenOutcome.create(
                    fill_id=snapshot.execution.fill.fill_id,
                    signal_id=snapshot.execution.fill.signal_id,
                    outcome=PositionOpenOutcomeType.OPENED,
                    decided_at=snapshot.execution.fill.filled_at,
                    run=run,
                )
                coordinator.persist_opened_entry(
                    fill=snapshot.execution.fill,
                    outcome=outcome,
                    trade=snapshot.open_result.trade,
                    position=snapshot.open_result.position,
                    trade_transition=_transition(
                        runtime,
                        TransitionEntityType.TRADE,
                        "none",
                        "open",
                    ),
                    position_transition=_transition(
                        runtime,
                        TransitionEntityType.POSITION,
                        "none",
                        "open",
                    ),
                )
                open_persisted = True

            if runtime.lifecycle.state is LifecycleState.CLOSED and not exit_persisted:
                snapshot = runtime.lifecycle.snapshot()
                assert snapshot.exit is not None
                assert snapshot.open_result is not None
                assert snapshot.open_result.trade is not None
                assert snapshot.open_result.position is not None
                coordinator.persist_exit(
                    exit_fact=snapshot.exit,
                    trade=snapshot.open_result.trade,
                    position=snapshot.open_result.position,
                    trade_transition=_transition(
                        runtime,
                        TransitionEntityType.TRADE,
                        "open",
                        "closed",
                    ),
                    position_transition=_transition(
                        runtime,
                        TransitionEntityType.POSITION,
                        "open",
                        "closed",
                    ),
                )
                exit_persisted = True

    assert arm_persisted and open_persisted and exit_persisted
    snapshot = runtime.lifecycle.snapshot()
    assert snapshot.arming is not None
    assert snapshot.execution is not None
    assert snapshot.open_result is not None
    assert snapshot.open_result.trade is not None
    assert snapshot.open_result.position is not None
    assert snapshot.exit is not None

    with Session(postgres_engine) as session:
        assert PostgresRunProvenanceRepository(session).get(run.run_id) == run
        assert (
            PostgresSignalRepository(session).get(snapshot.arming.signal.signal_id)
            == snapshot.arming.signal
        )
        assert (
            PostgresArmedSetupRepository(session).get(snapshot.arming.signal.signal_id)
            == snapshot.arming.armed_setup
        )
        trigger = runtime.lifecycle.signal_lifecycle.trigger_event
        assert trigger is not None
        assert PostgresTriggerEventRepository(session).get(trigger.trigger_event_id) == trigger
        assert (
            PostgresEntryIntentRepository(session).get(
                snapshot.execution.entry_intent.entry_intent_id
            )
            == snapshot.execution.entry_intent
        )
        assert PostgresFillRepository(session).get(snapshot.execution.fill.fill_id) == (
            snapshot.execution.fill
        )
        outcome_rows = PostgresPositionOpenOutcomeRepository(
            session
        ).find_for_run_instrument(run.run_id, INSTRUMENT)
        assert len(outcome_rows) == 1
        assert outcome_rows[0].outcome is PositionOpenOutcomeType.OPENED
        assert PostgresTradeRepository(session).get(
            snapshot.open_result.trade.trade_id
        ) == snapshot.open_result.trade
        assert PostgresPositionRepository(session).get(
            snapshot.open_result.position.position_id
        ) == snapshot.open_result.position
        assert PostgresExitRepository(session).get(snapshot.exit.exit_id) == snapshot.exit
        transitions = PostgresStateTransitionRepository(session).find_for_run(run.run_id)
        assert len(transitions) == 6
        decision = PostgresStrategyDecisionRepository(session).get(
            run.run_id,
            INSTRUMENT,
            snapshot.arming.signal.interval,
        )
        assert decision is not None
        assert decision.decision_kind == "rsi_mean_reversion_v1.evaluation.v1"
