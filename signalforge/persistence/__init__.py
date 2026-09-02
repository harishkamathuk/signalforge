"""PostgreSQL persistence metadata and infrastructure boundaries."""

from signalforge.persistence.models import Base
from signalforge.persistence.repositories import (
    PostgresArmedSetupRepository,
    PostgresEntryIntentRepository,
    PostgresExitRepository,
    PostgresFillRepository,
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
    "PostgresArmedSetupRepository",
    "PostgresEntryIntentRepository",
    "PostgresExitRepository",
    "PostgresFillRepository",
    "PostgresPositionRepository",
    "PostgresRunProvenanceRepository",
    "PostgresSignalRepository",
    "PostgresStateTransitionRepository",
    "PostgresTradeRepository",
    "PostgresStrategyEvaluationRepository",
    "PostgresTriggerEventRepository",
]
