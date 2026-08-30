"""Immutable audit facts for domain lifecycle transitions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from signalforge.domain.ids import StateTransitionId, deterministic_id
from signalforge.domain.provenance import RunIdentity
from signalforge.domain.time import require_aware


class TransitionEntityType(StrEnum):
    ARMED_SETUP = "armed_setup"
    TRADE = "trade"
    POSITION = "position"


def _validate_transition_fields(
    *,
    entity_id: str,
    from_state: str,
    to_state: str,
    cause_type: str,
    cause_id: str,
    occurred_at: datetime,
) -> None:
    require_aware(occurred_at)
    for name, value in (
        ("entity_id", entity_id),
        ("from_state", from_state),
        ("to_state", to_state),
        ("cause_type", cause_type),
        ("cause_id", cause_id),
    ):
        if not value or not value.strip():
            raise ValueError(f"StateTransition {name} must not be empty")
    if from_state == to_state:
        raise ValueError("StateTransition must change state")


@dataclass(frozen=True, slots=True)
class StateTransition:
    """Immutable audit fact for a completed domain state change."""

    transition_id: StateTransitionId
    entity_type: TransitionEntityType
    entity_id: str
    from_state: str
    to_state: str
    cause_type: str
    cause_id: str
    occurred_at: datetime
    run: RunIdentity

    def __post_init__(self) -> None:
        _validate_transition_fields(
            entity_id=self.entity_id,
            from_state=self.from_state,
            to_state=self.to_state,
            cause_type=self.cause_type,
            cause_id=self.cause_id,
            occurred_at=self.occurred_at,
        )
        if self.transition_id != self.expected_id():
            raise ValueError("StateTransition ID does not match deterministic logical identity")

    @classmethod
    def create(
        cls,
        *,
        entity_type: TransitionEntityType,
        entity_id: str,
        from_state: str,
        to_state: str,
        cause_type: str,
        cause_id: str,
        occurred_at: datetime,
        run: RunIdentity,
    ) -> StateTransition:
        """Create a deterministic audit fact for one logical state change."""

        _validate_transition_fields(
            entity_id=entity_id,
            from_state=from_state,
            to_state=to_state,
            cause_type=cause_type,
            cause_id=cause_id,
            occurred_at=occurred_at,
        )
        transition_id = deterministic_id(
            StateTransitionId,
            str(run.run_id),
            entity_type.value,
            entity_id,
            from_state,
            to_state,
            cause_type,
            cause_id,
            occurred_at.isoformat(),
        )
        return cls(
            transition_id=transition_id,
            entity_type=entity_type,
            entity_id=entity_id,
            from_state=from_state,
            to_state=to_state,
            cause_type=cause_type,
            cause_id=cause_id,
            occurred_at=occurred_at,
            run=run,
        )

    def expected_id(self) -> StateTransitionId:
        return deterministic_id(
            StateTransitionId,
            str(self.run.run_id),
            self.entity_type.value,
            self.entity_id,
            self.from_state,
            self.to_state,
            self.cause_type,
            self.cause_id,
            self.occurred_at.isoformat(),
        )
