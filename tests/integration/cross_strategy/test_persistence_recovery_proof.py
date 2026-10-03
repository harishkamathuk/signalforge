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

from signalforge.config.strategy_registry import (
    DEFAULT_STRATEGY_REGISTRY,
    StrategySelection,
)
from signalforge.domain.ids import InstrumentId, RunId, deterministic_id
from signalforge.domain.indicators import IndicatorRequirements, RsiRequirement
from signalforge.domain.provenance import RunIdentity
from signalforge.domain.strategy import (
    DecisionReason,
    MomentumResult,
    SetupResult,
    StrategyEvaluation,
    TrendResult,
)
from signalforge.domain.time import IST, CandleInterval
from signalforge.persistence.errors import ContradictoryFactError
from signalforge.persistence.repositories import (
    PostgresIndicatorCheckpointRepository,
    PostgresRunProvenanceRepository,
    PostgresStrategyDecisionRepository,
)
from signalforge.runtime.decision_audit import (
    project_rsi_mean_reversion_decision,
    project_v1_decision,
)
from signalforge.runtime.indicators import IndicatorEngine
from signalforge.runtime.recovery import RecoveryBootstrap, RecoveryDisposition
from signalforge.runtime.rsi_mean_reversion_v1 import RsiMeanReversionDecision

INSTRUMENT = InstrumentId("NSE:CROSSSTRAT")
INTERVAL = CandleInterval.five_minutes(datetime(2026, 10, 3, 10, 0, tzinfo=IST))


@pytest.fixture(scope="module")
def postgres_engine() -> Iterator[Engine]:
    url = os.environ.get("DATABASE_URL")
    if url is None:
        pytest.fail("DATABASE_URL is required for cross-strategy persistence tests")
    engine = sa.create_engine(url)
    try:
        yield engine
    finally:
        engine.dispose()


def _strategy(strategy_id: str):
    return DEFAULT_STRATEGY_REGISTRY.resolve(
        StrategySelection(strategy_id, "1.0.0", {})
    )


def _run(strategy_id: str, suffix: str) -> RunIdentity:
    strategy = _strategy(strategy_id)
    source = f"cross-strategy-{suffix}"
    run_id = deterministic_id(
        RunId,
        strategy.config_identity.config_hash,
        source,
        "engine-v1",
    )
    return RunIdentity(
        run_id=run_id,
        strategy=strategy.identity,
        config_id=strategy.config_identity.config_id,
        config_hash=strategy.config_identity.config_hash,
        engine_calculation_version="engine-v1",
    )


def _decision_fact(strategy_id: str):
    if strategy_id == "intraday_momentum_v1":
        return project_v1_decision(
            StrategyEvaluation(
                instrument_id=INSTRUMENT,
                interval=INTERVAL,
                trend=TrendResult(True),
                momentum=MomentumResult(True, True, True, None),
                setup=SetupResult(True),
                qualified=True,
                actionable=True,
                reasons=(DecisionReason.QUALIFIED, DecisionReason.ACTIONABLE),
            )
        )
    return project_rsi_mean_reversion_decision(
        RsiMeanReversionDecision(
            instrument_id=INSTRUMENT,
            interval=INTERVAL,
            qualified=True,
            actionable=True,
            reasons=("rsi_below_threshold",),
            rsi14=Decimal("29.125000"),
        )
    )


@pytest.mark.parametrize(
    "strategy_id",
    ("intraday_momentum_v1", "rsi_mean_reversion_v1"),
)
def test_cross_strategy_provenance_decision_checkpoint_and_recovery(
    postgres_engine: Engine,
    strategy_id: str,
) -> None:
    strategy = _strategy(strategy_id)
    run = _run(strategy_id, uuid4().hex)
    fact = _decision_fact(strategy_id)
    checkpoint = IndicatorEngine(
        INSTRUMENT,
        run.engine_calculation_version,
        requirements=strategy.indicator_requirements,
    ).state

    with Session(postgres_engine) as session:
        assert PostgresRunProvenanceRepository(session).add(run) == run
        repo = PostgresStrategyDecisionRepository(session)
        assert repo.append(run.run_id, fact) == fact
        assert repo.append(run.run_id, fact) == fact
        assert PostgresIndicatorCheckpointRepository(session).upsert(run, checkpoint) == checkpoint
        session.commit()

    with Session(postgres_engine) as session:
        assert PostgresRunProvenanceRepository(session).get(run.run_id) == run
        assert (
            PostgresStrategyDecisionRepository(session).get(
                run.run_id, INSTRUMENT, INTERVAL
            )
            == fact
        )
        assert (
            PostgresIndicatorCheckpointRepository(session).get(run.run_id, INSTRUMENT)
            == checkpoint
        )
        recovered = RecoveryBootstrap().inspect(
            session=session,
            requested_run=run,
            instrument_id=INSTRUMENT,
            indicator_requirements=strategy.indicator_requirements,
        )

    assert recovered.disposition is RecoveryDisposition.RESUMABLE
    assert recovered.run == run
    assert recovered.indicator_state == checkpoint


@pytest.mark.parametrize(
    "strategy_id",
    ("intraday_momentum_v1", "rsi_mean_reversion_v1"),
)
def test_strategy_decision_contradictory_retry_fails(
    postgres_engine: Engine,
    strategy_id: str,
) -> None:
    run = _run(strategy_id, uuid4().hex)
    fact = _decision_fact(strategy_id)

    with Session(postgres_engine) as session:
        PostgresRunProvenanceRepository(session).add(run)
        repo = PostgresStrategyDecisionRepository(session)
        repo.append(run.run_id, fact)
        session.commit()

    contradictory = type(fact)(
        instrument_id=fact.instrument_id,
        interval=fact.interval,
        decision_kind=fact.decision_kind,
        qualified=fact.qualified,
        actionable=fact.actionable,
        reasons=fact.reasons + ("contradiction",),
        diagnostics=fact.diagnostics,
    )
    with Session(postgres_engine) as session:
        with pytest.raises(ContradictoryFactError):
            PostgresStrategyDecisionRepository(session).append(
                run.run_id,
                contradictory,
            )


def test_recovery_rejects_cross_strategy_requirement_shape(
    postgres_engine: Engine,
) -> None:
    v1 = _strategy("intraday_momentum_v1")
    reference = _strategy("rsi_mean_reversion_v1")
    run = _run("intraday_momentum_v1", uuid4().hex)
    checkpoint = IndicatorEngine(
        INSTRUMENT,
        run.engine_calculation_version,
        requirements=v1.indicator_requirements,
    ).state

    with Session(postgres_engine) as session:
        PostgresRunProvenanceRepository(session).add(run)
        PostgresIndicatorCheckpointRepository(session).upsert(run, checkpoint)
        session.commit()

    with Session(postgres_engine) as session:
        with pytest.raises(
            ContradictoryFactError,
            match="requirements contradict requested strategy",
        ):
            RecoveryBootstrap().inspect(
                session=session,
                requested_run=run,
                instrument_id=INSTRUMENT,
                indicator_requirements=reference.indicator_requirements,
            )


def test_recovery_identity_is_not_inferred_from_rsi_only_shape(
    postgres_engine: Engine,
) -> None:
    reference = _strategy("rsi_mean_reversion_v1")
    run = _run("rsi_mean_reversion_v1", uuid4().hex)
    checkpoint = IndicatorEngine(
        INSTRUMENT,
        run.engine_calculation_version,
        requirements=reference.indicator_requirements,
    ).state

    with Session(postgres_engine) as session:
        PostgresRunProvenanceRepository(session).add(run)
        PostgresIndicatorCheckpointRepository(session).upsert(run, checkpoint)
        session.commit()

    v1 = _strategy("intraday_momentum_v1")
    contradictory = RunIdentity(
        run_id=run.run_id,
        strategy=v1.identity,
        config_id=v1.config_identity.config_id,
        config_hash=v1.config_identity.config_hash,
        engine_calculation_version=run.engine_calculation_version,
    )
    with Session(postgres_engine) as session:
        with pytest.raises(
            ContradictoryFactError,
            match="provenance differs",
        ):
            RecoveryBootstrap().inspect(
                session=session,
                requested_run=contradictory,
                instrument_id=INSTRUMENT,
                indicator_requirements=IndicatorRequirements.of(RsiRequirement(14)),
            )
