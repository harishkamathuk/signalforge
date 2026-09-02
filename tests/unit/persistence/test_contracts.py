from __future__ import annotations

import inspect

from signalforge.persistence import contracts

EXPECTED_CONTRACTS = {
    "RunProvenanceRepository",
    "StrategyEvaluationRepository",
    "SignalRepository",
    "ArmedSetupRepository",
    "TriggerEventRepository",
    "EntryIntentRepository",
    "FillRepository",
    "TradeRepository",
    "PositionRepository",
    "ExitRepository",
    "StateTransitionRepository",
    "IndicatorCheckpointRepository",
}


def test_repository_contract_inventory_is_complete_and_sql_free() -> None:
    assert EXPECTED_CONTRACTS <= set(vars(contracts))
    source = inspect.getsource(contracts)
    assert "sqlalchemy" not in source.lower()
    assert "postgresql" not in source.lower()
    assert "list_all" not in source
    assert "IndicatorCheckpointRepository" in source
