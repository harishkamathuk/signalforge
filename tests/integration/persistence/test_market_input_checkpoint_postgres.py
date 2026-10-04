from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from signalforge.domain.market import MarketEvent
from signalforge.domain.money import Price
from signalforge.domain.time import IST
from signalforge.persistence.errors import ContradictoryFactError
from signalforge.persistence.repositories import (
    PostgresMarketInputCheckpointRepository,
    PostgresRunProvenanceRepository,
)
from signalforge.runtime.candles import CandleEngine
from signalforge.runtime.market_input import (
    CanonicalMarketInput,
    MarketInputCheckpoint,
    market_event_fingerprint,
)
from tests.integration.persistence.test_repository_adapters_postgres import facts


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


def _event(value, sequence: int) -> MarketEvent:
    at = datetime(2026, 10, 4, 9, 15, tzinfo=IST) + timedelta(seconds=sequence)
    return MarketEvent(
        instrument_id=value.signal.instrument_id,
        exchange_timestamp=at,
        received_timestamp=at + timedelta(milliseconds=1),
        price=Price(Decimal("100") + Decimal(sequence) / Decimal("10")),
        quantity=sequence + 1,
        source="sf067-postgres",
        source_event_id=f"evt-{sequence}",
    )


def _checkpoint(value, sequence: int, engine: CandleEngine) -> MarketInputCheckpoint:
    event = _event(value, sequence)
    return MarketInputCheckpoint(
        run=value.run,
        instrument_id=value.signal.instrument_id,
        last_input=CanonicalMarketInput(
            source_id="source-A",
            sequence=sequence,
            source_event_id=event.source_event_id or "",
            payload_fingerprint=market_event_fingerprint(event),
        ),
        candle_state=engine.state,
        updated_at=event.received_timestamp,
    )


def test_market_input_checkpoint_round_trips_and_advances_contiguously(
    postgres_engine: Engine,
) -> None:
    value = facts(f"sf067cp-{uuid4().hex[:8]}")
    engine = CandleEngine(instrument_id=value.signal.instrument_id)
    event0 = _event(value, 0)
    engine.process(event0)
    first = _checkpoint(value, 0, engine)

    with Session(postgres_engine) as session:
        PostgresRunProvenanceRepository(session).add(value.run)
        session.commit()
        repo = PostgresMarketInputCheckpointRepository(session)
        assert repo.upsert(value.run, first) == first
        session.commit()

    with Session(postgres_engine) as observer:
        assert (
            PostgresMarketInputCheckpointRepository(observer).get(
                value.run.run_id,
                value.signal.instrument_id,
            )
            == first
        )

    engine.process(_event(value, 1))
    second = _checkpoint(value, 1, engine)
    with Session(postgres_engine) as session:
        repo = PostgresMarketInputCheckpointRepository(session)
        assert repo.upsert(value.run, second) == second
        assert repo.upsert(value.run, second) == second
        session.commit()

    with Session(postgres_engine) as observer:
        assert (
            PostgresMarketInputCheckpointRepository(observer).get(
                value.run.run_id,
                value.signal.instrument_id,
            )
            == second
        )


def test_market_input_checkpoint_rejects_source_regression_gap_and_conflict(
    postgres_engine: Engine,
) -> None:
    value = facts(f"sf067bad-{uuid4().hex[:8]}")
    engine = CandleEngine(instrument_id=value.signal.instrument_id)
    engine.process(_event(value, 0))
    first = _checkpoint(value, 0, engine)
    with Session(postgres_engine) as session:
        PostgresRunProvenanceRepository(session).add(value.run)
        session.commit()
        repo = PostgresMarketInputCheckpointRepository(session)
        repo.upsert(value.run, first)
        session.commit()

    for checkpoint, match in (
        (
            MarketInputCheckpoint(
                run=value.run,
                instrument_id=value.signal.instrument_id,
                last_input=CanonicalMarketInput(
                    "source-B",
                    1,
                    "evt-1",
                    "fingerprint",
                ),
                candle_state=engine.state,
                updated_at=first.updated_at + timedelta(seconds=1),
            ),
            "source identity",
        ),
        (
            MarketInputCheckpoint(
                run=value.run,
                instrument_id=value.signal.instrument_id,
                last_input=CanonicalMarketInput(
                    "source-A",
                    2,
                    "evt-2",
                    "fingerprint",
                ),
                candle_state=engine.state,
                updated_at=first.updated_at + timedelta(seconds=2),
            ),
            "sequence gap",
        ),
        (
            MarketInputCheckpoint(
                run=value.run,
                instrument_id=value.signal.instrument_id,
                last_input=CanonicalMarketInput(
                    "source-A",
                    0,
                    "evt-0",
                    "different",
                ),
                candle_state=engine.state,
                updated_at=first.updated_at,
            ),
            "same market-input sequence",
        ),
    ):
        with Session(postgres_engine) as session:
            with pytest.raises(ContradictoryFactError, match=match):
                PostgresMarketInputCheckpointRepository(session).upsert(
                    value.run,
                    checkpoint,
                )
