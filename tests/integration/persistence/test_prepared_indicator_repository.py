from __future__ import annotations

import os
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
import sqlalchemy as sa
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from signalforge.domain.ids import ConfigId, InstrumentId, RunId
from signalforge.domain.indicators import IndicatorRequirements, RsiRequirement
from signalforge.domain.market import CandleQuality, CompletedCandle
from signalforge.domain.money import Price
from signalforge.domain.prepared_indicators import (
    PreparedIndicatorCheckpoint,
    prepared_checkpoint_id,
)
from signalforge.domain.provenance import RunIdentity, StrategyIdentity
from signalforge.domain.time import IST, CandleInterval
from signalforge.persistence.errors import ContradictoryFactError
from signalforge.persistence.mappers import prepared_indicator_checkpoint_record_from_domain
from signalforge.persistence.repositories import (
    PostgresPreparedIndicatorCheckpointRepository,
    PostgresRunPreparedIndicatorCheckpointRepository,
    PostgresRunProvenanceRepository,
)
from signalforge.runtime.indicators import IndicatorEngine


@pytest.fixture(scope="module")
def postgres_engine() -> Iterator[Engine]:
    database_url = os.environ.get("DATABASE_URL")
    if database_url is None:
        pytest.fail("DATABASE_URL is required for prepared-state persistence tests")
    engine = sa.create_engine(database_url)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def session(postgres_engine: Engine) -> Iterator[Session]:
    with Session(postgres_engine) as value:
        try:
            yield value
        finally:
            value.rollback()


def _checkpoint() -> PreparedIndicatorCheckpoint:
    instrument_id = InstrumentId("NSE:SF073PERSIST")
    requirements = IndicatorRequirements.of(RsiRequirement(14))
    indicator = IndicatorEngine(
        instrument_id,
        "engine-v1",
        requirements=requirements,
    )
    interval = CandleInterval.five_minutes(
        datetime(2026, 10, 1, 9, 15, tzinfo=UTC)
    )
    indicator.update(
        CompletedCandle(
            instrument_id=instrument_id,
            interval=interval,
            quality=CandleQuality.VALID,
            open=Price(Decimal("100")),
            high=Price(Decimal("101")),
            low=Price(Decimal("99")),
            close=Price(Decimal("100.5")),
            volume=100,
            source="sf073-persistence-test",
            source_event_count=1,
        )
    )
    return PreparedIndicatorCheckpoint(
        checkpoint_id=prepared_checkpoint_id(
            instrument_id=instrument_id,
            requirements=requirements,
            calculation_version="engine-v1",
            boundary=interval,
        ),
        state=indicator.state,
        exchange="NSE",
        target_trading_date=date(2026, 10, 2),
        historical_source="openalgo:/api/v1/history",
        requested_from=date(2026, 10, 1),
        requested_to=date(2026, 10, 1),
        first_accepted_interval=interval,
        final_accepted_interval=interval,
        accepted_candle_count=1,
        candle_sequence_digest="d" * 64,
        prepared_at=datetime(2026, 10, 2, 2, 0, tzinfo=UTC),
    )


def _run(checkpoint: PreparedIndicatorCheckpoint) -> RunIdentity:
    return RunIdentity(
        run_id=RunId("sf073-prepared-run"),
        strategy=StrategyIdentity("intraday_momentum_v1", "1.0.0"),
        config_id=ConfigId("e" * 64),
        config_hash="e" * 64,
        engine_calculation_version=checkpoint.state.calculation_version,
    )


def test_prepared_checkpoint_retry_is_idempotent_by_state_and_digest(
    session: Session,
) -> None:
    checkpoint = _checkpoint()
    repository = PostgresPreparedIndicatorCheckpointRepository(session)

    first = repository.add(checkpoint)
    retried = repository.add(
        replace(
            checkpoint,
            prepared_at=checkpoint.prepared_at + timedelta(minutes=1),
        )
    )

    assert first == checkpoint
    assert retried == first
    assert repository.get(checkpoint.checkpoint_id) == first


def test_prepared_checkpoint_same_identity_different_digest_is_contradiction(
    session: Session,
) -> None:
    checkpoint = _checkpoint()
    repository = PostgresPreparedIndicatorCheckpointRepository(session)
    repository.add(checkpoint)

    with pytest.raises(ContradictoryFactError):
        repository.add(
            replace(
                checkpoint,
                candle_sequence_digest="f" * 64,
            )
        )


def test_live_run_records_immutable_prepared_checkpoint_provenance(
    session: Session,
) -> None:
    checkpoint = _checkpoint()
    run = _run(checkpoint)
    PostgresPreparedIndicatorCheckpointRepository(session).add(checkpoint)
    PostgresRunProvenanceRepository(session).add(run)

    linked = PostgresRunPreparedIndicatorCheckpointRepository(session).add(
        run,
        checkpoint,
    )

    assert linked == checkpoint
    assert (
        PostgresRunPreparedIndicatorCheckpointRepository(session).get_for_run(run.run_id)
        == checkpoint
    )


def test_prepared_checkpoint_id_is_stable_across_ist_and_utc_representation() -> None:
    instrument_id = InstrumentId("NSE:SF073TZ")
    requirements = IndicatorRequirements.of(RsiRequirement(14))
    ist_boundary = CandleInterval.five_minutes(
        datetime(2026, 10, 1, 15, 25, tzinfo=IST)
    )
    utc_boundary = CandleInterval(
        ist_boundary.start.astimezone(UTC),
        ist_boundary.end.astimezone(UTC),
    )

    ist_id = prepared_checkpoint_id(
        instrument_id=instrument_id,
        requirements=requirements,
        calculation_version="engine-v1",
        boundary=ist_boundary,
    )
    utc_id = prepared_checkpoint_id(
        instrument_id=instrument_id,
        requirements=requirements,
        calculation_version="engine-v1",
        boundary=utc_boundary,
    )

    assert utc_id == ist_id


def test_pre_sf059_ist_checkpoint_hydrates_after_postgres_timezone_round_trip(
    postgres_engine: Engine,
) -> None:
    instrument_id = InstrumentId("NSE:SF073LEGACY")
    requirements = IndicatorRequirements.of(RsiRequirement(14))
    interval = CandleInterval.five_minutes(
        datetime(2026, 10, 1, 15, 25, tzinfo=IST)
    )
    indicator = IndicatorEngine(
        instrument_id,
        "engine-v1",
        requirements=requirements,
    )
    indicator.update(
        CompletedCandle(
            instrument_id=instrument_id,
            interval=interval,
            quality=CandleQuality.VALID,
            open=Price(Decimal("100")),
            high=Price(Decimal("101")),
            low=Price(Decimal("99")),
            close=Price(Decimal("100.5")),
            volume=100,
            source="sf073-legacy-ist",
            source_event_count=1,
        )
    )

    # This is exactly the durable SF-073 identity formula: hash the NSE
    # exchange-session interval in its original IST representation.
    legacy_id = prepared_checkpoint_id(
        instrument_id=instrument_id,
        requirements=requirements,
        calculation_version="engine-v1",
        boundary=interval,
    )
    checkpoint = PreparedIndicatorCheckpoint(
        checkpoint_id=legacy_id,
        state=indicator.state,
        exchange="NSE",
        target_trading_date=date(2026, 10, 5),
        historical_source="openalgo:/api/v1/history",
        requested_from=date(2026, 10, 1),
        requested_to=date(2026, 10, 1),
        first_accepted_interval=interval,
        final_accepted_interval=interval,
        accepted_candle_count=1,
        candle_sequence_digest="a" * 64,
        prepared_at=datetime(2026, 10, 5, 8, 0, tzinfo=IST),
    )
    record = prepared_indicator_checkpoint_record_from_domain(checkpoint)

    with Session(postgres_engine) as session:
        with session.begin():
            session.add(record)

    # Fresh session forces a real PostgreSQL timestamptz hydration boundary.
    with Session(postgres_engine) as session:
        hydrated = PostgresPreparedIndicatorCheckpointRepository(session).get(legacy_id)

    assert hydrated is not None
    assert hydrated.checkpoint_id == legacy_id
    assert hydrated.final_accepted_interval == interval
    assert hydrated.state == checkpoint.state
