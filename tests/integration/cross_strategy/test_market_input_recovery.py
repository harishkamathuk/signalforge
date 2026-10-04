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
from signalforge.domain.ids import InstrumentId, RunId
from signalforge.domain.instruments import TickSizeRule, TickSizeSchedule
from signalforge.domain.market import CompletedCandle, MarketEvent
from signalforge.domain.money import Price, Quantity
from signalforge.domain.provenance import RunIdentity
from signalforge.domain.time import IST
from signalforge.persistence.repositories import PostgresRunProvenanceRepository
from signalforge.runtime.candles import CandleEngine
from signalforge.runtime.decision_audit import project_rsi_mean_reversion_decision
from signalforge.runtime.indicator_recovery import IndicatorRecoveryReconciler
from signalforge.runtime.indicators import IndicatorEngine
from signalforge.runtime.lifecycle import LifecycleCoordinator
from signalforge.runtime.lifecycle_recovery import LifecycleRecoveryHydrator
from signalforge.runtime.recovery import RecoveryBootstrap
from signalforge.runtime.replay import InMemoryReplaySource
from signalforge.runtime.replay_runtime import ReplayRuntime
from signalforge.runtime.restart_safe_replay import RestartSafeReplayRuntime
from signalforge.runtime.rsi_mean_reversion_v1 import RsiMeanReversionV1Strategy
from signalforge.runtime.strategy import StrategyRuntimeFacts

INSTRUMENT = InstrumentId("NSE:SF067RSI")


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


def _strategy() -> RsiMeanReversionV1Strategy:
    return RsiMeanReversionV1Strategy(RsiMeanReversionV1Config())


def _run(strategy: RsiMeanReversionV1Strategy) -> RunIdentity:
    return RunIdentity(
        run_id=RunId(f"sf067-rsi-{uuid4().hex[:8]}"),
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


def _events() -> tuple[MarketEvent, ...]:
    base = datetime(2026, 10, 4, 12, 0, tzinfo=IST)
    return tuple(
        MarketEvent(
            instrument_id=INSTRUMENT,
            exchange_timestamp=base + timedelta(minutes=minute),
            received_timestamp=base + timedelta(minutes=minute, milliseconds=1),
            price=Price(Decimal(price)),
            quantity=quantity,
            source="sf067-rsi",
            source_event_id=f"rsi-{minute}",
        )
        for minute, price, quantity in (
            (0, "100", 2),
            (2, "99", 3),
            (4, "98", 4),
            (5, "97", 5),
        )
    )


def _runtime(
    source: InMemoryReplaySource,
    run: RunIdentity,
    strategy: RsiMeanReversionV1Strategy,
    *,
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


def test_reference_strategy_uses_same_forming_candle_recovery_path(
    postgres_engine: Engine,
) -> None:
    strategy = _strategy()
    run = _run(strategy)
    source = InMemoryReplaySource(instrument_id=INSTRUMENT, events=_events())
    inputs = tuple(source)

    reference = _runtime(source, run, strategy)
    reference_steps = tuple(reference.process_input(item) for item in inputs)
    expected_candle = reference_steps[-1].completed_candle
    expected_state = reference.indicator_engine.state
    assert expected_candle is not None

    with Session(postgres_engine) as session:
        PostgresRunProvenanceRepository(session).add(run)
        session.commit()

    durable = RestartSafeReplayRuntime(
        runtime=_runtime(source, run, strategy),
        session_factory=lambda: Session(postgres_engine),
        decision_projector=project_rsi_mean_reversion_decision,
    )
    for item in inputs[:3]:
        durable.process_input(item)

    with Session(postgres_engine) as session:
        recovered = RecoveryBootstrap().inspect(
            session=session,
            requested_run=run,
            instrument_id=INSTRUMENT,
            indicator_requirements=strategy.indicator_requirements,
        )
    assert recovered.market_input_checkpoint is not None
    checkpoint = recovered.market_input_checkpoint
    indicator = IndicatorEngine(
        INSTRUMENT,
        run.engine_calculation_version,
        requirements=strategy.indicator_requirements,
    )
    indicator_result = IndicatorRecoveryReconciler(indicator.state).reconcile(())
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
    resumed = RestartSafeReplayRuntime(
        runtime=_runtime(
            source,
            run,
            strategy,
            candle_engine=CandleEngine(
                instrument_id=INSTRUMENT,
                state=checkpoint.candle_state,
            ),
            indicator_engine=indicator_result.engine,
            lifecycle=lifecycle,
        ),
        session_factory=lambda: Session(postgres_engine),
        decision_projector=project_rsi_mean_reversion_decision,
        checkpoint=checkpoint,
    )

    assert resumed.process_input(inputs[2]).duplicate
    final = resumed.process_input(inputs[3])
    assert final.replay_step is not None
    assert final.replay_step.completed_candle == expected_candle
    assert resumed.runtime.indicator_engine.state == expected_state
    assert resumed.runtime.indicator_engine.state.ema_states == ()
    assert resumed.runtime.indicator_engine.state.adx_state is None
    assert resumed.runtime.indicator_engine.state.macd_state is None
    assert resumed.runtime.indicator_engine.state.rsi_state is not None
