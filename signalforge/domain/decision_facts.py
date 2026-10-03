"""Strategy-neutral immutable audit facts for completed-candle decisions."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import TypeAlias

from signalforge.domain.ids import InstrumentId
from signalforge.domain.time import CandleInterval

DecisionDiagnosticValue: TypeAlias = str | bool | int | None


@dataclass(frozen=True, slots=True)
class StrategyDecisionFact:
    """Persistable strategy-neutral projection of one completed-candle decision.

    Diagnostics are audit data only. They are deliberately restricted to simple
    JSON-safe scalar values so this representation cannot become an executable
    strategy language.
    """

    instrument_id: InstrumentId
    interval: CandleInterval
    decision_kind: str
    qualified: bool
    actionable: bool
    reasons: tuple[str, ...]
    diagnostics: tuple[tuple[str, DecisionDiagnosticValue], ...]

    def __post_init__(self) -> None:
        if not self.decision_kind.strip():
            raise ValueError("Strategy decision kind must not be empty")
        if self.actionable and not self.qualified:
            raise ValueError("Actionable strategy decision fact must be qualified")
        keys = tuple(key for key, _ in self.diagnostics)
        if keys != tuple(sorted(keys)) or len(keys) != len(set(keys)):
            raise ValueError("Strategy decision diagnostics must have unique sorted keys")
        for key, value in self.diagnostics:
            if not key:
                raise ValueError("Strategy decision diagnostic keys must not be empty")
            if not isinstance(value, (str, bool, int, type(None))):
                raise TypeError(
                    "Strategy decision diagnostics support only str/bool/int/None"
                )

    @classmethod
    def create(
        cls,
        *,
        instrument_id: InstrumentId,
        interval: CandleInterval,
        decision_kind: str,
        qualified: bool,
        actionable: bool,
        reasons: tuple[str, ...],
        diagnostics: dict[str, DecisionDiagnosticValue],
    ) -> "StrategyDecisionFact":
        """Create a fact with deterministic diagnostic ordering."""

        return cls(
            instrument_id=instrument_id,
            interval=interval,
            decision_kind=decision_kind,
            qualified=qualified,
            actionable=actionable,
            reasons=reasons,
            diagnostics=tuple(sorted(diagnostics.items())),
        )

    @property
    def diagnostic_mapping(self) -> MappingProxyType[str, DecisionDiagnosticValue]:
        """Return immutable diagnostics for presentation or persistence."""

        return MappingProxyType(dict(self.diagnostics))
