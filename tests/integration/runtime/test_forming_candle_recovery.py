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


def _forming_events() -> tuple[MarketEvent, ...]:
    base = datetime(2026, 10, 4, 11, 0, tzinfo=IST)
    return tuple(
        MarketEvent(
            instrument_id=INSTRUMENT,
            exchange_timestamp=base + timedelta(minutes=minute),
            received_timestamp=base + timedelta(minutes=minute, milliseconds=1),
            price=Price(Decimal(price)),
            quantity=quantity,
            source="sf067-forming",
            source_event_id=f"forming-{minute}",
        )
        for minute, price, quantity in (
            (0, "100", 2),
            (1, "103", 3),
            (3, "99", 5),
            (5, "102", 7),
        )
    )


def test_mid_candle_restart_converges_to_exact_completed_candle_and_indicator_state(
    postgres_engine: Engine,
) -> None:
    strategy = _strategy()
    run = _run(strategy, f"forming-{uuid4().hex[:8]}")
    events = _forming_events()
    source = InMemoryReplaySource(instrument_id=INSTRUMENT, events=events)

    reference = _runtime(source=source, run=run, strategy=strategy)
    reference_steps = tuple(reference.process_input(item) for item in source)
    expected_candle = reference_steps[-1].completed_candle
    assert expected_candle is not None
    expected_indicator_state = reference.indicator_engine.state

    with Session(postgres_engine) as session:
        PostgresRunProvenanceRepository(session).add(run)
        session.commit()

    durable = RestartSafeReplayRuntime(
        runtime=_runtime(source=source, run=run, strategy=strategy),
        session_factory=lambda: Session(postgres_engine),
        decision_projector=project_v1_decision,
    )
    inputs = tuple(source)
    for item in inputs[:3]:
        result = durable.process_input(item)
        assert not result.duplicate
        assert result.replay_step is not None
        assert result.replay_step.completed_candle is None

    recovered = _recover_runtime(
        postgres_engine,
        source=source,
        run=run,
        strategy=strategy,
    )
    duplicate = recovered.process_input(inputs[2])
    assert duplicate.duplicate

    boundary = recovered.process_input(inputs[3])
    assert not boundary.duplicate
    assert boundary.replay_step is not None
    assert boundary.replay_step.completed_candle == expected_candle
    assert recovered.runtime.indicator_engine.state == expected_indicator_state

    with Session(postgres_engine) as observer:
        checkpoint = PostgresMarketInputCheckpointRepository(observer).get(
            run.run_id, INSTRUMENT
        )
        assert checkpoint is not None
        assert checkpoint.last_input.sequence == 3
        assert checkpoint.candle_state == recovered.runtime.candle_engine.state


def test_persistence_failure_terminalizes_mutated_runtime_and_rolls_back_checkpoint(
    postgres_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from signalforge.persistence.repositories import PostgresMarketInputCheckpointRepository

    strategy = _strategy()
    run = _run(strategy, f"failure-{uuid4().hex[:8]}")
    source = InMemoryReplaySource(
        instrument_id=INSTRUMENT,
        events=_forming_events()[:2],
    )
    with Session(postgres_engine) as session:
        PostgresRunProvenanceRepository(session).add(run)
        session.commit()

    original = PostgresMarketInputCheckpointRepository.upsert

    def fail_after_write(self, run_arg, checkpoint):
        original(self, run_arg, checkpoint)
        raise RuntimeError("injected market-input persistence failure")

    monkeypatch.setattr(PostgresMarketInputCheckpointRepository, "upsert", fail_after_write)

    durable = RestartSafeReplayRuntime(
        runtime=_runtime(source=source, run=run, strategy=strategy),
        session_factory=lambda: Session(postgres_engine),
        decision_projector=project_v1_decision,
    )
    inputs = tuple(source)
    with pytest.raises(RuntimeError, match="injected"):
        durable.process_input(inputs[0])
    assert durable.terminal

    with Session(postgres_engine) as observer:
        assert (
            PostgresMarketInputCheckpointRepository(observer).get(
                run.run_id, INSTRUMENT
            )
            is None
        )

    from signalforge.runtime.restart_safe_replay import RestartSafeReplayError

    with pytest.raises(RestartSafeReplayError, match="terminal"):
        durable.process_input(inputs[1])


def _recover_without_market_checkpoint(
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
    assert recovered.market_input_checkpoint is None
    indicator_engine = IndicatorEngine(
        INSTRUMENT,
        run.engine_calculation_version,
        requirements=strategy.indicator_requirements,
    )
    indicator_result = IndicatorRecoveryReconciler(indicator_engine.state).reconcile(())
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
        candle_engine=CandleEngine(instrument_id=INSTRUMENT),
        indicator_engine=indicator_result.engine,
        lifecycle=lifecycle,
    )
    return RestartSafeReplayRuntime(
        runtime=runtime,
        session_factory=lambda: Session(postgres_engine),
        decision_projector=project_v1_decision,
    )


def test_trigger_open_input_commit_rolls_back_as_one_unit_and_retries(
    postgres_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from signalforge.persistence.repositories import PostgresArmedSetupRepository

    strategy = _strategy()
    run = _run(strategy, f"atomic-{uuid4().hex[:8]}")
    source = InMemoryReplaySource(instrument_id=INSTRUMENT, events=_events())
    lifecycle = LifecycleCoordinator(
        run=run,
        tick_schedule=_schedule(),
        quantity=Quantity(10),
        strategy=strategy,
    )
    _persist_armed(postgres_engine, run, lifecycle)

    original = PostgresMarketInputCheckpointRepository.upsert

    def fail_after_checkpoint(self, run_arg, checkpoint):
        original(self, run_arg, checkpoint)
        raise RuntimeError("injected atomic input failure")

    monkeypatch.setattr(
        PostgresMarketInputCheckpointRepository,
        "upsert",
        fail_after_checkpoint,
    )
    durable = RestartSafeReplayRuntime(
        runtime=_runtime(
            source=source,
            run=run,
            strategy=strategy,
            lifecycle=lifecycle,
        ),
        session_factory=lambda: Session(postgres_engine),
        decision_projector=project_v1_decision,
    )
    first_input = tuple(source)[0]

    with pytest.raises(RuntimeError, match="atomic input failure"):
        durable.process_input(first_input)
    assert durable.terminal

    with Session(postgres_engine) as observer:
        setup_rows = PostgresArmedSetupRepository(observer).find_for_run_instrument(
            run.run_id,
            INSTRUMENT,
        )
        assert len(setup_rows) == 1
        assert setup_rows[0].state.value == "armed"
        assert (
            PostgresTriggerEventRepository(observer).find_for_run_instrument(
                run.run_id,
                INSTRUMENT,
            )
            == ()
        )
        assert (
            PostgresFillRepository(observer).find_for_run_instrument(
                run.run_id,
                INSTRUMENT,
            )
            == ()
        )
        assert (
            PostgresTradeRepository(observer).find_for_run_instrument(
                run.run_id,
                INSTRUMENT,
            )
            == ()
        )
        assert (
            PostgresMarketInputCheckpointRepository(observer).get(
                run.run_id,
                INSTRUMENT,
            )
            is None
        )

    monkeypatch.undo()
    recovered = _recover_without_market_checkpoint(
        postgres_engine,
        source=source,
        run=run,
        strategy=strategy,
    )
    retried = recovered.process_input(first_input)
    assert not retried.duplicate
    assert retried.replay_step is not None
    assert retried.replay_step.lifecycle.state is LifecycleState.OPEN

    with Session(postgres_engine) as observer:
        assert len(
            PostgresTriggerEventRepository(observer).find_for_run_instrument(
                run.run_id,
                INSTRUMENT,
            )
        ) == 1
        assert len(
            PostgresFillRepository(observer).find_for_run_instrument(
                run.run_id,
                INSTRUMENT,
            )
        ) == 1
        assert len(
            PostgresTradeRepository(observer).find_for_run_instrument(
                run.run_id,
                INSTRUMENT,
            )
        ) == 1


def test_exit_input_commit_rolls_back_as_one_unit_and_retries(
    postgres_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    strategy = _strategy()
    run = _run(strategy, f"exit-atomic-{uuid4().hex[:8]}")
    source = InMemoryReplaySource(instrument_id=INSTRUMENT, events=_events())
    lifecycle = LifecycleCoordinator(
        run=run,
        tick_schedule=_schedule(),
        quantity=Quantity(10),
        strategy=strategy,
    )
    _persist_armed(postgres_engine, run, lifecycle)
    durable = RestartSafeReplayRuntime(
        runtime=_runtime(
            source=source,
            run=run,
            strategy=strategy,
            lifecycle=lifecycle,
        ),
        session_factory=lambda: Session(postgres_engine),
        decision_projector=project_v1_decision,
    )
    inputs = tuple(source)
    opened = durable.process_input(inputs[0])
    assert opened.replay_step is not None
    assert opened.replay_step.lifecycle.state is LifecycleState.OPEN
    checkpoint_before_exit = opened.checkpoint

    original = PostgresMarketInputCheckpointRepository.upsert

    def fail_after_checkpoint(self, run_arg, checkpoint):
        original(self, run_arg, checkpoint)
        raise RuntimeError("injected exit input failure")

    monkeypatch.setattr(
        PostgresMarketInputCheckpointRepository,
        "upsert",
        fail_after_checkpoint,
    )
    with pytest.raises(RuntimeError, match="exit input failure"):
        durable.process_input(inputs[1])
    assert durable.terminal

    with Session(postgres_engine) as observer:
        trades = PostgresTradeRepository(observer).find_for_run_instrument(
            run.run_id,
            INSTRUMENT,
        )
        positions = PostgresPositionRepository(observer).find_for_run_instrument(
            run.run_id,
            INSTRUMENT,
        )
        assert len(trades) == len(positions) == 1
        assert trades[0].state.value == "open"
        assert positions[0].state.value == "open"
        assert (
            PostgresExitRepository(observer).find_for_run_instrument(
                run.run_id,
                INSTRUMENT,
            )
            == ()
        )
        persisted = PostgresMarketInputCheckpointRepository(observer).get(
            run.run_id,
            INSTRUMENT,
        )
        assert persisted == checkpoint_before_exit

    monkeypatch.undo()
    recovered = _recover_runtime(
        postgres_engine,
        source=source,
        run=run,
        strategy=strategy,
    )
    retried = recovered.process_input(inputs[1])
    assert retried.replay_step is not None
    assert retried.replay_step.lifecycle.state is LifecycleState.CLOSED
    with Session(postgres_engine) as observer:
        assert len(
            PostgresExitRepository(observer).find_for_run_instrument(
                run.run_id,
                INSTRUMENT,
            )
        ) == 1


def test_boundary_input_commit_rolls_back_indicator_decision_and_checkpoint(
    postgres_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    strategy = _strategy()
    run = _run(strategy, f"boundary-atomic-{uuid4().hex[:8]}")
    source = InMemoryReplaySource(instrument_id=INSTRUMENT, events=_forming_events())
    inputs = tuple(source)
    with Session(postgres_engine) as session:
        PostgresRunProvenanceRepository(session).add(run)
        session.commit()

    durable = RestartSafeReplayRuntime(
        runtime=_runtime(source=source, run=run, strategy=strategy),
        session_factory=lambda: Session(postgres_engine),
        decision_projector=project_v1_decision,
    )
    for item in inputs[:3]:
        durable.process_input(item)
    checkpoint_before_boundary = durable.checkpoint
    assert checkpoint_before_boundary is not None

    original = PostgresMarketInputCheckpointRepository.upsert

    def fail_after_checkpoint(self, run_arg, checkpoint):
        original(self, run_arg, checkpoint)
        raise RuntimeError("injected boundary input failure")

    monkeypatch.setattr(
        PostgresMarketInputCheckpointRepository,
        "upsert",
        fail_after_checkpoint,
    )
    with pytest.raises(RuntimeError, match="boundary input failure"):
        durable.process_input(inputs[3])
    assert durable.terminal

    with Session(postgres_engine) as observer:
        persisted = PostgresMarketInputCheckpointRepository(observer).get(
            run.run_id,
            INSTRUMENT,
        )
        assert persisted == checkpoint_before_boundary
        assert (
            PostgresIndicatorCheckpointRepository(observer).get(
                run.run_id,
                INSTRUMENT,
            )
            is None
        )
        assert (
            PostgresStrategyDecisionRepository(observer).get(
                run.run_id,
                INSTRUMENT,
                _forming_events()[0].exchange_timestamp.replace(
                    second=0,
                    microsecond=0,
                )
                and CandleInterval.five_minutes(
                    _forming_events()[0].exchange_timestamp
                ),
            )
            is None
        )

    monkeypatch.undo()
    recovered = _recover_runtime(
        postgres_engine,
        source=source,
        run=run,
        strategy=strategy,
    )
    retried = recovered.process_input(inputs[3])
    assert retried.replay_step is not None
    assert retried.replay_step.completed_candle is not None
    with Session(postgres_engine) as observer:
        assert (
            PostgresIndicatorCheckpointRepository(observer).get(
                run.run_id,
                INSTRUMENT,
            )
            == recovered.runtime.indicator_engine.state
        )
