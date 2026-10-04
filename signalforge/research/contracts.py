"""Typed deterministic contracts for reproducible SignalForge research experiments."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Self

from signalforge.config.identity import ConfigIdentity, config_hash
from signalforge.config.strategy_registry import (
    DEFAULT_STRATEGY_REGISTRY,
    StrategyRegistry,
    StrategySelection,
)
from signalforge.domain.ids import DatasetId, ExperimentId, InstrumentId, UniverseId
from signalforge.domain.instruments import TickSizeSchedule
from signalforge.domain.money import Quantity
from signalforge.domain.provenance import StrategyIdentity


@dataclass(frozen=True, slots=True)
class UniverseDefinition:
    """Explicit deterministic instrument universe for one research experiment."""

    instruments: tuple[InstrumentId, ...]

    def __post_init__(self) -> None:
        if not self.instruments:
            raise ValueError("Research universe must contain at least one instrument")
        if len(set(self.instruments)) != len(self.instruments):
            raise ValueError("Research universe instruments must be unique")
        object.__setattr__(
            self,
            "instruments",
            tuple(sorted(self.instruments, key=str)),
        )

    @property
    def universe_id(self) -> UniverseId:
        """Return content-derived identity independent of caller input order."""

        digest = config_hash({"instruments": [str(item) for item in self.instruments]})
        return UniverseId(digest)


@dataclass(frozen=True, slots=True)
class DatasetSourceDefinition:
    """Content-derived source identity for one instrument's historical market events."""

    instrument_id: InstrumentId
    source_id: str

    def __post_init__(self) -> None:
        if not self.source_id or not self.source_id.strip():
            raise ValueError("Dataset source_id must not be empty")


@dataclass(frozen=True, slots=True)
class DatasetDefinition:
    """Canonical historical source set and requested experiment time range."""

    sources: tuple[DatasetSourceDefinition, ...]
    start_at: datetime
    end_at: datetime

    def __post_init__(self) -> None:
        if not self.sources:
            raise ValueError("Research dataset must contain at least one source")
        instruments = tuple(source.instrument_id for source in self.sources)
        if len(set(instruments)) != len(instruments):
            raise ValueError("Research dataset must contain one source per instrument")
        _require_aware(self.start_at, "start_at")
        _require_aware(self.end_at, "end_at")
        if self.end_at <= self.start_at:
            raise ValueError("Research dataset end_at must be after start_at")
        object.__setattr__(
            self,
            "sources",
            tuple(sorted(self.sources, key=lambda item: str(item.instrument_id))),
        )

    @property
    def dataset_id(self) -> DatasetId:
        """Return identity from canonical source content IDs and requested range."""

        digest = config_hash(
            {
                "sources": [
                    {
                        "instrument_id": str(source.instrument_id),
                        "source_id": source.source_id,
                    }
                    for source in self.sources
                ],
                "start_at": self.start_at.isoformat(),
                "end_at": self.end_at.isoformat(),
            }
        )
        return DatasetId(digest)


@dataclass(frozen=True, slots=True)
class InstrumentExecutionDefinition:
    """Replay execution inputs that are material to one instrument's research result."""

    instrument_id: InstrumentId
    quantity: Quantity
    tick_schedule: TickSizeSchedule

    def __post_init__(self) -> None:
        if self.tick_schedule.instrument_id != self.instrument_id:
            raise ValueError("Execution tick schedule instrument must match instrument_id")

    def semantic_mapping(self) -> dict[str, object]:
        """Return canonical execution content used by experiment identity."""

        return {
            "instrument_id": str(self.instrument_id),
            "quantity": self.quantity.value,
            "tick_rules": [
                {
                    "tick_size": rule.tick_size.value,
                    "effective_from": rule.effective_from.isoformat(),
                    "effective_to": (
                        None if rule.effective_to is None else rule.effective_to.isoformat()
                    ),
                }
                for rule in self.tick_schedule.rules
            ],
        }


@dataclass(frozen=True, slots=True)
class ExperimentDefinition:
    """Validated strategy/universe/dataset definition with deterministic provenance."""

    experiment_id: ExperimentId
    strategy_selection: StrategySelection
    strategy_identity: StrategyIdentity
    config_identity: ConfigIdentity
    universe: UniverseDefinition
    dataset: DatasetDefinition
    engine_calculation_version: str
    execution: tuple[InstrumentExecutionDefinition, ...]

    @classmethod
    def create(
        cls,
        *,
        strategy_selection: StrategySelection,
        universe: UniverseDefinition,
        dataset: DatasetDefinition,
        engine_calculation_version: str,
        execution: tuple[InstrumentExecutionDefinition, ...],
        registry: StrategyRegistry = DEFAULT_STRATEGY_REGISTRY,
    ) -> Self:
        """Validate the complete experiment and derive its deterministic identity."""

        if not engine_calculation_version or not engine_calculation_version.strip():
            raise ValueError("engine_calculation_version must not be empty")

        strategy = registry.resolve(strategy_selection)
        ordered_execution = tuple(sorted(execution, key=lambda item: str(item.instrument_id)))
        if not ordered_execution:
            raise ValueError("Research experiment requires execution configuration")
        execution_instruments = tuple(item.instrument_id for item in ordered_execution)
        if len(set(execution_instruments)) != len(execution_instruments):
            raise ValueError("Research execution instruments must be unique")

        universe_set = set(universe.instruments)
        dataset_set = {source.instrument_id for source in dataset.sources}
        execution_set = set(execution_instruments)
        if dataset_set != universe_set:
            raise ValueError("Research dataset instruments must exactly match universe")
        if execution_set != universe_set:
            raise ValueError("Research execution instruments must exactly match universe")

        config_identity = strategy.config_identity
        digest = config_hash(
            {
                "strategy_id": strategy.identity.strategy_id,
                "strategy_version": strategy.identity.strategy_version,
                "config_hash": config_identity.config_hash,
                "universe_id": str(universe.universe_id),
                "dataset_id": str(dataset.dataset_id),
                "engine_calculation_version": engine_calculation_version,
                "execution": [item.semantic_mapping() for item in ordered_execution],
            }
        )
        return cls(
            experiment_id=ExperimentId(digest),
            strategy_selection=strategy_selection,
            strategy_identity=strategy.identity,
            config_identity=config_identity,
            universe=universe,
            dataset=dataset,
            engine_calculation_version=engine_calculation_version,
            execution=ordered_execution,
        )


def _require_aware(value: datetime, field: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"Research dataset {field} must be timezone-aware")
