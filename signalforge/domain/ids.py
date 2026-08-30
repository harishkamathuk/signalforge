"""Strongly typed identifiers for SignalForge domain entities."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256


@dataclass(frozen=True, slots=True)
class _IdBase:
    """Immutable string-backed identifier with non-empty validation."""

    value: str

    def __post_init__(self) -> None:
        if not self.value or not self.value.strip():
            raise ValueError(f"{type(self).__name__} must not be empty")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class RunId(_IdBase):
    pass


@dataclass(frozen=True, slots=True)
class ConfigId(_IdBase):
    pass


@dataclass(frozen=True, slots=True)
class SignalId(_IdBase):
    pass


@dataclass(frozen=True, slots=True)
class TriggerEventId(_IdBase):
    pass


@dataclass(frozen=True, slots=True)
class EntryIntentId(_IdBase):
    pass


@dataclass(frozen=True, slots=True)
class FillId(_IdBase):
    pass


@dataclass(frozen=True, slots=True)
class TradeId(_IdBase):
    pass


@dataclass(frozen=True, slots=True)
class PositionId(_IdBase):
    pass


@dataclass(frozen=True, slots=True)
class ExitId(_IdBase):
    pass


@dataclass(frozen=True, slots=True)
class StateTransitionId(_IdBase):
    pass


@dataclass(frozen=True, slots=True)
class InstrumentId(_IdBase):
    pass


def deterministic_id[IdT: _IdBase](id_type: type[IdT], *parts: str) -> IdT:
    """Create a stable identifier from explicit logical identity components.

    The identifier type participates in the hash domain so identical parts used
    for different entity types cannot collide by construction.
    """

    if not parts:
        raise ValueError("deterministic_id requires at least one identity component")
    if any(not part or not part.strip() for part in parts):
        raise ValueError("deterministic_id components must not be empty")

    payload = "\x1f".join((id_type.__name__, *parts)).encode("utf-8")
    digest = sha256(payload).hexdigest()
    return id_type(digest)
