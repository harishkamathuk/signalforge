from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
import sqlalchemy as sa
from alembic.config import Config
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from alembic import command
from signalforge.domain.ids import ConfigId, InstrumentId, RunId
from signalforge.domain.indicators import IndicatorRequirements, RsiRequirement
from signalforge.domain.market import CandleQuality, CompletedCandle
from signalforge.domain.money import Price
from signalforge.domain.provenance import RunIdentity, StrategyIdentity
from signalforge.domain.time import CandleInterval
from signalforge.persistence.mappers import indicator_checkpoint_record_from_state
from signalforge.persistence.models import (
    PRICE_PRECISION,
    PRICE_SCALE,
    Base,
    IndicatorCheckpointRecord,
)
from signalforge.persistence.repositories import (
    PostgresIndicatorCheckpointRepository,
    PostgresRunProvenanceRepository,
)
from signalforge.runtime.indicators import V1_INDICATOR_REQUIREMENTS, IndicatorEngine

EXPECTED_TABLES = {
    "armed_setups",
    "entry_intents",
    "exits",
    "fills",
    "indicator_checkpoints",
    "lifecycle_state",
    "positions",
    "position_open_outcomes",
    "runs",
    "signals",
    "state_transitions",
    "strategy_configs",
    "strategy_evaluations",
    "trades",
    "trigger_events",
}


@pytest.fixture(scope="module")
def postgres_engine() -> Iterator[Engine]:
    database_url = os.environ.get("DATABASE_URL")
    if database_url is None:
        pytest.skip("DATABASE_URL is required for PostgreSQL migration integration tests")

    engine = sa.create_engine(database_url)
    try:
        yield engine
    finally:
        engine.dispose()


def test_orm_metadata_declares_exact_canonical_table_set() -> None:
    assert set(Base.metadata.tables) == EXPECTED_TABLES


def test_alembic_head_creates_canonical_runtime_schema(postgres_engine: Engine) -> None:
    inspector = sa.inspect(postgres_engine)
    assert EXPECTED_TABLES <= set(inspector.get_table_names())

    signal_pk = inspector.get_pk_constraint("signals")
    assert signal_pk["constrained_columns"] == ["signal_id"]

    evaluation_pk = inspector.get_pk_constraint("strategy_evaluations")
    assert evaluation_pk["constrained_columns"] == [
        "run_id",
        "instrument_id",
        "interval_start",
        "interval_end",
    ]

    signal_columns = {column["name"]: column for column in inspector.get_columns("signals")}
    signal_close_type = signal_columns["signal_close"]["type"]
    assert isinstance(signal_close_type, sa.Numeric)
    assert signal_close_type.precision == PRICE_PRECISION
    assert signal_close_type.scale == PRICE_SCALE

    exit_columns = {column["name"]: column for column in inspector.get_columns("exits")}
    realised_r_type = exit_columns["realised_r"]["type"]
    assert isinstance(realised_r_type, sa.Numeric)
    assert realised_r_type.precision is None
    assert realised_r_type.scale is None

    created_at_type = signal_columns["created_at"]["type"]
    assert isinstance(created_at_type, sa.DateTime)
    assert created_at_type.timezone is True
    outcome_columns = {
        column["name"]: column for column in inspector.get_columns("position_open_outcomes")
    }
    assert {"signal_id", "decided_at"} <= set(outcome_columns)
    decided_at_type = outcome_columns["decided_at"]["type"]
    assert isinstance(decided_at_type, sa.DateTime)
    assert decided_at_type.timezone is True
    outcome_fks = {
        constraint["name"]: constraint
        for constraint in inspector.get_foreign_keys("position_open_outcomes")
    }
    assert (
        outcome_fks["fk_position_open_outcomes_fill_id_fills"]["options"]["ondelete"] == "RESTRICT"
    )
    assert outcome_fks["fk_position_open_outcomes_signal_id_signals"]["referred_table"] == "signals"


def test_schema_enforces_core_lifecycle_constraints(postgres_engine: Engine) -> None:
    inspector = sa.inspect(postgres_engine)
    trade_checks = {constraint["name"] for constraint in inspector.get_check_constraints("trades")}
    armed_checks = {
        constraint["name"] for constraint in inspector.get_check_constraints("armed_setups")
    }
    assert "ck_trade_close_metadata" in trade_checks
    assert "ck_trade_risk_positive" in trade_checks
    assert "ck_armed_terminal_metadata" in armed_checks
    assert "ck_armed_trigger_order" in armed_checks


def test_initial_migration_is_reversible_and_reproducible(postgres_engine: Engine) -> None:
    config = Config("alembic.ini")
    command.downgrade(config, "base")
    assert not (EXPECTED_TABLES & set(sa.inspect(postgres_engine).get_table_names()))
    command.upgrade(config, "head")
    assert EXPECTED_TABLES <= set(sa.inspect(postgres_engine).get_table_names())



def _sf063_run(run_id: str, *, engine_version: str = "engine-v1") -> RunIdentity:
    return RunIdentity(
        run_id=RunId(run_id),
        strategy=StrategyIdentity("intraday_momentum_v1", "1.0.0"),
        config_id=ConfigId("b" * 64),
        config_hash="b" * 64,
        engine_calculation_version=engine_version,
    )


def _sf063_candle(instrument_id: InstrumentId, offset: int) -> CompletedCandle:
    start = datetime(2026, 9, 30, 3, 45, tzinfo=UTC) + timedelta(minutes=5 * offset)
    close = Decimal("100.123456789012345678") + Decimal(offset) / Decimal("1000")
    return CompletedCandle(
        instrument_id=instrument_id,
        interval=CandleInterval.five_minutes(start),
        quality=CandleQuality.VALID,
        open=Price(close),
        high=Price(close + Decimal("0.5")),
        low=Price(close - Decimal("0.5")),
        close=Price(close),
        volume=100 + offset,
        source="sf063-migration-test",
        source_event_count=1,
    )


def _reset_migrations(config: Config) -> None:
    command.downgrade(config, "base")
    command.upgrade(config, "head")


def test_sf063_upgrade_preserves_0004_v1_checkpoint_and_resume(
    postgres_engine: Engine,
) -> None:
    """Prove a real pre-SF-063 checkpoint survives 0004 -> 0005 and resumes exactly."""

    config = Config("alembic.ini")
    _reset_migrations(config)
    command.downgrade(config, "20260902_0004")
    instrument_id = InstrumentId("NSE:SF063LEGACY")
    run = _sf063_run("sf063-legacy-run")
    source = IndicatorEngine(
        instrument_id,
        run.engine_calculation_version,
        requirements=V1_INDICATOR_REQUIREMENTS,
    )
    for offset in range(40):
        source.update(_sf063_candle(instrument_id, offset))
    state = source.state
    record = indicator_checkpoint_record_from_state(run, state)

    legacy_columns = tuple(
        column.name
        for column in IndicatorCheckpointRecord.__table__.columns
        if column.name not in {"requirements_manifest", "state_payload"}
    )
    column_sql = ", ".join(legacy_columns)
    value_sql = ", ".join(f":{name}" for name in legacy_columns)
    params = {name: getattr(record, name) for name in legacy_columns}

    try:
        with postgres_engine.begin() as connection:
            connection.execute(
                sa.text(
                    "INSERT INTO strategy_configs "
                    "(config_id, strategy_id, strategy_version, config_hash) "
                    "VALUES (:config_id, :strategy_id, :strategy_version, :config_hash)"
                ),
                {
                    "config_id": str(run.config_id),
                    "strategy_id": run.strategy.strategy_id,
                    "strategy_version": run.strategy.strategy_version,
                    "config_hash": run.config_hash,
                },
            )
            connection.execute(
                sa.text(
                    "INSERT INTO runs (run_id, config_id, engine_calculation_version) "
                    "VALUES (:run_id, :config_id, :engine_version)"
                ),
                {
                    "run_id": str(run.run_id),
                    "config_id": str(run.config_id),
                    "engine_version": run.engine_calculation_version,
                },
            )
            connection.execute(
                sa.text(
                    f"INSERT INTO indicator_checkpoints ({column_sql}) "
                    f"VALUES ({value_sql})"
                ),
                params,
            )

        command.upgrade(config, "head")

        with Session(postgres_engine) as session:
            recovered = PostgresIndicatorCheckpointRepository(session).get(
                run.run_id,
                instrument_id,
            )
        assert recovered == state

        next_candle = _sf063_candle(instrument_id, 40)
        expected = source.update(next_candle)
        resumed = IndicatorEngine(
            instrument_id,
            run.engine_calculation_version,
            requirements=V1_INDICATOR_REQUIREMENTS,
            state=recovered,
        )
        actual = resumed.update(next_candle)
        assert actual == expected
        assert resumed.state == source.state
    finally:
        _reset_migrations(config)


@pytest.mark.parametrize("advance", (False, True))
def test_sf063_downgrade_blocks_generic_only_checkpoint(
    postgres_engine: Engine,
    advance: bool,
) -> None:
    """Do not silently discard empty or populated generic-only state on downgrade."""

    config = Config("alembic.ini")
    _reset_migrations(config)
    run = _sf063_run(f"sf063-rsi-downgrade-{advance}")
    instrument_id = InstrumentId(f"NSE:SF063RSI{int(advance)}")
    engine = IndicatorEngine(
        instrument_id,
        run.engine_calculation_version,
        requirements=IndicatorRequirements.of(RsiRequirement(14)),
    )
    if advance:
        engine.update(_sf063_candle(instrument_id, 0))

    try:
        with Session(postgres_engine) as session:
            PostgresRunProvenanceRepository(session).add(run)
            PostgresIndicatorCheckpointRepository(session).upsert(run, engine.state)
            session.commit()

        with pytest.raises(RuntimeError, match="generic indicator checkpoints"):
            command.downgrade(config, "20260902_0004")
    finally:
        with postgres_engine.begin() as connection:
            connection.execute(sa.text("DELETE FROM indicator_checkpoints"))
        _reset_migrations(config)


def test_sf063_v1_checkpoint_can_downgrade_to_0004(postgres_engine: Engine) -> None:
    """V1 checkpoints retain the historical columns required by the downgrade."""

    config = Config("alembic.ini")
    _reset_migrations(config)
    run = _sf063_run("sf063-v1-downgrade")
    instrument_id = InstrumentId("NSE:SF063V1")
    engine = IndicatorEngine(
        instrument_id,
        run.engine_calculation_version,
        requirements=V1_INDICATOR_REQUIREMENTS,
    )
    engine.update(_sf063_candle(instrument_id, 0))

    try:
        with Session(postgres_engine) as session:
            PostgresRunProvenanceRepository(session).add(run)
            PostgresIndicatorCheckpointRepository(session).upsert(run, engine.state)
            session.commit()

        command.downgrade(config, "20260902_0004")
        checkpoint_columns = sa.inspect(postgres_engine).get_columns("indicator_checkpoints")
        assert "requirements_manifest" not in {
            column["name"] for column in checkpoint_columns
        }
        command.upgrade(config, "head")
    finally:
        _reset_migrations(config)
