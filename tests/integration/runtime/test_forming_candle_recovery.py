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

from signalforge.config.strategy_v1 import StrategyV1EvaluationConfig
from signalforge.domain.audit import TransitionEntityType
from signalforge.domain.ids import InstrumentId, RunId
from signalforge.domain.instruments import TickSizeRule, TickSizeSchedule
from signalforge.domain.market import CandleQuality, CompletedCandle, MarketEvent
from signalforge.domain.money import Price, Quantity
from signalforge.domain.provenance import RunIdentity
from signalforge.domain.strategy import (
    DecisionReason,
    MomentumResult,
    SetupResult,
    StrategyEvaluation,
    TrendResult,
)
from signalforge.domain.time import IST, CandleInterval
from signalforge.persistence.coordinator import PersistenceCoordinator
from signalforge.persistence.repositories import (
    PostgresExitRepository,
    PostgresFillRepository,
    PostgresMarketInputCheckpointRepository,
    PostgresPositionRepository,
    PostgresRunProvenanceRepository,
    PostgresTradeRepository,
    PostgresTriggerEventRepository,
)
from signalforge.runtime.candles import CandleEngine
from signalforge.runtime.decision_audit import project_v1_decision
from signalforge.runtime.indicator_recovery import IndicatorRecoveryReconciler
from signalforge.runtime.indicators import IndicatorEngine
from signalforge.runtime.lifecycle import LifecycleCoordinator, LifecycleState
from signalforge.runtime.lifecycle_recovery import LifecycleRecoveryHydrator
from signalforge.runtime.recovery import RecoveryBootstrap
from signalforge.runtime.replay import InMemoryReplaySource
from signalforge.runtime.replay_runtime import ReplayRuntime
from signalforge.runtime.restart_safe_replay import RestartSafeReplayRuntime
from signalforge.runtime.strategy import StrategyRuntimeFacts
from signalforge.runtime.strategy_v1 import IntradayMomentumV1Strategy

INSTRUMENT = InstrumentId("NSE:SF067GOLDEN")


@pytest.fixture(scope="module")
def postgres_engine() -> Iterator[Engine]:
    url = os.environ.get("DATABASE_URL")
    if url is None:
        pytest.fail("DATABASE_URL is required")
    engine = sa.create_engine(url)
    try:
        yield engine
    finally:
        engine.dispose()


def _strategy() -> IntradayMomentumV1Strategy:
    return IntradayMomentumV1Strategy(StrategyV1EvaluationConfig())


def _run(strategy: IntradayMomentumV1Strategy, suffix: str) -> RunIdentity:
    return RunIdentity(
        run_id=RunId(f"sf067-golden-{suffix}"),
        strategy=strategy.identity,
        config_id=strategy.config_identity.config_id,
        config_hash=strategy.config_identity.config_hash,
        engine_calculation_version="engine-v1",
    )


def _schedule() -> TickSizeSchedule:
    return TickSizeSchedule(
        instrument_id=INSTRUMENT,
        rules=(TickSizeRule(Price(Decimal("0.05")), date(2026, 1, 1)),),
    )


def _context(_candle: CompletedCandle) -> StrategyRuntimeFacts:
    from signalforge.runtime.eligibility import MarketDataFeedState
    from signalforge.runtime.indicators import IndicatorContinuity

    return StrategyRuntimeFacts(
        completed_regular_session_candles=250,
        continuity=IndicatorContinuity.HEALTHY,
        feed_state=MarketDataFeedState.HEALTHY,
    )


def _signal_candle() -> CompletedCandle:
    interval = CandleInterval.five_minutes(datetime(2026, 10, 4, 10, 0, tzinfo=IST))
    return CompletedCandle(
        instrument_id=INSTRUMENT,
        interval=interval,
        quality=CandleQuality.VALID,
        open=Price(Decimal("100")),
        high=Price(Decimal("102")),
        low=Price(Decimal("100")),
        close=Price(Decimal("101")),
        volume=100,
        source="sf067-golden",
        source_event_count=10,
    )


def _actionable_evaluation() -> StrategyEvaluation:
    candle = _signal_candle()
    return StrategyEvaluation(
        instrument_id=INSTRUMENT,
        interval=candle.interval,
        trend=TrendResult(True),
        momentum=MomentumResult(True, True, True, None),
        setup=SetupResult(True),
        qualified=True,
        actionable=True,
        reasons=(DecisionReason.QUALIFIED, DecisionReason.ACTIONABLE),
    )


def _events() -> tuple[MarketEvent, MarketEvent]:
    first_at = datetime(2026, 10, 4, 10, 6, tzinfo=IST)
    second_at = first_at + timedelta(minutes=1)
    return (
        MarketEvent(
            instrument_id=INSTRUMENT,
            exchange_timestamp=first_at,
            received_timestamp=first_at + timedelta(milliseconds=1),
            price=Price(Decimal("102")),
            quantity=5,
            source="sf067-golden",
            source_event_id="sf067-trigger",
        ),
        MarketEvent(
            instrument_id=INSTRUMENT,
            exchange_timestamp=second_at,
            received_timestamp=second_at + timedelta(milliseconds=1),
            price=Price(Decimal("999")),
            quantity=7,
            source="sf067-golden",
            source_event_id="sf067-exit",
        ),
    )


def _persist_armed(
    postgres_engine: Engine,
    run: RunIdentity,
    coordinator: LifecycleCoordinator,
) -> None:
    evaluation = _actionable_evaluation()
    snapshot = coordinator.process_evaluation(_signal_candle(), evaluation)
    assert snapshot.state is LifecycleState.ARMED
    assert snapshot.arming is not None
    transition = next(
        item
        for item in coordinator.audit_transitions
        if item.entity_type is TransitionEntityType.ARMED_SETUP
    )
    with Session(postgres_engine) as session:
        PostgresRunProvenanceRepository(session).add(run)
        session.commit()
        PersistenceCoordinator(session).persist_actionable_evaluation(
            evaluation=project_v1_decision(evaluation),
            signal=snapshot.arming.signal,
            setup=snapshot.arming.armed_setup,
            setup_transition=transition,
        )


def _runtime(
    *,
    source: InMemoryReplaySource,
    run: RunIdentity,
    strategy: IntradayMomentumV1Strategy,
    candle_engine: CandleEngine | None = None,
    indicator_engine: IndicatorEngine | None = None,
    lifecycle: LifecycleCoordinator | None = None,
) -> ReplayRuntime:
    return ReplayRuntime(
        source=source,
        run=run,
        tick_schedule=_schedule(),
        quantity=Quantity(10),
        strategy=strategy,
        evaluation_context_factory=_context,
        candle_engine=candle_engine,
        indicator_engine=indicator_engine,
        lifecycle=lifecycle,
    )


def _recover_runtime(
    postgres_engine: Engine,
    *,
    source: InMemoryReplaySource,
    run: RunIdentity,
    strategy: IntradayMomentumV1Strategy,
) -> RestartSafeReplayRuntime:
    with Session(postgres_engine) as session:
        recovered = RecoveryBootstrap().inspect(
            session=session,
            requested_run=run,
            instrument_id=INSTRUMENT,
            indicator_requirements=strategy.indicator_requirements,
        )
    assert recovered.market_input_checkpoint is not None
    market_checkpoint = recovered.market_input_checkpoint

    if recovered.indicator_state is None:
        indicator_engine = IndicatorEngine(
            INSTRUMENT,
            run.engine_calculation_version,
            requirements=strategy.indicator_requirements,
        )
        indicator_result = IndicatorRecoveryReconciler(indicator_engine.state).reconcile(())
    else:
        indicator_result = IndicatorRecoveryReconciler(
            recovered.indicator_state
        ).reconcile(())

    lifecycle = LifecycleCoordinator(
        run=run,
        tick_schedule=_schedule(),
        quantity=Quantity(10),
        strategy=strategy,
    )
    LifecycleRecoveryHydrator().hydrate(
        indicator_result=indicator_result,
        recovered=recovered.lifecycle,
        coordinator=lifecycle,
    )
    runtime = _runtime(
        source=source,
        run=run,
        strategy=strategy,
        candle_engine=CandleEngine(
            instrument_id=INSTRUMENT,
            state=market_checkpoint.candle_state,
        ),
        indicator_engine=indicator_result.engine,
        lifecycle=lifecycle,
    )
    return RestartSafeReplayRuntime(
        runtime=runtime,
        session_factory=lambda: Session(postgres_engine),
        decision_projector=project_v1_decision,
        checkpoint=market_checkpoint,
    )


def test_trigger_open_and_exit_survive_restart_without_duplicate_market_effects(
    postgres_engine: Engine,
) -> None:
    strategy = _strategy()
    run = _run(strategy, uuid4().hex[:8])
    source = InMemoryReplaySource(instrument_id=INSTRUMENT, events=_events())
    initial_lifecycle = LifecycleCoordinator(
        run=run,
        tick_schedule=_schedule(),
        quantity=Quantity(10),
        strategy=strategy,
    )
    _persist_armed(postgres_engine, run, initial_lifecycle)
    runtime = _runtime(
        source=source,
        run=run,
        strategy=strategy,
        lifecycle=initial_lifecycle,
    )
    durable = RestartSafeReplayRuntime(
        runtime=runtime,
        session_factory=lambda: Session(postgres_engine),
        decision_projector=project_v1_decision,
    )
    inputs = tuple(source)

    opened = durable.process_input(inputs[0])
    assert not opened.duplicate
    assert opened.replay_step is not None
    assert opened.replay_step.lifecycle.state is LifecycleState.OPEN

    recovered_open = _recover_runtime(
        postgres_engine,
        source=source,
        run=run,
        strategy=strategy,
    )
    duplicate_trigger = recovered_open.process_input(inputs[0])
    assert duplicate_trigger.duplicate
    assert recovered_open.runtime.lifecycle.state is LifecycleState.OPEN

    closed = recovered_open.process_input(inputs[1])
    assert not closed.duplicate
    assert closed.replay_step is not None
    assert closed.replay_step.lifecycle.state is LifecycleState.CLOSED

    recovered_closed = _recover_runtime(
        postgres_engine,
        source=source,
        run=run,
        strategy=strategy,
    )
    duplicate_exit = recovered_closed.process_input(inputs[1])
    assert duplicate_exit.duplicate
    assert recovered_closed.runtime.lifecycle.state is LifecycleState.IDLE

    with Session(postgres_engine) as observer:
        assert len(
            PostgresTriggerEventRepository(observer).find_for_run_instrument(
                run.run_id, INSTRUMENT
            )
        ) == 1
        assert len(
            PostgresFillRepository(observer).find_for_run_instrument(
                run.run_id, INSTRUMENT
            )
        ) == 1
        trades = PostgresTradeRepository(observer).find_for_run_instrument(
            run.run_id, INSTRUMENT
        )
        positions = PostgresPositionRepository(observer).find_for_run_instrument(
            run.run_id, INSTRUMENT
        )
        exits = PostgresExitRepository(observer).find_for_run_instrument(
            run.run_id, INSTRUMENT
        )
        assert len(trades) == len(positions) == len(exits) == 1
        assert trades[0].state.value == "closed"
        checkpoint = PostgresMarketInputCheckpointRepository(observer).get(
            run.run_id, INSTRUMENT
        )
        assert checkpoint is not None
        assert checkpoint.last_input.sequence == 1
