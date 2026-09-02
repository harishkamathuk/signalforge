import os
from collections.abc import Iterator
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from signalforge.persistence.repositories import PostgresRunProvenanceRepository
from signalforge.runtime.recovery import RecoveryBootstrap, RecoveryDisposition
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


def test_recovery_postgres_clean_and_pre_checkpoint_run_are_read_only(
    postgres_engine: Engine,
) -> None:
    value = facts(f"recovery-{uuid4().hex[:8]}")
    bootstrap = RecoveryBootstrap()
    with Session(postgres_engine) as session:
        result = bootstrap.inspect(
            session=session, requested_run=value.run, instrument_id=value.signal.instrument_id
        )
        assert result.disposition is RecoveryDisposition.NEW
        assert not session.new and not session.dirty
    with Session(postgres_engine) as session:
        PostgresRunProvenanceRepository(session).add(value.run)
        session.commit()
    with Session(postgres_engine) as session:
        result = bootstrap.inspect(
            session=session, requested_run=value.run, instrument_id=value.signal.instrument_id
        )
        assert result.disposition is RecoveryDisposition.RESUMABLE
        assert result.indicator_state is None
        assert not session.new and not session.dirty
