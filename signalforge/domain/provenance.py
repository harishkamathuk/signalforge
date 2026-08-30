"""Immutable strategy and run provenance models."""

from __future__ import annotations

from dataclasses import dataclass

from signalforge.domain.ids import ConfigId, RunId


@dataclass(frozen=True, slots=True)
class StrategyIdentity:
    strategy_id: str
    strategy_version: str

    def __post_init__(self) -> None:
        if not self.strategy_id or not self.strategy_id.strip():
            raise ValueError("strategy_id must not be empty")
        if not self.strategy_version or not self.strategy_version.strip():
            raise ValueError("strategy_version must not be empty")


@dataclass(frozen=True, slots=True)
class RunIdentity:
    run_id: RunId
    strategy: StrategyIdentity
    config_id: ConfigId
    config_hash: str
    engine_calculation_version: str

    def __post_init__(self) -> None:
        if not self.config_hash or not self.config_hash.strip():
            raise ValueError("config_hash must not be empty")
        if not self.engine_calculation_version or not self.engine_calculation_version.strip():
            raise ValueError("engine_calculation_version must not be empty")
