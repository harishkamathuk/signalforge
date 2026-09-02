from types import SimpleNamespace

import pytest

from signalforge.domain.ids import ConfigId, InstrumentId, RunId
from signalforge.domain.provenance import RunIdentity, StrategyIdentity
from signalforge.persistence.errors import ContradictoryFactError
from signalforge.runtime import recovery
from signalforge.runtime.recovery import RecoveryBootstrap, RecoveryDisposition


def _run() -> RunIdentity:
    return RunIdentity(
        RunId("recovery-run"),
        StrategyIdentity("strategy", "1"),
        ConfigId("config"),
        "hash",
        "engine",
    )


def _repos(monkeypatch: pytest.MonkeyPatch, run: RunIdentity | None) -> None:
    class RunRepo:
        def __init__(self, session: object) -> None:
            pass

        def get(self, run_id: RunId) -> RunIdentity | None:
            return run

    class EmptyRepo:
        def __init__(self, session: object) -> None:
            pass

        def find_for_run_instrument(
            self, run_id: RunId, instrument_id: InstrumentId
        ) -> tuple[object, ...]:
            return ()

    class CheckpointRepo:
        def __init__(self, session: object) -> None:
            pass

        def get(self, run_id: RunId, instrument_id: InstrumentId) -> None:
            return None

    monkeypatch.setattr(recovery, "PostgresRunProvenanceRepository", RunRepo)
    for name in (
        "PostgresSignalRepository",
        "PostgresArmedSetupRepository",
        "PostgresFillRepository",
        "PostgresPositionOpenOutcomeRepository",
        "PostgresTradeRepository",
        "PostgresPositionRepository",
        "PostgresExitRepository",
    ):
        monkeypatch.setattr(recovery, name, EmptyRepo)
    monkeypatch.setattr(recovery, "PostgresIndicatorCheckpointRepository", CheckpointRepo)


def test_recovery_returns_new_without_persisted_run(monkeypatch: pytest.MonkeyPatch) -> None:
    run = _run()
    _repos(monkeypatch, None)
    result = RecoveryBootstrap().inspect(
        session=SimpleNamespace(), requested_run=run, instrument_id=InstrumentId("NSE:X")
    )
    assert result.disposition is RecoveryDisposition.NEW
    assert result.indicator_state is None


def test_recovery_rejects_provenance_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    run = _run()
    _repos(
        monkeypatch,
        RunIdentity(
            run.run_id, run.strategy, run.config_id, "other", run.engine_calculation_version
        ),
    )
    with pytest.raises(ContradictoryFactError):
        RecoveryBootstrap().inspect(
            session=SimpleNamespace(), requested_run=run, instrument_id=InstrumentId("NSE:X")
        )


def test_recovery_accepts_persisted_run_before_first_checkpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _run()
    _repos(monkeypatch, run)
    result = RecoveryBootstrap().inspect(
        session=SimpleNamespace(), requested_run=run, instrument_id=InstrumentId("NSE:X")
    )
    assert result.disposition is RecoveryDisposition.RESUMABLE
    assert result.indicator_state is None
