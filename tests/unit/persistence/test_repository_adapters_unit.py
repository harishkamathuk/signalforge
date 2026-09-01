from __future__ import annotations

import inspect

from signalforge.persistence import repositories


def test_postgres_adapters_keep_transaction_ownership_with_caller() -> None:
    source = inspect.getsource(repositories)

    assert ".commit(" not in source
    assert ".rollback(" not in source
    assert "create_engine" not in source
    assert "sessionmaker" not in source
    assert "begin_nested" in source
    assert "on_conflict_do_nothing" in source


def test_sf045_adapter_inventory_includes_only_accepted_repositories() -> None:
    names = set(vars(repositories))

    assert {
        "PostgresRunProvenanceRepository",
        "PostgresStrategyEvaluationRepository",
        "PostgresSignalRepository",
        "PostgresTriggerEventRepository",
        "PostgresEntryIntentRepository",
        "PostgresFillRepository",
        "PostgresExitRepository",
        "PostgresStateTransitionRepository",
    } <= names
    assert {
        "PostgresArmedSetupRepository",
        "PostgresTradeRepository",
        "PostgresPositionRepository",
    } <= names
    assert "UnitOfWork" not in names
    assert "PostgresCheckpointRepository" not in names
    assert "PostgresLifecycleProjectionRepository" not in names


def test_authoritative_adapters_use_conditional_predecessor_updates() -> None:
    source = inspect.getsource(repositories)

    assert source.count("sa.update(") >= 3
    assert "ArmedSetupRecord.state == ArmedSetupState.ARMED.value" in source
    assert "TradeRecord.state == TradeState.OPEN.value" in source
    assert "PositionRecord.state == PositionState.OPEN.value" in source
    assert source.count("self._session.expire_all()") >= 3
