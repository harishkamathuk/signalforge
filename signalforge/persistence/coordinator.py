"""Narrow atomic persistence boundaries for accepted lifecycle outcomes."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from signalforge.domain.armed import ArmedSetup
from signalforge.domain.audit import StateTransition
from signalforge.domain.decision_facts import StrategyDecisionFact
from signalforge.domain.execution import EntryIntent, Fill, TriggerEvent
from signalforge.domain.exits import Exit
from signalforge.domain.ids import RunId
from signalforge.domain.position_outcomes import PositionOpenOutcome, PositionOpenOutcomeType
from signalforge.domain.positions import Position
from signalforge.domain.provenance import RunIdentity
from signalforge.domain.signals import Signal
from signalforge.domain.trades import Trade
from signalforge.persistence.repositories import (
    PostgresArmedSetupRepository,
    PostgresEntryIntentRepository,
    PostgresExitRepository,
    PostgresFillRepository,
    PostgresIndicatorCheckpointRepository,
    PostgresMarketInputCheckpointRepository,
    PostgresPositionOpenOutcomeRepository,
    PostgresPositionRepository,
    PostgresSignalRepository,
    PostgresStateTransitionRepository,
    PostgresStrategyDecisionRepository,
    PostgresTradeRepository,
    PostgresTriggerEventRepository,
)
from signalforge.runtime.indicators import IndicatorEngineState
from signalforge.runtime.market_input import MarketInputCheckpoint


@dataclass(frozen=True, slots=True)
class LiveMarketInputCommit:
    """Durable consequences of one accepted live event without replay identity."""

    indicator_state: IndicatorEngineState | None = None
    evaluations: tuple[StrategyDecisionFact, ...] = ()
    signals: tuple[Signal, ...] = ()
    setups: tuple[ArmedSetup, ...] = ()
    triggers: tuple[TriggerEvent, ...] = ()
    intents: tuple[EntryIntent, ...] = ()
    fills: tuple[Fill, ...] = ()
    outcomes: tuple[PositionOpenOutcome, ...] = ()
    trades: tuple[Trade, ...] = ()
    positions: tuple[Position, ...] = ()
    exits: tuple[Exit, ...] = ()
    transitions: tuple[StateTransition, ...] = ()


@dataclass(frozen=True, slots=True)
class MarketInputCommit:
    """Already-decided durable consequences of one canonical market input."""

    checkpoint: MarketInputCheckpoint
    indicator_state: IndicatorEngineState | None = None
    evaluations: tuple[StrategyDecisionFact, ...] = ()
    signals: tuple[Signal, ...] = ()
    setups: tuple[ArmedSetup, ...] = ()
    triggers: tuple[TriggerEvent, ...] = ()
    intents: tuple[EntryIntent, ...] = ()
    fills: tuple[Fill, ...] = ()
    outcomes: tuple[PositionOpenOutcome, ...] = ()
    trades: tuple[Trade, ...] = ()
    positions: tuple[Position, ...] = ()
    exits: tuple[Exit, ...] = ()
    transitions: tuple[StateTransition, ...] = ()


class PersistenceCoordinator:
    """Commit one accepted lifecycle boundary with one caller-provided Session."""

    def persist_live_market_input(
        self,
        *,
        run: RunIdentity,
        commit: LiveMarketInputCommit,
    ) -> None:
        """Atomically persist synchronous consequences of one live market event.

        Live OpenAlgo input has no replayable provider sequence/event identity, so
        this boundary intentionally persists no MarketInputCheckpoint.
        """

        self._validate_live_commit(run=run, commit=commit)
        with self._session.begin():
            if commit.indicator_state is not None:
                PostgresIndicatorCheckpointRepository(self._session).upsert(
                    run, commit.indicator_state
                )
            for evaluation in commit.evaluations:
                PostgresStrategyDecisionRepository(self._session).append(
                    run.run_id, evaluation
                )
            for signal in commit.signals:
                PostgresSignalRepository(self._session).append(signal)
            for trigger in commit.triggers:
                PostgresTriggerEventRepository(self._session).append(trigger)
            for intent in commit.intents:
                PostgresEntryIntentRepository(self._session).append(intent)
            for fill in commit.fills:
                PostgresFillRepository(self._session).append(fill)
            for outcome in commit.outcomes:
                PostgresPositionOpenOutcomeRepository(self._session).append(outcome)
            for exit_fact in commit.exits:
                PostgresExitRepository(self._session).append(exit_fact)
            for trade in commit.trades:
                PostgresTradeRepository(self._session).upsert(trade)
            for position in commit.positions:
                PostgresPositionRepository(self._session).upsert(position)
            for setup in commit.setups:
                PostgresArmedSetupRepository(self._session).upsert(run.run_id, setup)
            for transition in commit.transitions:
                PostgresStateTransitionRepository(self._session).append(transition)

    @staticmethod
    def _validate_live_commit(
        *,
        run: RunIdentity,
        commit: LiveMarketInputCommit,
    ) -> None:
        if (
            commit.indicator_state is not None
            and commit.indicator_state.calculation_version
            != run.engine_calculation_version
        ):
            raise ValueError("Live indicator checkpoint calculation version must match run")
        if any(item.strategy != run.strategy for item in commit.evaluations):
            raise ValueError("Live strategy decision identity must match run")
        if (
            any(item.run != run for item in commit.signals)
            or any(item.run != run for item in commit.triggers)
            or any(item.run != run for item in commit.intents)
            or any(item.run != run for item in commit.fills)
            or any(item.run != run for item in commit.outcomes)
            or any(item.run != run for item in commit.trades)
            or any(item.run != run for item in commit.positions)
            or any(item.run != run for item in commit.exits)
            or any(item.run != run for item in commit.transitions)
        ):
            raise ValueError("Live durable fact run identity must match requested run")

    def persist_market_input(
        self,
        *,
        run: RunIdentity,
        commit: MarketInputCommit,
    ) -> MarketInputCheckpoint:
        """Atomically persist all synchronous durable consequences of one input."""

        if commit.checkpoint.run != run:
            raise ValueError("MarketInputCommit checkpoint run must match requested run")
        with self._session.begin():
            if commit.indicator_state is not None:
                PostgresIndicatorCheckpointRepository(self._session).upsert(
                    run, commit.indicator_state
                )
            for evaluation in commit.evaluations:
                PostgresStrategyDecisionRepository(self._session).append(
                    run.run_id, evaluation
                )
            for signal in commit.signals:
                PostgresSignalRepository(self._session).append(signal)
            for trigger in commit.triggers:
                PostgresTriggerEventRepository(self._session).append(trigger)
            for intent in commit.intents:
                PostgresEntryIntentRepository(self._session).append(intent)
            for fill in commit.fills:
                PostgresFillRepository(self._session).append(fill)
            for outcome in commit.outcomes:
                PostgresPositionOpenOutcomeRepository(self._session).append(outcome)
            for exit_fact in commit.exits:
                PostgresExitRepository(self._session).append(exit_fact)
            for trade in commit.trades:
                PostgresTradeRepository(self._session).upsert(trade)
            for position in commit.positions:
                PostgresPositionRepository(self._session).upsert(position)
            for setup in commit.setups:
                PostgresArmedSetupRepository(self._session).upsert(run.run_id, setup)
            for transition in commit.transitions:
                PostgresStateTransitionRepository(self._session).append(transition)
            checkpoint = PostgresMarketInputCheckpointRepository(self._session).upsert(
                run, commit.checkpoint
            )
        return checkpoint

    def persist_completed_evaluation(
        self, *, run: RunIdentity, state: IndicatorEngineState, evaluation: StrategyDecisionFact
    ) -> tuple[IndicatorEngineState, StrategyDecisionFact]:
        """Atomically persist one generic decision fact and indicator checkpoint."""

        with self._session.begin():
            checkpoint = PostgresIndicatorCheckpointRepository(self._session).upsert(run, state)
            evaluation = PostgresStrategyDecisionRepository(self._session).append(
                run.run_id, evaluation
            )
        return checkpoint, evaluation

    def __init__(self, session: Session) -> None:
        self._session = session

    def persist_actionable_evaluation(
        self,
        *,
        evaluation: StrategyDecisionFact,
        signal: Signal,
        setup: ArmedSetup,
        setup_transition: StateTransition,
        checkpoint: IndicatorEngineState | None = None,
    ) -> tuple[StrategyDecisionFact, Signal, ArmedSetup, StateTransition]:
        with self._session.begin():
            if checkpoint is not None:
                PostgresIndicatorCheckpointRepository(self._session).upsert(signal.run, checkpoint)
            evaluation = PostgresStrategyDecisionRepository(self._session).append(
                signal.run.run_id, evaluation
            )
            signal = PostgresSignalRepository(self._session).append(signal)
            setup = PostgresArmedSetupRepository(self._session).upsert(signal.run.run_id, setup)
            transition = PostgresStateTransitionRepository(self._session).append(setup_transition)
        return evaluation, signal, setup, transition

    def persist_trigger_intent(
        self,
        *,
        trigger: TriggerEvent,
        intent: EntryIntent,
        setup: ArmedSetup,
        setup_transition: StateTransition,
    ) -> tuple[TriggerEvent, EntryIntent, ArmedSetup, StateTransition]:
        with self._session.begin():
            trigger = PostgresTriggerEventRepository(self._session).append(trigger)
            intent = PostgresEntryIntentRepository(self._session).append(intent)
            setup = PostgresArmedSetupRepository(self._session).upsert(trigger.run.run_id, setup)
            transition = PostgresStateTransitionRepository(self._session).append(setup_transition)
        return trigger, intent, setup, transition

    def persist_expiry(
        self,
        *,
        setup: ArmedSetup,
        run_id: RunId,
        setup_transition: StateTransition,
    ) -> tuple[ArmedSetup, StateTransition]:
        with self._session.begin():
            setup = PostgresArmedSetupRepository(self._session).upsert(run_id, setup)
            transition = PostgresStateTransitionRepository(self._session).append(setup_transition)
        return setup, transition

    def persist_opened_entry(
        self,
        *,
        fill: Fill,
        outcome: PositionOpenOutcome,
        trade: Trade,
        position: Position,
        trade_transition: StateTransition,
        position_transition: StateTransition,
    ) -> tuple[Fill, PositionOpenOutcome, Trade, Position, StateTransition, StateTransition]:
        if outcome.outcome is not PositionOpenOutcomeType.OPENED:
            raise ValueError("opened entry requires an OPENED PositionOpenOutcome")
        with self._session.begin():
            fill = PostgresFillRepository(self._session).append(fill)
            outcome = PostgresPositionOpenOutcomeRepository(self._session).append(outcome)
            trade = PostgresTradeRepository(self._session).upsert(trade)
            position = PostgresPositionRepository(self._session).upsert(position)
            trade_transition = PostgresStateTransitionRepository(self._session).append(
                trade_transition
            )
            position_transition = PostgresStateTransitionRepository(self._session).append(
                position_transition
            )
        return fill, outcome, trade, position, trade_transition, position_transition

    def persist_rejected_entry(
        self,
        *,
        fill: Fill,
        outcome: PositionOpenOutcome,
    ) -> tuple[Fill, PositionOpenOutcome]:
        if outcome.outcome is not PositionOpenOutcomeType.REJECTED_NON_POSITIVE_RISK:
            raise ValueError("rejected entry requires a rejection PositionOpenOutcome")
        with self._session.begin():
            fill = PostgresFillRepository(self._session).append(fill)
            outcome = PostgresPositionOpenOutcomeRepository(self._session).append(outcome)
        return fill, outcome

    def persist_exit(
        self,
        *,
        exit_fact: Exit,
        trade: Trade,
        position: Position,
        trade_transition: StateTransition,
        position_transition: StateTransition,
    ) -> tuple[Exit, Trade, Position, StateTransition, StateTransition]:
        with self._session.begin():
            exit_fact = PostgresExitRepository(self._session).append(exit_fact)
            trade = PostgresTradeRepository(self._session).upsert(trade)
            position = PostgresPositionRepository(self._session).upsert(position)
            trade_transition = PostgresStateTransitionRepository(self._session).append(
                trade_transition
            )
            position_transition = PostgresStateTransitionRepository(self._session).append(
                position_transition
            )
        return exit_fact, trade, position, trade_transition, position_transition
