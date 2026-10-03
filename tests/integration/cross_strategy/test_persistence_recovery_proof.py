from __future__ import annotations

import json
import os
from collections.abc import Iterator
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic.config import Config
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from alembic import command
from signalforge.config.strategy_registry import (
    DEFAULT_STRATEGY_REGISTRY,
    StrategySelection,
)
from signalforge.domain.ids import InstrumentId, RunId, deterministic_id
from signalforge.domain.indicators import IndicatorRequirements, RsiRequirement
from signalforge.domain.market import CandleQuality, CompletedCandle
from signalforge.domain.money import Price
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
from tests.integration.persistence.test_migrations import _clear_downgrade_blockers

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
        strategy=fact.strategy,
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



def test_cross_strategy_fresh_database_logical_output_is_reproducible(
    postgres_engine: Engine,
) -> None:
    """Recreate the schema twice and require identical logical cross-strategy facts."""

    config = Config("alembic.ini")

    def run_clean() -> tuple[tuple[object, ...], ...]:
        _clear_downgrade_blockers(postgres_engine)
        command.downgrade(config, "base")
        command.upgrade(config, "head")
        for strategy_id in ("intraday_momentum_v1", "rsi_mean_reversion_v1"):
            strategy = _strategy(strategy_id)
            run = _run(strategy_id, f"fresh-{strategy_id}")
            fact = _decision_fact(strategy_id)
            checkpoint = IndicatorEngine(
                INSTRUMENT,
                run.engine_calculation_version,
                requirements=strategy.indicator_requirements,
            ).state
            with Session(postgres_engine) as session:
                PostgresRunProvenanceRepository(session).add(run)
                PostgresStrategyDecisionRepository(session).append(run.run_id, fact)
                PostgresIndicatorCheckpointRepository(session).upsert(run, checkpoint)
                session.commit()

        rows: list[tuple[object, ...]] = []
        with postgres_engine.connect() as connection:
            configs = connection.execute(
                sa.text(
                    "SELECT strategy_id, strategy_version, config_id, config_hash "
                    "FROM strategy_configs ORDER BY strategy_id"
                )
            ).mappings()
            rows.extend(
                (
                    "config",
                    row["strategy_id"],
                    row["strategy_version"],
                    row["config_id"],
                    row["config_hash"],
                )
                for row in configs
            )
            decisions = connection.execute(
                sa.text(
                    "SELECT run_id, instrument_id, interval_start, interval_end, "
                    "decision_kind, qualified, actionable, reasons, diagnostics "
                    "FROM strategy_evaluations ORDER BY run_id"
                )
            ).mappings()
            rows.extend(
                (
                    "decision",
                    row["run_id"],
                    row["instrument_id"],
                    row["interval_start"].isoformat(),
                    row["interval_end"].isoformat(),
                    row["decision_kind"],
                    row["qualified"],
                    row["actionable"],
                    json.dumps(row["reasons"], separators=(",", ":")),
                    json.dumps(row["diagnostics"], sort_keys=True, separators=(",", ":")),
                )
                for row in decisions
            )
            checkpoints = connection.execute(
                sa.text(
                    "SELECT run_id, instrument_id, calculation_version, continuity_state, "
                    "completed_candle_count, requirements_manifest, state_payload "
                    "FROM indicator_checkpoints ORDER BY run_id"
                )
            ).mappings()
            rows.extend(
                (
                    "checkpoint",
                    row["run_id"],
                    row["instrument_id"],
                    row["calculation_version"],
                    row["continuity_state"],
                    row["completed_candle_count"],
                    json.dumps(
                        row["requirements_manifest"],
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    json.dumps(row["state_payload"], sort_keys=True, separators=(",", ":")),
                )
                for row in checkpoints
            )
        return tuple(rows)

    try:
        first = run_clean()
        second = run_clean()
        assert second == first
    finally:
        _clear_downgrade_blockers(postgres_engine)
        command.downgrade(config, "base")
        command.upgrade(config, "head")



def _candle(index: int) -> CompletedCandle:
    start = datetime(2026, 10, 3, 9, 15, tzinfo=IST) + timedelta(minutes=5 * index)
    close = Decimal("100") + Decimal(index) / Decimal("7")
    return CompletedCandle(
        instrument_id=INSTRUMENT,
        interval=CandleInterval.five_minutes(start),
        quality=CandleQuality.VALID,
        open=Price(close),
        high=Price(close + Decimal("1.1")),
        low=Price(close - Decimal("0.9")),
        close=Price(close + Decimal("0.123456789012345678")),
        volume=1000 + index,
        source="sf066-checkpoint",
        source_event_count=1,
    )


@pytest.mark.parametrize(
    ("strategy_id", "warmup"),
    (("intraday_momentum_v1", 60), ("rsi_mean_reversion_v1", 20)),
)
def test_cross_strategy_checkpoint_resume_matches_uninterrupted_next_candle(
    postgres_engine: Engine,
    strategy_id: str,
    warmup: int,
) -> None:
    strategy = _strategy(strategy_id)
    run = _run(strategy_id, uuid4().hex)
    source = IndicatorEngine(
        INSTRUMENT,
        run.engine_calculation_version,
        requirements=strategy.indicator_requirements,
    )
    for index in range(warmup):
        source.update(_candle(index))

    with Session(postgres_engine) as session:
        PostgresRunProvenanceRepository(session).add(run)
        PostgresIndicatorCheckpointRepository(session).upsert(run, source.state)
        session.commit()
    with Session(postgres_engine) as session:
        restored = PostgresIndicatorCheckpointRepository(session).get(
            run.run_id,
            INSTRUMENT,
        )
    assert restored == source.state
    assert restored is not None

    resumed = IndicatorEngine(
        INSTRUMENT,
        run.engine_calculation_version,
        requirements=strategy.indicator_requirements,
        state=restored,
    )
    next_candle = _candle(warmup)

    assert resumed.update(next_candle) == source.update(next_candle)
    assert resumed.state == source.state



def test_strategy_decision_cannot_cross_run_strategy_provenance(
    postgres_engine: Engine,
) -> None:
    """Reject a reference decision fact stored under Strategy V1 provenance."""

    run = _run("intraday_momentum_v1", uuid4().hex)
    reference_fact = _decision_fact("rsi_mean_reversion_v1")
    with Session(postgres_engine) as session:
        PostgresRunProvenanceRepository(session).add(run)
        with pytest.raises(
            ContradictoryFactError,
            match="decision identity contradicts persisted run provenance",
        ):
            PostgresStrategyDecisionRepository(session).append(
                run.run_id,
                reference_fact,
            )
