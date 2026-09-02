"""Immutable durable outcome of attempting to open a position from a Fill."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from signalforge.domain.ids import FillId, PositionOpenOutcomeId, deterministic_id
from signalforge.domain.provenance import RunIdentity


class PositionOpenOutcomeType(StrEnum):
    OPENED = "opened"
    REJECTED_NON_POSITIVE_RISK = "rejected_non_positive_risk"


@dataclass(frozen=True, slots=True)
class PositionOpenOutcome:
    """One deterministic immutable completion outcome for one accepted entry Fill."""

    outcome_id: PositionOpenOutcomeId
    fill_id: FillId
    outcome: PositionOpenOutcomeType
    run: RunIdentity

    def __post_init__(self) -> None:
        if self.outcome_id != self.expected_id():
            raise ValueError("PositionOpenOutcome ID does not match deterministic identity")

    @classmethod
    def create(
        cls, *, fill_id: FillId, outcome: PositionOpenOutcomeType, run: RunIdentity
    ) -> PositionOpenOutcome:
        return cls(
            outcome_id=deterministic_id(PositionOpenOutcomeId, str(run.run_id), str(fill_id)),
            fill_id=fill_id,
            outcome=outcome,
            run=run,
        )

    def expected_id(self) -> PositionOpenOutcomeId:
        return deterministic_id(PositionOpenOutcomeId, str(self.run.run_id), str(self.fill_id))
