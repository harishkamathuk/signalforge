from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import datetime
from decimal import Decimal
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from signalforge.config.strategy_v1 import StrategyV1EvaluationConfig
from signalforge.domain.decision_facts import StrategyDecisionFact
from signalforge.domain.ids import InstrumentId, RunId
from signalforge.domain.instruments import TickSizeRule, TickSizeSchedule
from signalforge.domain.money import Price, Quantity
from signalforge.domain.provenance import RunIdentity
from signalforge.domain.time import IST, CandleInterval
from signalforge.persistence.coordinator import LiveMarketInputCommit, PersistenceCoordinator
from signalforge.persistence.repositories import (
    PostgresIndicatorCheckpointRepository,
    PostgresMarketInputCheckpointRepository,
    PostgresRunProvenanceRepository,
    PostgresStrategyDecisionRepository,
)
from signalforge.runtime.decision_audit import project_v1_decision
from signalforge.runtime.eligibility import MarketDataFeedState
from signalforge.runtime.indicators import IndicatorContinuity, IndicatorEngine
from signalforge.runtime.live_runtime import LiveRuntime
from signalforge.runtime.strategy import StrategyRuntimeFacts
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



def test_live_commit_rolls_back_prior_writes_on_later_repository_failure(
    postgres_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
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

    def fail_append(self, run_id, fact):
        raise RuntimeError("forced strategy-decision persistence failure")

    monkeypatch.setattr(
        PostgresStrategyDecisionRepository,
        "append",
        fail_append,
    )

    with Session(postgres_engine) as session:
        with pytest.raises(RuntimeError, match="forced strategy-decision"):
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
            is None
        )
        assert (
            PostgresStrategyDecisionRepository(session).get(
                run.run_id, INSTRUMENT, decision.interval
            )
            is None
        )
        assert (
            PostgresMarketInputCheckpointRepository(session).get(
                run.run_id, INSTRUMENT
            )
            is None
        )



class _FailingStartFeed:
    @property
    def state(self) -> MarketDataFeedState:
        return MarketDataFeedState.STARTING

    def start(self) -> None:
        raise RuntimeError("forced websocket startup failure")

    def receive_once(self):
        raise AssertionError("receive must not run")

    def close(self) -> None:
        return None


def test_failed_new_live_activation_rolls_back_run_provenance(
    postgres_engine: Engine,
) -> None:
    strategy = _strategy()
    run = _run(strategy)
    schedule = TickSizeSchedule(
        instrument_id=INSTRUMENT,
        rules=(
            TickSizeRule(
                tick_size=Price(Decimal("0.05")),
                effective_from=datetime(2026, 10, 5, tzinfo=IST).date(),
            ),
        ),
    )

    with pytest.raises(RuntimeError, match="forced websocket startup failure"):
        LiveRuntime.bootstrap(
            feed=_FailingStartFeed(),
            run=run,
            instrument_id=INSTRUMENT,
            tick_schedule=schedule,
            quantity=Quantity(10),
            strategy=strategy,
            session_factory=lambda: Session(postgres_engine),
            decision_projector=project_v1_decision,
            evaluation_context_factory=lambda _candle: StrategyRuntimeFacts(
                completed_regular_session_candles=0,
                continuity=IndicatorContinuity.HEALTHY,
                feed_state=MarketDataFeedState.HEALTHY,
            ),
        )

    with Session(postgres_engine) as session:
        assert PostgresRunProvenanceRepository(session).get(run.run_id) is None
