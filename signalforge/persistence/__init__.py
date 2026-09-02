"""PostgreSQL persistence metadata and infrastructure boundaries."""

from signalforge.persistence.coordinator import PersistenceCoordinator
from signalforge.persistence.models import Base
from signalforge.persistence.repositories import (
    PostgresArmedSetupRepository,
    PostgresEntryIntentRepository,
    PostgresExitRepository,
    PostgresFillRepository,
    PostgresIndicatorCheckpointRepository,
    PostgresPositionOpenOutcomeRepository,
    PostgresPositionRepository,
    PostgresRunProvenanceRepository,
    PostgresSignalRepository,
    PostgresStateTransitionRepository,
    PostgresStrategyEvaluationRepository,
    PostgresTradeRepository,
    PostgresTriggerEventRepository,
)

__all__ = [
    "Base",
    "PersistenceCoordinator",
    "PostgresArmedSetupRepository",
    "PostgresIndicatorCheckpointRepository",
    "PostgresEntryIntentRepository",
    "PostgresExitRepository",
    "PostgresFillRepository",
    "PostgresPositionOpenOutcomeRepository",
    "PostgresPositionRepository",
    "PostgresRunProvenanceRepository",
    "PostgresSignalRepository",
    "PostgresStateTransitionRepository",
    "PostgresTradeRepository",
    "PostgresStrategyEvaluationRepository",
    "PostgresTriggerEventRepository",
]
