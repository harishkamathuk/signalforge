from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from signalforge.config.identity import ConfigStatus
from signalforge.config.rsi_mean_reversion_v1 import RsiMeanReversionV1Config
from signalforge.domain.ids import InstrumentId, RunId, deterministic_id
from signalforge.domain.provenance import RunIdentity, StrategyIdentity
from signalforge.persistence.repositories import (
    PostgresIndicatorCheckpointRepository,
    PostgresRunProvenanceRepository,
)
from signalforge.runtime.indicators import IndicatorEngine
from signalforge.runtime.rsi_mean_reversion_v1 import RsiMeanReversionV1Strategy


def test_reference_strategy_provenance_and_rsi_checkpoint_round_trip(
    postgres_engine: Engine,
) -> None:
    """Persist reference provenance without introducing strategy-shaped repositories."""

    strategy = RsiMeanReversionV1Strategy(RsiMeanReversionV1Config())
    config_identity = strategy.config_identity
    instrument_id = InstrumentId("NSE:SF065")
    run = RunIdentity(
        run_id=deterministic_id(
            RunId,
            config_identity.config_hash,
            "sf065-reference-source",
            "engine-v1",
        ),
        strategy=strategy.identity,
        config_id=config_identity.config_id,
        config_hash=config_identity.config_hash,
        engine_calculation_version="engine-v1",
    )
    checkpoint = IndicatorEngine(
        instrument_id,
        run.engine_calculation_version,
        requirements=strategy.indicator_requirements,
    ).state

    assert config_identity.status is ConfigStatus.EXPERIMENTAL
    assert run.strategy == StrategyIdentity("rsi_mean_reversion_v1", "1.0.0")

    with Session(postgres_engine) as session:
        assert PostgresRunProvenanceRepository(session).add(run) == run
        assert PostgresIndicatorCheckpointRepository(session).upsert(run, checkpoint) == checkpoint
        session.commit()

    with Session(postgres_engine) as observer:
        assert PostgresRunProvenanceRepository(observer).get(run.run_id) == run
        restored = PostgresIndicatorCheckpointRepository(observer).get(
            run.run_id,
            instrument_id,
        )

    assert restored == checkpoint
    assert restored is not None
    assert restored.requirements == strategy.indicator_requirements
    assert restored.ema_states == ()
    assert restored.adx_state is None
    assert restored.macd_state is None
    assert restored.rsi_state is not None
