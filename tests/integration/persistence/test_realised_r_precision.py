from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal

import pytest
import sqlalchemy as sa
from sqlalchemy.engine import Engine

from signalforge.persistence.models import (
    EntryIntentRecord,
    ExitRecord,
    FillRecord,
    PositionRecord,
    RunRecord,
    SignalRecord,
    StrategyConfigRecord,
    TradeRecord,
    TriggerEventRecord,
)


@pytest.fixture(scope="module")
def postgres_engine() -> Iterator[Engine]:
    database_url = os.environ.get("DATABASE_URL")
    if database_url is None:
        pytest.skip("DATABASE_URL is required for realised_r precision integration tests")

    engine = sa.create_engine(database_url)
    try:
        yield engine
    finally:
        engine.dispose()


def test_realised_r_uses_unconstrained_numeric(postgres_engine: Engine) -> None:
    column = {item["name"]: item for item in sa.inspect(postgres_engine).get_columns("exits")}[
        "realised_r"
    ]
    numeric = column["type"]

    assert isinstance(numeric, sa.Numeric)
    assert numeric.precision is None
    assert numeric.scale is None


def test_high_precision_realised_r_round_trips_exactly(postgres_engine: Engine) -> None:
    at = datetime(2026, 9, 1, 10, 0, tzinfo=UTC)
    realised_r = Decimal("1.1234567890123456789012345678901234567890123456789012345")

    connection = postgres_engine.connect()
    transaction = connection.begin()
    try:
        connection.execute(
            StrategyConfigRecord.__table__.insert(),
            {
                "config_id": "precision-config",
                "strategy_id": "intraday_momentum_v1",
                "strategy_version": "1.0.0",
                "config_hash": "precision-hash",
            },
        )
        connection.execute(
            RunRecord.__table__.insert(),
            {
                "run_id": "precision-run",
                "config_id": "precision-config",
                "engine_calculation_version": "engine-v1",
            },
        )
        connection.execute(
            SignalRecord.__table__.insert(),
            {
                "signal_id": "precision-signal",
                "run_id": "precision-run",
                "instrument_id": "NSE:TEST",
                "interval_start": at,
                "interval_end": at.replace(minute=5),
                "signal_close": Decimal("101"),
                "signal_low": Decimal("100"),
                "created_at": at.replace(minute=5),
            },
        )
        connection.execute(
            TriggerEventRecord.__table__.insert(),
            {
                "trigger_event_id": "precision-trigger",
                "signal_id": "precision-signal",
                "run_id": "precision-run",
                "instrument_id": "NSE:TEST",
                "reference_price": Decimal("101.1"),
                "observed_price": Decimal("101.2"),
                "observed_at": at.replace(minute=6),
            },
        )
        connection.execute(
            EntryIntentRecord.__table__.insert(),
            {
                "entry_intent_id": "precision-intent",
                "trigger_event_id": "precision-trigger",
                "signal_id": "precision-signal",
                "run_id": "precision-run",
                "instrument_id": "NSE:TEST",
                "reference_price": Decimal("101.1"),
                "quantity": 10,
                "execution_mode": "paper",
                "created_at": at.replace(minute=6),
            },
        )
        connection.execute(
            FillRecord.__table__.insert(),
            {
                "fill_id": "precision-fill",
                "entry_intent_id": "precision-intent",
                "trigger_event_id": "precision-trigger",
                "signal_id": "precision-signal",
                "run_id": "precision-run",
                "instrument_id": "NSE:TEST",
                "reference_price": Decimal("101.1"),
                "fill_price": Decimal("101.2"),
                "quantity": 10,
                "execution_mode": "paper",
                "filled_at": at.replace(minute=6),
            },
        )
        connection.execute(
            TradeRecord.__table__.insert(),
            {
                "trade_id": "precision-trade",
                "entry_fill_id": "precision-fill",
                "signal_id": "precision-signal",
                "run_id": "precision-run",
                "instrument_id": "NSE:TEST",
                "entry_price": Decimal("101.2"),
                "stop_price": Decimal("100"),
                "raw_target_price": Decimal("103"),
                "tradable_target_price": Decimal("103"),
                "risk_per_share": Decimal("1.2"),
                "quantity": 10,
                "opened_at": at.replace(minute=6),
                "state": "open",
                "closed_at": None,
                "exit_id": None,
            },
        )
        connection.execute(
            PositionRecord.__table__.insert(),
            {
                "position_id": "precision-position",
                "trade_id": "precision-trade",
                "run_id": "precision-run",
                "instrument_id": "NSE:TEST",
                "quantity": 10,
                "average_entry_price": Decimal("101.2"),
                "opened_at": at.replace(minute=6),
                "state": "open",
                "closed_at": None,
            },
        )
        connection.execute(
            ExitRecord.__table__.insert(),
            {
                "exit_id": "precision-exit",
                "exit_fill_id": "precision-exit-fill",
                "trade_id": "precision-trade",
                "position_id": "precision-position",
                "run_id": "precision-run",
                "instrument_id": "NSE:TEST",
                "reason": "target",
                "reference_price": Decimal("103"),
                "fill_price": Decimal("103.1"),
                "quantity": 10,
                "execution_mode": "paper",
                "exited_at": at.replace(minute=10),
                "realised_pnl": Decimal("19"),
                "realised_r": realised_r,
            },
        )

        stored = connection.scalar(
            sa.select(ExitRecord.realised_r).where(ExitRecord.exit_id == "precision-exit")
        )
        assert stored == realised_r
        assert stored.as_tuple() == realised_r.as_tuple()
    finally:
        transaction.rollback()
        connection.close()
