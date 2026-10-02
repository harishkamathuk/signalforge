"""Explicit in-process strategy registration and typed configuration resolution."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from signalforge.config.strategy_v1 import StrategyV1EvaluationConfig
from signalforge.domain.provenance import StrategyIdentity
from signalforge.runtime.strategy import Strategy
from signalforge.runtime.strategy_v1 import IntradayMomentumV1Strategy


class StrategyResolutionError(ValueError):
    """Base error for deterministic strategy startup/configuration failures."""


class UnknownStrategyError(StrategyResolutionError):
    """Raised when no registered strategy uses the requested strategy ID."""


class UnsupportedStrategyVersionError(StrategyResolutionError):
    """Raised when a known strategy ID does not support the requested version."""


class StrategyParameterValidationError(StrategyResolutionError):
    """Raised when registered typed configuration rejects supplied parameters."""


@dataclass(frozen=True, slots=True)
class StrategySelection:
    """Normalized strategy selection independent of serialization format."""

    strategy_id: str
    strategy_version: str
    parameters: Mapping[str, object]

    def __post_init__(self) -> None:
        if not self.strategy_id.strip():
            raise ValueError("Strategy selection ID must not be empty")
        if not self.strategy_version.strip():
            raise ValueError("Strategy selection version must not be empty")
        object.__setattr__(self, "parameters", MappingProxyType(dict(self.parameters)))


class StrategySelectionEnvelope(BaseModel):
    """Strict canonical external strategy-selection envelope."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    strategy_id: str = Field(alias="id")
    strategy_version: str = Field(alias="version")
    parameters: dict[str, object]

    @field_validator("strategy_id", "strategy_version")
    @classmethod
    def validate_non_empty(cls, value: str) -> str:
        """Reject blank selection identity fields before registry resolution."""

        if not value.strip():
            raise ValueError("Strategy selection identity fields must not be empty")
        return value


StrategyFactory = Callable[[Mapping[str, object]], Strategy]


@dataclass(frozen=True, slots=True)
class StrategyRegistration:
    """One explicit mapping from strategy identity/version to a typed factory."""

    strategy_id: str
    strategy_version: str
    factory: StrategyFactory

    def __post_init__(self) -> None:
        if not self.strategy_id.strip():
            raise ValueError("Registered strategy ID must not be empty")
        if not self.strategy_version.strip():
            raise ValueError("Registered strategy version must not be empty")


class StrategyRegistry:
    """Deterministic registry for known version-controlled strategy implementations."""

    def __init__(self, registrations: tuple[StrategyRegistration, ...]) -> None:
        entries: dict[tuple[str, str], StrategyRegistration] = {}
        versions_by_id: dict[str, set[str]] = {}
        for registration in registrations:
            key = (registration.strategy_id, registration.strategy_version)
            if key in entries:
                raise ValueError(
                    "Duplicate strategy registration: "
                    f"{registration.strategy_id} / {registration.strategy_version}"
                )
            entries[key] = registration
            versions_by_id.setdefault(registration.strategy_id, set()).add(
                registration.strategy_version
            )
        self._entries = MappingProxyType(entries)
        self._versions_by_id = MappingProxyType(
            {
                strategy_id: tuple(sorted(versions))
                for strategy_id, versions in sorted(versions_by_id.items())
            }
        )

    @property
    def registrations(self) -> tuple[tuple[str, str], ...]:
        """Return registered identity/version keys in deterministic order."""

        return tuple(sorted(self._entries))

    def resolve(self, selection: StrategySelection) -> Strategy:
        """Resolve one selection through its registered typed parser/factory.

        Raises:
            UnknownStrategyError: If the strategy ID is not registered.
            UnsupportedStrategyVersionError: If the ID exists but version does not.
            StrategyParameterValidationError: If typed parameter validation fails.
            StrategyResolutionError: If registration metadata contradicts the
                constructed strategy identity.
        """

        versions = self._versions_by_id.get(selection.strategy_id)
        if versions is None:
            raise UnknownStrategyError(f"Unknown strategy: {selection.strategy_id}")

        registration = self._entries.get(
            (selection.strategy_id, selection.strategy_version)
        )
        if registration is None:
            raise UnsupportedStrategyVersionError(
                f"Unsupported version {selection.strategy_version} "
                f"for strategy {selection.strategy_id}"
            )

        try:
            strategy = registration.factory(selection.parameters)
        except ValidationError as exc:
            raise StrategyParameterValidationError(
                f"Invalid parameters for {selection.strategy_id} / "
                f"{selection.strategy_version}: {exc}"
            ) from exc

        expected = StrategyIdentity(
            registration.strategy_id,
            registration.strategy_version,
        )
        # Registration metadata is the composition authority; accepting a
        # factory that constructs another identity would corrupt provenance.
        if strategy.identity != expected:
            raise StrategyResolutionError(
                "Registered strategy identity contradicts constructed strategy: "
                f"expected {expected.strategy_id} / {expected.strategy_version}, "
                f"got {strategy.identity.strategy_id} / "
                f"{strategy.identity.strategy_version}"
            )
        return strategy


def normalize_strategy_selection(raw: Mapping[str, object]) -> StrategySelection:
    """Normalize canonical envelope or legacy Strategy V1 mapping.

    Any envelope key activates strict envelope validation. This prevents malformed
    or ambiguous mixed shapes from silently falling back to Strategy V1.
    """

    envelope_keys = {"id", "version", "parameters"}
    if envelope_keys.intersection(raw):
        envelope = StrategySelectionEnvelope.model_validate(dict(raw))
        return StrategySelection(
            envelope.strategy_id,
            envelope.strategy_version,
            envelope.parameters,
        )

    # Legacy replay configuration historically placed Strategy V1 parameters
    # directly under "strategy"; preserving that input must not alter V1 hashing.
    return StrategySelection(
        "intraday_momentum_v1",
        "1.0.0",
        raw,
    )


def _build_intraday_momentum_v1(
    parameters: Mapping[str, object],
) -> Strategy:
    config = StrategyV1EvaluationConfig.model_validate(dict(parameters))
    return IntradayMomentumV1Strategy(config)


DEFAULT_STRATEGY_REGISTRY = StrategyRegistry(
    (
        StrategyRegistration(
            "intraday_momentum_v1",
            "1.0.0",
            _build_intraday_momentum_v1,
        ),
    )
)
