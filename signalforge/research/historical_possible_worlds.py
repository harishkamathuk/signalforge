"""SF-097 synthetic proof: deterministic, evidence-conditional historical worlds.

Not wired to the accepted historical runner. An audited adapter must first prove
which OHLCV-compatible alternatives are supported; none are inferred here.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Callable


class Lifecycle(StrEnum):
    FLAT = "flat"
    ARMED = "armed"
    OPEN = "open"


class TransitionKind(StrEnum):
    NOOP = "noop"
    ARM = "arm"
    ENTER = "enter"
    EXPIRE = "expire"
    EXIT = "exit"
    BLOCK = "block"
    KEEP = "keep"


@dataclass(frozen=True, slots=True)
class Position:
    """Branch-local modeled setup, never an observed trade."""

    signal_id: str
    stop: Decimal
    trigger: Decimal
    target: Decimal | None = None
    entry_fill: Decimal | None = None

    def __post_init__(self) -> None:
        if not self.signal_id:
            raise ValueError("signal identity required")
        for price in (self.stop, self.trigger, self.target, self.entry_fill):
            if price is not None and (not price.is_finite() or price <= 0):
                raise ValueError("positive finite price required")
        if self.stop >= self.trigger:
            raise ValueError("stop must be below trigger")
        if (self.entry_fill is None) != (self.target is None):
            raise ValueError("entry and target must both be present or absent")
        if self.entry_fill is not None and (
            self.entry_fill <= self.stop or self.target is None
            or self.target <= self.entry_fill
        ):
            raise ValueError("open position must have positive risk and target")


@dataclass(frozen=True, slots=True)
class CausalEvent:
    """Supported conditional transition, not fabricated market chronology."""

    minute_key: str
    kind: TransitionKind
    reason: str
    signal_id: str | None
    outcome_r: Decimal | None = None

    def __post_init__(self) -> None:
        if not self.minute_key or not self.reason:
            raise ValueError("causal identity and reason required")
        if self.outcome_r is not None and not self.outcome_r.is_finite():
            raise ValueError("non-finite modeled R")


@dataclass(frozen=True, slots=True)
class World:
    """Independent possible history; equal future state does not erase history."""

    lifecycle: Lifecycle = Lifecycle.FLAT
    position: Position | None = None
    events: tuple[CausalEvent, ...] = ()

    def __post_init__(self) -> None:
        if (self.position is None) != (self.lifecycle is Lifecycle.FLAT):
            raise ValueError("exactly one setup iff ARMED or OPEN")
        if self.position is not None and (
            (self.position.entry_fill is None) != (self.lifecycle is Lifecycle.ARMED)
        ):
            raise ValueError("position contradicts lifecycle")

    @property
    def identity(self) -> str:
        p = self.position
        mapping = {
            "lifecycle": self.lifecycle.value,
            "position": None if p is None else (
                p.signal_id, str(p.stop), str(p.trigger),
                None if p.target is None else str(p.target),
                None if p.entry_fill is None else str(p.entry_fill),
            ),
            "events": [
                (e.minute_key, e.kind.value, e.reason, e.signal_id,
                 None if e.outcome_r is None else str(e.outcome_r))
                for e in self.events
            ],
        }
        return hashlib.sha256(
            json.dumps(mapping, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()


@dataclass(frozen=True, slots=True)
class SupportedTransition:
    kind: TransitionKind
    reason: str
    position: Position | None = None
    outcome_r: Decimal | None = None


@dataclass(frozen=True, slots=True)
class PropagationPolicy:
    max_worlds: int = 16
    max_total_transitions: int = 1000

    def __post_init__(self) -> None:
        if self.max_worlds < 1 or self.max_total_transitions < 1:
            raise ValueError("positive resource budgets required")


@dataclass(frozen=True, slots=True)
class PropagationResult:
    worlds: tuple[World, ...]
    total_transitions: int
    unresolved_at: str | None = None
    unresolved_reason: str | None = None

    @property
    def complete(self) -> bool:
        return self.unresolved_at is None


def _apply(world: World, minute_key: str, transition: SupportedTransition) -> World:
    kind = transition.kind
    current = world.position
    new_position = current
    state = world.lifecycle
    if kind is TransitionKind.NOOP and state is Lifecycle.FLAT:
        pass
    elif kind is TransitionKind.ARM and state is Lifecycle.FLAT:
        if transition.position is None or transition.position.entry_fill is not None:
            raise ValueError("ARM needs one unfilled setup")
        state, new_position = Lifecycle.ARMED, transition.position
    elif kind is TransitionKind.ENTER and state is Lifecycle.ARMED:
        if (current is None or transition.position is None
                or current.signal_id != transition.position.signal_id
                or transition.position.entry_fill is None
                or current.stop != transition.position.stop
                or current.trigger != transition.position.trigger):
            raise ValueError("ENTER must fill the existing branch-local setup")
        state, new_position = Lifecycle.OPEN, transition.position
    elif kind is TransitionKind.EXPIRE and state is Lifecycle.ARMED:
        state, new_position = Lifecycle.FLAT, None
    elif kind is TransitionKind.EXIT and state is Lifecycle.OPEN:
        if transition.outcome_r is None:
            raise ValueError("EXIT requires modeled R evidence")
        state, new_position = Lifecycle.FLAT, None
    elif kind in (TransitionKind.BLOCK, TransitionKind.KEEP) and state is not Lifecycle.FLAT:
        pass
    else:
        raise ValueError(f"unsupported {kind.value} from {state.value}")
    if kind not in (TransitionKind.ARM, TransitionKind.ENTER) and transition.position is not None:
        raise ValueError("unexpected replacement setup")
    if kind is not TransitionKind.EXIT and transition.outcome_r is not None:
        raise ValueError("modeled R only valid for EXIT")
    event = CausalEvent(
        minute_key, kind, transition.reason,
        current.signal_id if current is not None else (
            transition.position.signal_id if transition.position is not None else None
        ),
        transition.outcome_r,
    )
    return World(state, new_position, (*world.events, event))


def propagate(
    prior: PropagationResult,
    minute_key: str,
    resolver: Callable[[World], tuple[SupportedTransition, ...]],
    policy: PropagationPolicy,
) -> PropagationResult:
    """Consume all declared supported alternatives or fail closed atomically.

    A later audited strategy/bar adapter must prove alternative completeness.
    This synthetic proof does not claim that any generated history occurred.
    """
    if not prior.complete:
        raise ValueError("cannot resume unresolved propagation")
    if not minute_key or (
        prior.worlds and prior.worlds[0].events
        and minute_key <= prior.worlds[0].events[-1].minute_key
    ):
        raise ValueError("minute keys must increase strictly")
    proposed: list[World] = []
    count = prior.total_transitions
    for world in sorted(prior.worlds, key=lambda item: item.identity):
        alternatives = resolver(world)
        if not alternatives:
            raise ValueError("all supported possibilities must be supplied")
        for alternative in alternatives:
            count += 1
            if count > policy.max_total_transitions:
                return PropagationResult((), count, minute_key, "transition_budget_exhausted")
            proposed.append(_apply(world, minute_key, alternative))
            if len(proposed) > policy.max_worlds:
                return PropagationResult((), count, minute_key, "world_budget_exhausted")
    identities = [world.identity for world in proposed]
    if len(identities) != len(set(identities)):
        raise ValueError("duplicate causal alternatives require evidence deduplication")
    return PropagationResult(tuple(sorted(proposed, key=lambda item: item.identity)), count)
