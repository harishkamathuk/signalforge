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
from signalforge.runtime.indicators import IndicatorEngineState


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

    def find_for_run_instrument(
        self, run_id: RunId, instrument_id: InstrumentId
    ) -> tuple[Signal, ...]: ...


class ArmedSetupRepository(Protocol):
    def upsert(self, run_id: RunId, setup: ArmedSetup) -> ArmedSetup: ...

    def get(self, signal_id: SignalId) -> ArmedSetup | None: ...

    def find_for_run_instrument(
        self, run_id: RunId, instrument_id: InstrumentId
    ) -> tuple[ArmedSetup, ...]: ...


class TriggerEventRepository(Protocol):
    def append(self, event: TriggerEvent) -> TriggerEvent: ...

    def get(self, event_id: TriggerEventId) -> TriggerEvent | None: ...


class EntryIntentRepository(Protocol):
    def append(self, intent: EntryIntent) -> EntryIntent: ...

    def get(self, intent_id: EntryIntentId) -> EntryIntent | None: ...


class FillRepository(Protocol):
    def append(self, fill: Fill) -> Fill: ...

    def get(self, fill_id: FillId) -> Fill | None: ...

    def find_for_run_instrument(
        self, run_id: RunId, instrument_id: InstrumentId
    ) -> tuple[Fill, ...]: ...


class TradeRepository(Protocol):
    def upsert(self, trade: Trade) -> Trade: ...

    def get(self, trade_id: TradeId) -> Trade | None: ...

    def find_for_run_instrument(
        self, run_id: RunId, instrument_id: InstrumentId
    ) -> tuple[Trade, ...]: ...


class PositionRepository(Protocol):
    def upsert(self, position: Position) -> Position: ...

    def get(self, position_id: PositionId) -> Position | None: ...

    def find_for_run_instrument(
        self, run_id: RunId, instrument_id: InstrumentId
    ) -> tuple[Position, ...]: ...


class PositionOpenOutcomeRepository(Protocol):
    def append(self, outcome: PositionOpenOutcome) -> PositionOpenOutcome: ...

    def get(self, outcome_id: PositionOpenOutcomeId) -> PositionOpenOutcome | None: ...

    def find_for_run_instrument(
        self, run_id: RunId, instrument_id: InstrumentId
    ) -> tuple[PositionOpenOutcome, ...]: ...


class ExitRepository(Protocol):
    def append(self, exit_fact: Exit) -> Exit: ...

    def get(self, exit_id: ExitId) -> Exit | None: ...

    def find_for_run_instrument(
        self, run_id: RunId, instrument_id: InstrumentId
    ) -> tuple[Exit, ...]: ...


class IndicatorCheckpointRepository(Protocol):
    def upsert(self, run: RunIdentity, state: IndicatorEngineState) -> IndicatorEngineState: ...

    def get(self, run_id: RunId, instrument_id: InstrumentId) -> IndicatorEngineState | None: ...


class StateTransitionRepository(Protocol):
    def append(self, transition: StateTransition) -> StateTransition: ...

    def get(self, transition_id: StateTransitionId) -> StateTransition | None: ...

    def find_for_run(self, run_id: RunId) -> tuple[StateTransition, ...]: ...
