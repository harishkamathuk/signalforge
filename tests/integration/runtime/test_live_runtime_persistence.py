from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from signalforge.config.strategy_v1 import StrategyV1EvaluationConfig
from signalforge.domain.decision_facts import StrategyDecisionFact
from signalforge.domain.ids import InstrumentId, RunId
from signalforge.domain.indicators import IndicatorRequirements
from signalforge.domain.money import Price
from signalforge.domain.provenance import RunIdentity
from signalforge.domain.time import IST, CandleInterval
from signalforge.persistence.coordinator import LiveMarketInputCommit, PersistenceCoordinator
from signalforge.persistence.repositories import (
    PostgresIndicatorCheckpointRepository,
    PostgresMarketInputCheckpointRepository,
    PostgresRunProvenanceRepository,
    PostgresStrategyDecisionRepository,
)
from signalforge.runtime.indicators import IndicatorEngine
from signalforge.runtime.strategy_v1 import IntradayMomentumV1Strategy

INSTRUMENT = InstrumentId("NSE:SF057LIVE")


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


def _run(strategy: IntradayMomentumV1Strategy) -> RunIdentity:
    return RunIdentity(
        run_id=RunId(f"sf057-live-{uuid4().hex[:8]}"),
        strategy=strategy.identity,
        config_id=strategy.config_identity.config_id,
        config_hash=strategy.config_identity.config_hash,
        engine_calculation_version="engine-v1",
    )


def _decision(run: RunIdentity) -> StrategyDecisionFact:
    interval = CandleInterval.five_minutes(
        datetime(2026, 10, 5, 10, 0, tzinfo=IST)
    )
    return StrategyDecisionFact.create(
        instrument_id=INSTRUMENT,
        interval=interval,
        strategy=run.strategy,
        decision_kind="intraday_momentum_v1.live_test.v1",
        qualified=False,
        actionable=False,
        reasons=("not_actionable",),
        diagnostics={"feed_healthy": True},
    )


def test_live_commit_persists_atomic_facts_without_market_input_checkpoint(
    postgres_engine: Engine,
) -> None:
    strategy = _strategy()
    run = _run(strategy)
    state = IndicatorEngine(
        INSTRUMENT,
        run.engine_calculation_version,
        requirements=strategy.indicator_requirements,
    ).state
    decision = _decision(run)

    with Session(postgres_engine) as session:
        with session.begin():
            PostgresRunProvenanceRepository(session).add(run)

    with Session(postgres_engine) as session:
        PersistenceCoordinator(session).persist_live_market_input(
            run=run,
            commit=LiveMarketInputCommit(
                indicator_state=state,
                evaluations=(decision,),
            ),
        )

    with Session(postgres_engine) as session:
        assert (
            PostgresIndicatorCheckpointRepository(session).get(
                run.run_id, INSTRUMENT
            )
            == state
        )
        assert (
            PostgresStrategyDecisionRepository(session).get(
                run.run_id, INSTRUMENT, decision.interval
            )
            == decision
        )
        assert (
            PostgresMarketInputCheckpointRepository(session).get(
                run.run_id, INSTRUMENT
            )
            is None
        )
