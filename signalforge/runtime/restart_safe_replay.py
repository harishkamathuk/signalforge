"""Restart-safe deterministic replay composition with per-input durability."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy.orm import Session

from signalforge.domain.armed import ArmedSetup
from signalforge.domain.audit import StateTransition, TransitionEntityType
from signalforge.domain.decision_facts import StrategyDecisionFact
from signalforge.domain.execution import EntryIntent, Fill, TriggerEvent
from signalforge.domain.exits import Exit
from signalforge.domain.position_outcomes import PositionOpenOutcome, PositionOpenOutcomeType
from signalforge.domain.positions import Position
from signalforge.domain.signals import Signal
from signalforge.domain.trades import Trade
from signalforge.persistence.coordinator import MarketInputCommit, PersistenceCoordinator
from signalforge.runtime.lifecycle import LifecycleSnapshot
from signalforge.runtime.market_input import (
    CanonicalMarketInput,
    MarketInputCheckpoint,
    MarketInputDisposition,
    MarketInputGuard,
)
from signalforge.runtime.replay import ReplayInput
from signalforge.runtime.replay_runtime import ReplayRuntime, ReplayRuntimeStep
from signalforge.runtime.strategy import CompletedCandleStrategyContext, StrategyDecision

DecisionProjector = Callable[[StrategyDecision], StrategyDecisionFact]
SessionFactory = Callable[[], Session]


class RestartSafeReplayError(RuntimeError):
    """Raised when a restart-safe replay runtime can no longer continue safely."""


@dataclass(frozen=True, slots=True)
class RestartSafeReplayStep:
    """Observable result for one canonical input, including duplicate suppression."""

    duplicate: bool
    replay_step: ReplayRuntimeStep | None
    checkpoint: MarketInputCheckpoint


class RestartSafeReplayRuntime:
    """Process one canonical input atomically with all synchronous durable effects."""

    def __init__(
        self,
        *,
        runtime: ReplayRuntime,
        session_factory: SessionFactory,
        decision_projector: DecisionProjector,
        checkpoint: MarketInputCheckpoint | None = None,
    ) -> None:
        self.runtime = runtime
        self._session_factory = session_factory
        self._decision_projector = decision_projector
        self._terminal = False
        if checkpoint is not None:
            if checkpoint.run != runtime.run:
                raise ValueError("Market-input checkpoint run must match replay runtime")
            if checkpoint.instrument_id != runtime.instrument_id:
                raise ValueError("Market-input checkpoint instrument must match replay runtime")
            if checkpoint.candle_state != runtime.candle_engine.state:
                raise ValueError(
                    "Replay CandleEngine must be restored from the persisted checkpoint"
                )
        self._guard = MarketInputGuard(
            source_id=runtime.source.identity.source_id,
            checkpoint=checkpoint,
        )

    @property
    def terminal(self) -> bool:
        return self._terminal

    @property
    def checkpoint(self) -> MarketInputCheckpoint | None:
        return self._guard.checkpoint

    def process_input(self, replay_input: ReplayInput) -> RestartSafeReplayStep:
        """Process one input exactly once from the durable runtime's point of view."""

        if self._terminal:
            raise RestartSafeReplayError(
                "restart-safe replay runtime is terminal after persistence failure"
            )
        canonical = CanonicalMarketInput.from_replay_input(replay_input)
        disposition = self._guard.classify(canonical)
        existing = self._guard.checkpoint
        if disposition is MarketInputDisposition.DUPLICATE:
            assert existing is not None
            return RestartSafeReplayStep(True, None, existing)

        before_transition_ids = {
            str(item.transition_id) for item in self.runtime.lifecycle.audit_transitions
        }
        event = replay_input.event

        market_snapshot = self.runtime.lifecycle.process_market_event(event)
        trigger_after_market = self.runtime.lifecycle.signal_lifecycle.trigger_event
        completed = self.runtime.candle_engine.process(event)

        completed_snapshot = market_snapshot
        indicator_snapshot = None
        evaluation = None
        final_snapshot = market_snapshot
        if completed is not None:
            completed_snapshot = self.runtime.lifecycle.process_completed_candle(completed)
            indicator_snapshot = self.runtime.indicator_engine.update(completed)
            facts = self.runtime._evaluation_context_factory(completed)
            evaluation = self.runtime.strategy.evaluate_completed_candle(
                CompletedCandleStrategyContext(
                    candle=completed,
                    indicators=indicator_snapshot,
                    completed_regular_session_candles=facts.completed_regular_session_candles,
                    continuity=facts.continuity,
                    feed_state=facts.feed_state,
                )
            )
            final_snapshot = self.runtime.lifecycle.process_evaluation(completed, evaluation)

        replay_step = ReplayRuntimeStep(
            replay_input=replay_input,
            completed_candle=completed,
            indicator_snapshot=indicator_snapshot,
            evaluation=evaluation,
            lifecycle=final_snapshot,
        )
        checkpoint = MarketInputCheckpoint(
            run=self.runtime.run,
            instrument_id=self.runtime.instrument_id,
            last_input=canonical,
            candle_state=self.runtime.candle_engine.state,
            updated_at=event.received_timestamp,
        )
        transitions = tuple(
            item
            for item in self.runtime.lifecycle.audit_transitions
            if str(item.transition_id) not in before_transition_ids
        )
        commit = self._build_commit(
            checkpoint=checkpoint,
            transitions=transitions,
            market_snapshot=market_snapshot,
            completed_snapshot=completed_snapshot,
            final_snapshot=final_snapshot,
            trigger_after_market=trigger_after_market,
            evaluation=evaluation,
            completed=completed is not None,
        )
        try:
            with self._session_factory() as session:
                persisted = PersistenceCoordinator(session).persist_market_input(
                    run=self.runtime.run,
                    commit=commit,
                )
        except Exception:
            self._terminal = True
            raise

        self._guard.accept(persisted)
        return RestartSafeReplayStep(False, replay_step, persisted)

    def _build_commit(
        self,
        *,
        checkpoint: MarketInputCheckpoint,
        transitions: tuple[StateTransition, ...],
        market_snapshot: LifecycleSnapshot,
        completed_snapshot: LifecycleSnapshot,
        final_snapshot: LifecycleSnapshot,
        trigger_after_market: TriggerEvent | None,
        evaluation: StrategyDecision | None,
        completed: bool,
    ) -> MarketInputCommit:
        snapshots = (market_snapshot, completed_snapshot, final_snapshot)
        setup_signal_ids = {
            item.entity_id
            for item in transitions
            if item.entity_type is TransitionEntityType.ARMED_SETUP
        }

        signals: dict[str, Signal] = {}
        setups: dict[str, ArmedSetup] = {}
        intents: dict[str, EntryIntent] = {}
        fills: dict[str, Fill] = {}
        trades: dict[str, Trade] = {}
        positions: dict[str, Position] = {}
        exits: dict[str, Exit] = {}

        for snapshot in snapshots:
            arming = snapshot.arming
            if arming is not None and str(arming.signal.signal_id) in setup_signal_ids:
                signals[str(arming.signal.signal_id)] = arming.signal
                setups[str(arming.armed_setup.signal_id)] = arming.armed_setup

            execution = snapshot.execution
            if execution is not None:
                intents[str(execution.entry_intent.entry_intent_id)] = execution.entry_intent
                fills[str(execution.fill.fill_id)] = execution.fill

            open_result = snapshot.open_result
            if open_result is not None and open_result.opened:
                assert open_result.trade is not None
                assert open_result.position is not None
                trades[str(open_result.trade.trade_id)] = open_result.trade
                positions[str(open_result.position.position_id)] = open_result.position

            if snapshot.exit is not None:
                exits[str(snapshot.exit.exit_id)] = snapshot.exit

        triggered = any(
            item.entity_type is TransitionEntityType.ARMED_SETUP
            and item.to_state == "triggered"
            for item in transitions
        )
        triggers = (
            ()
            if not triggered or trigger_after_market is None
            else (trigger_after_market,)
        )

        outcomes: tuple[PositionOpenOutcome, ...] = ()
        if triggered and fills:
            fill = next(iter(fills.values()))
            opened = bool(trades and positions)
            outcomes = (
                PositionOpenOutcome.create(
                    fill_id=fill.fill_id,
                    signal_id=fill.signal_id,
                    outcome=(
                        PositionOpenOutcomeType.OPENED
                        if opened
                        else PositionOpenOutcomeType.REJECTED_NON_POSITIVE_RISK
                    ),
                    decided_at=fill.filled_at,
                    run=fill.run,
                ),
            )

        evaluations = (
            ()
            if evaluation is None
            else (self._decision_projector(evaluation),)
        )
        indicator_state = self.runtime.indicator_engine.state if completed else None

        return MarketInputCommit(
            checkpoint=checkpoint,
            indicator_state=indicator_state,
            evaluations=evaluations,
            signals=tuple(signals.values()),
            setups=tuple(setups.values()),
            triggers=triggers,
            intents=tuple(intents.values()) if triggered else (),
            fills=tuple(fills.values()) if triggered else (),
            outcomes=outcomes,
            trades=tuple(trades.values()),
            positions=tuple(positions.values()),
            exits=tuple(exits.values()),
            transitions=transitions,
        )
