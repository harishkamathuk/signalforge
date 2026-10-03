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
from signalforge.domain.instruments import TickSizeRule, TickSizeSchedule
from signalforge.domain.market import CandleQuality, CompletedCandle
from signalforge.domain.money import Price, Quantity
from signalforge.domain.time import IST, CandleInterval
from signalforge.persistence.repositories import (
    PostgresArmedSetupRepository,
    PostgresIndicatorCheckpointRepository,
    PostgresRunProvenanceRepository,
)
from signalforge.runtime.indicator_recovery import (
    IndicatorRecoveryError,
    IndicatorRecoveryReconciler,
    RecoveryCandle,
)
from signalforge.runtime.indicators import (
    V1_INDICATOR_REQUIREMENTS,
    IndicatorContinuity,
    IndicatorEngine,
)
from signalforge.runtime.lifecycle import LifecycleCoordinator
from signalforge.runtime.lifecycle_recovery import (
    LifecycleRecoveryError,
    LifecycleRecoveryHydrator,
)
from signalforge.runtime.recovery import RecoveryBootstrap
from signalforge.runtime.strategy_v1 import IntradayMomentumV1Strategy
from tests.integration.persistence.test_recovery_postgres import (
    _durable_counts,
    _persist_armed_graph,
)
from tests.integration.persistence.test_repository_adapters_postgres import facts


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


def _candle(instrument_id, index: int) -> CompletedCandle:
    start = datetime(2026, 10, 3, 9, 15, tzinfo=IST) + timedelta(minutes=5 * index)
    base = Decimal("100") + Decimal(index) / Decimal("10")
    return CompletedCandle(
        instrument_id=instrument_id,
        interval=CandleInterval.five_minutes(start),
        quality=CandleQuality.VALID,
        open=Price(base),
        high=Price(base + Decimal("1")),
        low=Price(base - Decimal("1")),
        close=Price(base + Decimal("0.25")),
        volume=1000 + index,
        source="sf052-recovery",
        source_event_count=1,
    )


def test_interrupted_indicator_recovery_is_non_durable_and_fresh_retry_converges(
    postgres_engine: Engine,
) -> None:
    value = facts(f"sf052-indicator-recovery-{uuid4().hex}")
    checkpoint_engine = IndicatorEngine(
        value.signal.instrument_id,
        value.run.engine_calculation_version,
        requirements=V1_INDICATOR_REQUIREMENTS,
    )
    for index in range(5):
        checkpoint_engine.update(_candle(value.signal.instrument_id, index))
    checkpoint = checkpoint_engine.state

    uninterrupted = IndicatorEngine(
        value.signal.instrument_id,
        value.run.engine_calculation_version,
        requirements=V1_INDICATOR_REQUIREMENTS,
        state=checkpoint,
    )
    for index in range(5, 8):
        uninterrupted.update(_candle(value.signal.instrument_id, index))

    with Session(postgres_engine) as session:
        PostgresRunProvenanceRepository(session).add(value.run)
        PostgresIndicatorCheckpointRepository(session).upsert(value.run, checkpoint)
        session.commit()

    def interrupted_source():
        yield RecoveryCandle(_candle(value.signal.instrument_id, 5), continuity_ok=True)
        raise OSError("simulated recovery-source crash")

    reconciler = IndicatorRecoveryReconciler(checkpoint)
    with pytest.raises(IndicatorRecoveryError, match="source failed"):
        reconciler.reconcile(interrupted_source())

    assert reconciler.state.continuity is IndicatorContinuity.BROKEN
    with pytest.raises(IndicatorRecoveryError, match="already terminal"):
        reconciler.reconcile(())

    with Session(postgres_engine) as observer:
        persisted = PostgresIndicatorCheckpointRepository(observer).get(
            value.run.run_id,
            value.signal.instrument_id,
        )
    assert persisted == checkpoint

    with Session(postgres_engine) as session:
        recovered = RecoveryBootstrap().inspect(
            session=session,
            requested_run=value.run,
            instrument_id=value.signal.instrument_id,
            indicator_requirements=V1_INDICATOR_REQUIREMENTS,
        )
    assert recovered.indicator_state == checkpoint
    assert recovered.indicator_state is not None

    fresh = IndicatorRecoveryReconciler(recovered.indicator_state)
    result = fresh.reconcile(
        RecoveryCandle(_candle(value.signal.instrument_id, index), continuity_ok=True)
        for index in range(5, 8)
    )

    assert result.engine.state == uninterrupted.state

    with Session(postgres_engine) as observer:
        assert (
            PostgresIndicatorCheckpointRepository(observer).get(
                value.run.run_id,
                value.signal.instrument_id,
            )
            == checkpoint
        )


def test_failed_lifecycle_hydration_is_non_durable_and_fresh_retry_starts_from_same_graph(
    postgres_engine: Engine,
) -> None:
    value = facts(f"sf052-lifecycle-recovery-{uuid4().hex}")
    _persist_armed_graph(postgres_engine, value)

    with Session(postgres_engine) as session:
        before = _durable_counts(session)
        recovered = RecoveryBootstrap().inspect(
            session=session,
            requested_run=value.run,
            instrument_id=value.signal.instrument_id,
            indicator_requirements=V1_INDICATOR_REQUIREMENTS,
        )

    indicator_engine = IndicatorEngine(
        value.signal.instrument_id,
        value.run.engine_calculation_version,
        requirements=V1_INDICATOR_REQUIREMENTS,
    )
    indicator_result = IndicatorRecoveryReconciler(indicator_engine.state).reconcile(())

    strategy = IntradayMomentumV1Strategy(StrategyV1EvaluationConfig())
    schedule = TickSizeSchedule(
        instrument_id=value.signal.instrument_id,
        rules=(TickSizeRule(Price(Decimal("0.05")), date(2026, 1, 1)),),
    )
    mismatched = LifecycleCoordinator(
        run=value.run,
        tick_schedule=schedule,
        quantity=Quantity(10),
        strategy=strategy,
    )

    with pytest.raises(LifecycleRecoveryError, match="configured strategy identity"):
        LifecycleRecoveryHydrator().hydrate(
            indicator_result=indicator_result,
            recovered=recovered.lifecycle,
            coordinator=mismatched,
        )

    with Session(postgres_engine) as observer:
        assert _durable_counts(observer) == before
        setup = PostgresArmedSetupRepository(observer).get(value.signal.signal_id)
        assert setup == recovered.lifecycle.setup

    with Session(postgres_engine) as session:
        retried = RecoveryBootstrap().inspect(
            session=session,
            requested_run=value.run,
            instrument_id=value.signal.instrument_id,
            indicator_requirements=V1_INDICATOR_REQUIREMENTS,
        )

    assert retried.lifecycle.signal == recovered.lifecycle.signal
    assert retried.lifecycle.setup == recovered.lifecycle.setup
