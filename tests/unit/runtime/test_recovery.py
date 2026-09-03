from dataclasses import replace
from types import SimpleNamespace
from typing import cast

import pytest
from sqlalchemy.orm import Session

from signalforge.domain.audit import TransitionEntityType
from signalforge.domain.ids import ConfigId, InstrumentId, RunId
from signalforge.domain.position_outcomes import PositionOpenOutcome, PositionOpenOutcomeType
from signalforge.domain.provenance import RunIdentity, StrategyIdentity
from signalforge.persistence.errors import ContradictoryFactError
from signalforge.runtime import recovery
from signalforge.runtime.recovery import RecoveryBootstrap, RecoveryDisposition
from tests.integration.persistence.test_repository_adapters_postgres import _transition, facts


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

        def find_for_run(self, run_id: RunId) -> tuple[object, ...]:
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
        "PostgresStateTransitionRepository",
    ):
        monkeypatch.setattr(recovery, name, EmptyRepo)
    monkeypatch.setattr(recovery, "PostgresIndicatorCheckpointRepository", CheckpointRepo)


def test_recovery_returns_new_without_persisted_run(monkeypatch: pytest.MonkeyPatch) -> None:
    run = _run()
    _repos(monkeypatch, None)
    result = RecoveryBootstrap().inspect(
        session=cast(Session, SimpleNamespace()),
        requested_run=run,
        instrument_id=InstrumentId("NSE:X"),
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
            session=cast(Session, SimpleNamespace()),
            requested_run=run,
            instrument_id=InstrumentId("NSE:X"),
        )


def test_recovery_accepts_persisted_run_before_first_checkpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _run()
    _repos(monkeypatch, run)
    result = RecoveryBootstrap().inspect(
        session=cast(Session, SimpleNamespace()),
        requested_run=run,
        instrument_id=InstrumentId("NSE:X"),
    )
    assert result.disposition is RecoveryDisposition.RESUMABLE
    assert result.indicator_state is None


def _stateful_repos(
    monkeypatch: pytest.MonkeyPatch,
    run: RunIdentity,
    *,
    signals: tuple[object, ...] = (),
    setups: tuple[object, ...] = (),
    fills: tuple[object, ...] = (),
    outcomes: tuple[object, ...] = (),
    trades: tuple[object, ...] = (),
    positions: tuple[object, ...] = (),
    exits: tuple[object, ...] = (),
    transitions: tuple[object, ...] = (),
) -> None:
    class RunRepo:
        def __init__(self, session: object) -> None:
            pass

        def get(self, run_id: RunId) -> RunIdentity:
            return run

    def repository(values: tuple[object, ...]) -> type[object]:
        class Repo:
            def __init__(self, session: object) -> None:
                pass

            def find_for_run_instrument(
                self, run_id: RunId, instrument_id: InstrumentId
            ) -> tuple[object, ...]:
                return values

            def find_for_run(self, run_id: RunId) -> tuple[object, ...]:
                return values

        return Repo

    class CheckpointRepo:
        def __init__(self, session: object) -> None:
            pass

        def get(self, run_id: RunId, instrument_id: InstrumentId) -> None:
            return None

    monkeypatch.setattr(recovery, "PostgresRunProvenanceRepository", RunRepo)
    for name, values in (
        ("PostgresSignalRepository", signals),
        ("PostgresArmedSetupRepository", setups),
        ("PostgresFillRepository", fills),
        ("PostgresPositionOpenOutcomeRepository", outcomes),
        ("PostgresTradeRepository", trades),
        ("PostgresPositionRepository", positions),
        ("PostgresExitRepository", exits),
        ("PostgresStateTransitionRepository", transitions),
    ):
        monkeypatch.setattr(recovery, name, repository(values))
    monkeypatch.setattr(recovery, "PostgresIndicatorCheckpointRepository", CheckpointRepo)


def _inspect(
    monkeypatch: pytest.MonkeyPatch, run: RunIdentity, **values: tuple[object, ...]
) -> None:
    _stateful_repos(monkeypatch, run, **values)
    RecoveryBootstrap().inspect(
        session=cast(Session, SimpleNamespace()),
        requested_run=run,
        instrument_id=InstrumentId("NSE:SF045B"),
    )


def test_recovery_rejects_cross_run_signal_lineage(monkeypatch: pytest.MonkeyPatch) -> None:
    value = facts("recovery-cross-run")
    foreign = facts("recovery-cross-run-foreign")
    _stateful_repos(monkeypatch, value.run, signals=(foreign.signal,), setups=(value.setup,))
    with pytest.raises(ContradictoryFactError):
        RecoveryBootstrap().inspect(
            session=cast(Session, SimpleNamespace()),
            requested_run=value.run,
            instrument_id=value.signal.instrument_id,
        )


def test_recovery_rejects_multiple_armed_setups(monkeypatch: pytest.MonkeyPatch) -> None:
    value = facts("recovery-multi-armed")
    _stateful_repos(
        monkeypatch, value.run, signals=(value.signal,), setups=(value.setup, value.setup)
    )
    with pytest.raises(ContradictoryFactError):
        RecoveryBootstrap().inspect(
            session=cast(Session, SimpleNamespace()),
            requested_run=value.run,
            instrument_id=value.signal.instrument_id,
        )


def test_recovery_rejects_multiple_open_graphs(monkeypatch: pytest.MonkeyPatch) -> None:
    value = facts("recovery-multi-open")
    outcome = PositionOpenOutcome.create(
        fill_id=value.fill.fill_id,
        signal_id=value.signal.signal_id,
        outcome=PositionOpenOutcomeType.OPENED,
        decided_at=value.fill.filled_at,
        run=value.run,
    )
    _stateful_repos(
        monkeypatch,
        value.run,
        signals=(value.signal,),
        fills=(value.fill,),
        outcomes=(outcome,),
        trades=(value.trade, value.trade),
        positions=(value.position, value.position),
    )
    with pytest.raises(ContradictoryFactError):
        RecoveryBootstrap().inspect(
            session=cast(Session, SimpleNamespace()),
            requested_run=value.run,
            instrument_id=value.signal.instrument_id,
        )


@pytest.mark.parametrize("trade_closed,position_closed", ((False, True), (True, False)))
def test_recovery_rejects_trade_position_state_disagreement(
    monkeypatch: pytest.MonkeyPatch, trade_closed: bool, position_closed: bool
) -> None:
    value = facts(f"recovery-state-mismatch-{trade_closed}-{position_closed}")
    trade = replace(value.trade)
    position = replace(value.position)
    if trade_closed:
        trade.close(exit_id=value.exit_fact.exit_id, at=value.exit_fact.exited_at)
    if position_closed:
        position.close(at=value.exit_fact.exited_at)
    _stateful_repos(monkeypatch, value.run, trades=(trade,), positions=(position,))
    with pytest.raises(ContradictoryFactError):
        RecoveryBootstrap().inspect(
            session=cast(Session, SimpleNamespace()),
            requested_run=value.run,
            instrument_id=value.signal.instrument_id,
        )


def test_recovery_rejects_closed_lifecycle_without_matching_transition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = facts("recovery-transition-mismatch")
    trade = replace(value.trade)
    trade.close(exit_id=value.exit_fact.exit_id, at=value.exit_fact.exited_at)
    position = replace(value.position)
    position.close(at=value.exit_fact.exited_at)
    wrong = _transition(
        value,
        entity=TransitionEntityType.TRADE,
        entity_id=str(value.trade.trade_id),
        before="open",
        after="closed",
        cause_type="exit",
        cause_id="different-exit",
        occurred_at=value.exit_fact.exited_at,
    )
    _stateful_repos(
        monkeypatch,
        value.run,
        trades=(trade,),
        positions=(position,),
        exits=(value.exit_fact,),
        transitions=(wrong,),
    )
    with pytest.raises(ContradictoryFactError):
        RecoveryBootstrap().inspect(
            session=cast(Session, SimpleNamespace()),
            requested_run=value.run,
            instrument_id=value.signal.instrument_id,
        )
