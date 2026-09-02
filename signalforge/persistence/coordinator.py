"""Narrow atomic persistence boundaries for accepted lifecycle outcomes."""

from __future__ import annotations

from sqlalchemy.orm import Session

from signalforge.domain.armed import ArmedSetup
from signalforge.domain.audit import StateTransition
from signalforge.domain.execution import EntryIntent, Fill, TriggerEvent
from signalforge.domain.exits import Exit
from signalforge.domain.ids import RunId
from signalforge.domain.position_outcomes import PositionOpenOutcome, PositionOpenOutcomeType
from signalforge.domain.positions import Position
from signalforge.domain.signals import Signal
from signalforge.domain.strategy import StrategyEvaluation
from signalforge.domain.trades import Trade
from signalforge.persistence.repositories import (
    PostgresArmedSetupRepository,
    PostgresEntryIntentRepository,
    PostgresExitRepository,
    PostgresFillRepository,
    PostgresPositionOpenOutcomeRepository,
    PostgresPositionRepository,
    PostgresSignalRepository,
    PostgresStateTransitionRepository,
    PostgresStrategyEvaluationRepository,
    PostgresTradeRepository,
    PostgresTriggerEventRepository,
)


class PersistenceCoordinator:
    """Commit one accepted lifecycle boundary with one caller-provided Session."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def persist_actionable_evaluation(
        self,
        *,
        evaluation: StrategyEvaluation,
        signal: Signal,
        setup: ArmedSetup,
        setup_transition: StateTransition,
    ) -> tuple[StrategyEvaluation, Signal, ArmedSetup, StateTransition]:
        with self._session.begin():
            evaluation = PostgresStrategyEvaluationRepository(self._session).append(
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
        run_id: RunId,
        setup: ArmedSetup,
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
