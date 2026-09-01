from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
import sqlalchemy as sa
from alembic.config import Config
from sqlalchemy.engine import Engine

from alembic import command
from signalforge.persistence.models import PRICE_PRECISION, PRICE_SCALE, Base

EXPECTED_TABLES = {
    "armed_setups",
    "entry_intents",
    "exits",
    "fills",
    "indicator_checkpoints",
    "lifecycle_state",
    "positions",
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
