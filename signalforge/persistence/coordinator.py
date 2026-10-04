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
class MarketInputCommit:
    """Already-decided durable consequences of one canonical market input."""

    checkpoint: MarketInputCheckpoint
    indicator_state: IndicatorEngineState | None = None
    evaluation: StrategyDecisionFact | None = None
    signal: Signal | None = None
    setup: ArmedSetup | None = None
    trigger: TriggerEvent | None = None
    intent: EntryIntent | None = None
    fill: Fill | None = None
    outcome: PositionOpenOutcome | None = None
    trade: Trade | None = None
    position: Position | None = None
    exit_fact: Exit | None = None
    transitions: tuple[StateTransition, ...] = ()

    def __post_init__(self) -> None:
        if self.intent is not None and self.trigger is None:
            raise ValueError("MarketInputCommit EntryIntent requires TriggerEvent")
        if self.fill is not None and self.intent is None:
            raise ValueError("MarketInputCommit Fill requires EntryIntent")
        if self.outcome is not None and self.fill is None:
            raise ValueError("MarketInputCommit outcome requires Fill")
        if self.outcome is not None:
            opened = self.outcome.outcome is PositionOpenOutcomeType.OPENED
            if opened != (self.trade is not None and self.position is not None):
                raise ValueError(
                    "MarketInputCommit OPENED outcome requires Trade and Position"
                )
        if self.exit_fact is not None and (
            self.trade is None or self.position is None
        ):
            raise ValueError("MarketInputCommit Exit requires Trade and Position")


class PersistenceCoordinator:
    """Commit one accepted lifecycle boundary with one caller-provided Session."""

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
            if commit.evaluation is not None:
                PostgresStrategyDecisionRepository(self._session).append(
                    run.run_id, commit.evaluation
                )
            if commit.signal is not None:
                PostgresSignalRepository(self._session).append(commit.signal)
            if commit.trigger is not None:
                PostgresTriggerEventRepository(self._session).append(commit.trigger)
            if commit.intent is not None:
                PostgresEntryIntentRepository(self._session).append(commit.intent)
            if commit.fill is not None:
                PostgresFillRepository(self._session).append(commit.fill)
            if commit.outcome is not None:
                PostgresPositionOpenOutcomeRepository(self._session).append(commit.outcome)
            if commit.exit_fact is not None:
                PostgresExitRepository(self._session).append(commit.exit_fact)
            if commit.trade is not None:
                PostgresTradeRepository(self._session).upsert(commit.trade)
            if commit.position is not None:
                PostgresPositionRepository(self._session).upsert(commit.position)
            if commit.setup is not None:
                PostgresArmedSetupRepository(self._session).upsert(
                    run.run_id, commit.setup
                )
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
