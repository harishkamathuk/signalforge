"""SQL-agnostic repository contracts for canonical M6 persistence."""

from __future__ import annotations

from typing import Protocol

from signalforge.domain.armed import ArmedSetup
from signalforge.domain.audit import StateTransition
from signalforge.domain.execution import EntryIntent, Fill, TriggerEvent
from signalforge.domain.exits import Exit
from signalforge.domain.ids import (
    EntryIntentId,
    ExitId,
    FillId,
    InstrumentId,
    PositionId,
    PositionOpenOutcomeId,
    RunId,
    SignalId,
    StateTransitionId,
    TradeId,
    TriggerEventId,
)
from signalforge.domain.position_outcomes import PositionOpenOutcome
from signalforge.domain.positions import Position
from signalforge.domain.provenance import RunIdentity
from signalforge.domain.signals import Signal
from signalforge.domain.strategy import StrategyEvaluation
from signalforge.domain.time import CandleInterval
from signalforge.domain.trades import Trade


class RunProvenanceRepository(Protocol):
    """Persist immutable strategy/config/run provenance."""

    def add(self, run: RunIdentity) -> RunIdentity: ...

    def get(self, run_id: RunId) -> RunIdentity | None: ...


class StrategyEvaluationRepository(Protocol):
    """Persist immutable run-scoped strategy decisions."""

    def append(self, run_id: RunId, evaluation: StrategyEvaluation) -> StrategyEvaluation: ...

    def get(
        self,
        run_id: RunId,
        instrument_id: InstrumentId,
        interval: CandleInterval,
    ) -> StrategyEvaluation | None: ...


class SignalRepository(Protocol):
    def append(self, signal: Signal) -> Signal: ...

    def get(self, signal_id: SignalId) -> Signal | None: ...


class ArmedSetupRepository(Protocol):
    def upsert(self, run_id: RunId, setup: ArmedSetup) -> ArmedSetup: ...

    def get(self, signal_id: SignalId) -> ArmedSetup | None: ...


class TriggerEventRepository(Protocol):
    def append(self, event: TriggerEvent) -> TriggerEvent: ...

    def get(self, event_id: TriggerEventId) -> TriggerEvent | None: ...


class EntryIntentRepository(Protocol):
    def append(self, intent: EntryIntent) -> EntryIntent: ...

    def get(self, intent_id: EntryIntentId) -> EntryIntent | None: ...


class FillRepository(Protocol):
    def append(self, fill: Fill) -> Fill: ...

    def get(self, fill_id: FillId) -> Fill | None: ...


class TradeRepository(Protocol):
    def upsert(self, trade: Trade) -> Trade: ...

    def get(self, trade_id: TradeId) -> Trade | None: ...


class PositionRepository(Protocol):
    def upsert(self, position: Position) -> Position: ...

    def get(self, position_id: PositionId) -> Position | None: ...


class PositionOpenOutcomeRepository(Protocol):
    def append(self, outcome: PositionOpenOutcome) -> PositionOpenOutcome: ...

    def get(self, outcome_id: PositionOpenOutcomeId) -> PositionOpenOutcome | None: ...


class ExitRepository(Protocol):
    def append(self, exit_fact: Exit) -> Exit: ...

    def get(self, exit_id: ExitId) -> Exit | None: ...


class StateTransitionRepository(Protocol):
    def append(self, transition: StateTransition) -> StateTransition: ...

    def get(self, transition_id: StateTransitionId) -> StateTransition | None: ...
