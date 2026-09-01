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


def test_sf045b_adapter_inventory_excludes_later_issue_repositories() -> None:
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
    assert "PostgresArmedSetupRepository" not in names
    assert "PostgresTradeRepository" not in names
    assert "PostgresPositionRepository" not in names
    assert "UnitOfWork" not in names
