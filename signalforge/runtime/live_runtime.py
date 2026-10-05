"""Durable single-security PAPER runtime for non-replayable live market data."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from sqlalchemy.orm import Session

from signalforge.domain.armed import ArmedSetup
from signalforge.domain.audit import StateTransition, TransitionEntityType
from signalforge.domain.decision_facts import StrategyDecisionFact
from signalforge.domain.execution import EntryIntent, Fill, TriggerEvent
from signalforge.domain.exits import Exit
from signalforge.domain.ids import InstrumentId
from signalforge.domain.indicators import IndicatorSnapshot
from signalforge.domain.instruments import TickSizeSchedule
from signalforge.domain.market import CompletedCandle, MarketEvent
from signalforge.domain.money import Quantity
from signalforge.domain.position_outcomes import (
    PositionOpenOutcome,
    PositionOpenOutcomeType,
)
from signalforge.domain.positions import Position
from signalforge.domain.provenance import RunIdentity
from signalforge.domain.signals import Signal
from signalforge.domain.trades import Trade
from signalforge.persistence.coordinator import (
    LiveMarketInputCommit,
    PersistenceCoordinator,
)
from signalforge.persistence.repositories import PostgresRunProvenanceRepository
from signalforge.runtime.candles import CandleEngine
from signalforge.runtime.eligibility import MarketDataFeedState
from signalforge.runtime.indicator_recovery import IndicatorRecoveryReconciler
from signalforge.runtime.indicators import IndicatorEngine
from signalforge.runtime.lifecycle import (
    LifecycleCoordinator,
    LifecycleSnapshot,
    LifecycleState,
)
from signalforge.runtime.lifecycle_recovery import LifecycleRecoveryHydrator
from signalforge.runtime.recovery import RecoveryBootstrap, RecoveryDisposition
from signalforge.runtime.strategy import (
    CompletedCandleStrategyContext,
    Strategy,
    StrategyDecision,
    StrategyRuntimeFacts,
)

DecisionProjector = Callable[[StrategyDecision], StrategyDecisionFact]
EvaluationContextFactory = Callable[[CompletedCandle], StrategyRuntimeFacts]
SessionFactory = Callable[[], Session]


class LiveFeed(Protocol):
    """Broker-neutral live-feed surface consumed by the runtime."""

    @property
    def state(self) -> MarketDataFeedState: ...

    def start(self) -> None: ...

    def receive_once(self) -> MarketEvent | None: ...

    def close(self) -> None: ...


class LiveRuntimeContinuity(StrEnum):
    """Runtime chronology state, intentionally separate from transport health."""

    CONTINUOUS = "continuous"
    RECONCILIATION_REQUIRED = "reconciliation_required"
    TERMINAL = "terminal"


class LiveRuntimeError(RuntimeError):
    """Raised when a live runtime cannot safely continue."""


class LiveRuntimeReconciliationRequired(LiveRuntimeError):
    """Raised after market chronology becomes unprovable."""


@dataclass(frozen=True, slots=True)
class LiveRuntimeStep:
    """Observable result from one accepted live market event or no-event poll."""

    market_event: MarketEvent | None
    completed_candle: CompletedCandle | None
    indicator_snapshot: IndicatorSnapshot | None
    evaluation: StrategyDecision | None
    lifecycle: LifecycleSnapshot
    feed_state: MarketDataFeedState
    continuity: LiveRuntimeContinuity


class LiveRuntime:
    """Compose recovery, live feed, shared runtime engines and durable PAPER facts."""

    _GAP_STATES = frozenset(
        {
            MarketDataFeedState.STALE,
            MarketDataFeedState.DISCONNECTED,
            MarketDataFeedState.RECOVERING,
            MarketDataFeedState.FAILED,
        }
    )

    def __init__(
        self,
        *,
        feed: LiveFeed,
        run: RunIdentity,
        instrument_id: InstrumentId,
        candle_engine: CandleEngine,
        indicator_engine: IndicatorEngine,
        lifecycle: LifecycleCoordinator,
        strategy: Strategy,
        session_factory: SessionFactory,
        decision_projector: DecisionProjector,
        evaluation_context_factory: EvaluationContextFactory,
        continuity: LiveRuntimeContinuity,
    ) -> None:
        if candle_engine.instrument_id != instrument_id:
            raise ValueError("CandleEngine instrument must match live runtime")
        indicator_state = indicator_engine.state
        if (
            indicator_state.instrument_id != instrument_id
            or indicator_state.calculation_version != run.engine_calculation_version
            or indicator_state.requirements != strategy.indicator_requirements
        ):
            raise ValueError("IndicatorEngine contradicts live runtime identity")
        if lifecycle.run != run or lifecycle.strategy.identity != strategy.identity:
            raise ValueError("LifecycleCoordinator contradicts live runtime")
        if run.strategy != strategy.identity:
            raise ValueError("Run strategy identity must match configured strategy")
        if (
            run.config_id != strategy.config_identity.config_id
            or run.config_hash != strategy.config_identity.config_hash
        ):
            raise ValueError("Run config identity must match configured strategy")

        self.feed = feed
        self.run = run
        self.instrument_id = instrument_id
        self.candle_engine = candle_engine
        self.indicator_engine = indicator_engine
        self.lifecycle = lifecycle
        self.strategy = strategy
        self._session_factory = session_factory
        self._decision_projector = decision_projector
        self._evaluation_context_factory = evaluation_context_factory
        self._continuity = continuity

    @property
    def continuity(self) -> LiveRuntimeContinuity:
        return self._continuity

    @property
    def terminal(self) -> bool:
        return self._continuity is LiveRuntimeContinuity.TERMINAL

    @classmethod
    def bootstrap(
        cls,
        *,
        feed: LiveFeed,
        run: RunIdentity,
        instrument_id: InstrumentId,
        tick_schedule: TickSizeSchedule,
        quantity: Quantity,
        strategy: Strategy,
        session_factory: SessionFactory,
        decision_projector: DecisionProjector,
        evaluation_context_factory: EvaluationContextFactory,
    ) -> LiveRuntime:
        """Recover durable state before the live adapter is allowed to start."""

        if tick_schedule.instrument_id != instrument_id:
            raise ValueError("Tick schedule instrument must match live runtime")

        with session_factory() as session:
            recovered = RecoveryBootstrap().inspect(
                session=session,
                requested_run=run,
                instrument_id=instrument_id,
                indicator_requirements=strategy.indicator_requirements,
            )

        if recovered.market_input_checkpoint is not None:
            raise LiveRuntimeError(
                "Live runtime cannot resume a run containing replay market-input checkpoints"
            )

        base_indicator = recovered.indicator_state
        if base_indicator is None:
            base_indicator = IndicatorEngine(
                instrument_id,
                run.engine_calculation_version,
                requirements=strategy.indicator_requirements,
            ).state
        indicator_result = IndicatorRecoveryReconciler(base_indicator).reconcile(())

        lifecycle = LifecycleCoordinator(
            run=run,
            tick_schedule=tick_schedule,
            quantity=quantity,
            strategy=strategy,
        )
        LifecycleRecoveryHydrator().hydrate(
            indicator_result=indicator_result,
            recovered=recovered.lifecycle,
            coordinator=lifecycle,
        )

        continuity = (
            LiveRuntimeContinuity.CONTINUOUS
            if recovered.disposition is RecoveryDisposition.NEW
            else LiveRuntimeContinuity.RECONCILIATION_REQUIRED
        )
        runtime = cls(
            feed=feed,
            run=run,
            instrument_id=instrument_id,
            candle_engine=CandleEngine(instrument_id=instrument_id),
            indicator_engine=indicator_result.engine,
            lifecycle=lifecycle,
            strategy=strategy,
            session_factory=session_factory,
            decision_projector=decision_projector,
            evaluation_context_factory=evaluation_context_factory,
            continuity=continuity,
        )

        if recovered.disposition is RecoveryDisposition.NEW:
            try:
                with session_factory() as session:
                    with session.begin():
                        PostgresRunProvenanceRepository(session).add(run)
                # Recovery, hydration and run provenance are durable before
                # external live input can arrive.
                feed.start()
            except Exception:
                runtime._continuity = LiveRuntimeContinuity.TERMINAL
                feed.close()
                raise
        return runtime

    def mark_gap(self) -> None:
        """Preserve durable lifecycle state while blocking same-run progression."""

        if self._continuity is not LiveRuntimeContinuity.TERMINAL:
            self._continuity = LiveRuntimeContinuity.RECONCILIATION_REQUIRED

    def poll_once(self) -> LiveRuntimeStep:
        """Poll the feed once and process only chronology that remains trustworthy."""

        self._require_processable()
        if self.feed.state in self._GAP_STATES:
            self.mark_gap()
            raise LiveRuntimeReconciliationRequired(
                "Live feed continuity was already lost before the next receive"
            )
        try:
            event = self.feed.receive_once()
        except Exception:
            if self.feed.state in self._GAP_STATES:
                self.mark_gap()
            else:
                self._continuity = LiveRuntimeContinuity.TERMINAL
            raise

        feed_state = self.feed.state
        if event is None:
            if feed_state in self._GAP_STATES:
                self.mark_gap()
            return LiveRuntimeStep(
                market_event=None,
                completed_candle=None,
                indicator_snapshot=None,
                evaluation=None,
                lifecycle=self.lifecycle.snapshot(),
                feed_state=feed_state,
                continuity=self._continuity,
            )

        if feed_state is not MarketDataFeedState.HEALTHY:
            self.mark_gap()
            raise LiveRuntimeReconciliationRequired(
                "Live feed produced an event without HEALTHY transport state"
            )
        return self.process_event(event, feed_state=feed_state)

    def process_event(
        self,
        event: MarketEvent,
        *,
        feed_state: MarketDataFeedState,
    ) -> LiveRuntimeStep:
        """Process one already-normalized live event and atomically persist its effects."""

        self._require_processable()
        if feed_state in self._GAP_STATES:
            self.mark_gap()
            raise LiveRuntimeReconciliationRequired(
                "Non-continuous feed state cannot advance live runtime chronology"
            )
        if (
            feed_state is not MarketDataFeedState.HEALTHY
            and self.lifecycle.state in {LifecycleState.ARMED, LifecycleState.OPEN}
        ):
            self._continuity = LiveRuntimeContinuity.TERMINAL
            raise LiveRuntimeError(
                "Price-sensitive lifecycle cannot advance on a non-HEALTHY live feed"
            )
        if event.instrument_id != self.instrument_id:
            self._continuity = LiveRuntimeContinuity.TERMINAL
            raise LiveRuntimeError("Live MarketEvent instrument does not match runtime")
        if event.source_event_id is not None:
            self._continuity = LiveRuntimeContinuity.TERMINAL
            raise LiveRuntimeError(
                "Live OpenAlgo events must not acquire synthetic provider event identity"
            )

        before_transition_ids = {
            str(item.transition_id) for item in self.lifecycle.audit_transitions
        }
        try:
            market_snapshot = self.lifecycle.process_market_event(event)
            trigger_after_market = self.lifecycle.signal_lifecycle.trigger_event
            completed = self.candle_engine.process(event)

            completed_snapshot = market_snapshot
            indicator_snapshot = None
            evaluation = None
            final_snapshot = market_snapshot
            if completed is not None:
                completed_snapshot = self.lifecycle.process_completed_candle(completed)
                indicator_snapshot = self.indicator_engine.update(completed)
                facts = self._evaluation_context_factory(completed)
                if facts.continuity != self.indicator_engine.continuity:
                    raise LiveRuntimeError(
                        "Evaluation context continuity contradicts IndicatorEngine"
                    )
                evaluation = self.strategy.evaluate_completed_candle(
                    CompletedCandleStrategyContext(
                        candle=completed,
                        indicators=indicator_snapshot,
                        completed_regular_session_candles=(
                            facts.completed_regular_session_candles
                        ),
                        continuity=self.indicator_engine.continuity,
                        feed_state=feed_state,
                    )
                )
                if (
                    feed_state is not MarketDataFeedState.HEALTHY
                    and evaluation.actionable
                ):
                    raise LiveRuntimeError(
                        "Non-HEALTHY live feed cannot produce an actionable decision"
                    )
                final_snapshot = self.lifecycle.process_evaluation(completed, evaluation)

            transitions = tuple(
                item
                for item in self.lifecycle.audit_transitions
                if str(item.transition_id) not in before_transition_ids
            )
            commit = self._build_commit(
                transitions=transitions,
                market_snapshot=market_snapshot,
                completed_snapshot=completed_snapshot,
                final_snapshot=final_snapshot,
                trigger_after_market=trigger_after_market,
                evaluation=evaluation,
                completed=completed is not None,
            )
            with self._session_factory() as session:
                PersistenceCoordinator(session).persist_live_market_input(
                    run=self.run,
                    commit=commit,
                )
        except Exception:
            # Processing may already have advanced in-memory candle/lifecycle/indicator
            # state. It is never safe to continue that instance ahead of PostgreSQL.
            self._continuity = LiveRuntimeContinuity.TERMINAL
            raise

        return LiveRuntimeStep(
            market_event=event,
            completed_candle=completed,
            indicator_snapshot=indicator_snapshot,
            evaluation=evaluation,
            lifecycle=final_snapshot,
            feed_state=feed_state,
            continuity=self._continuity,
        )

    def process_time(self, at: datetime) -> LifecycleSnapshot:
        """Advance ARMED time policy and atomically persist any resulting transition."""

        self._require_processable()
        before_transition_ids = {
            str(item.transition_id) for item in self.lifecycle.audit_transitions
        }
        try:
            snapshot = self.lifecycle.process_time(at)
            transitions = tuple(
                item
                for item in self.lifecycle.audit_transitions
                if str(item.transition_id) not in before_transition_ids
            )
            if transitions:
                setup = (
                    ()
                    if snapshot.arming is None
                    else (snapshot.arming.armed_setup,)
                )
                with self._session_factory() as session:
                    PersistenceCoordinator(session).persist_live_market_input(
                        run=self.run,
                        commit=LiveMarketInputCommit(
                            setups=setup,
                            transitions=transitions,
                        ),
                    )
        except Exception:
            self._continuity = LiveRuntimeContinuity.TERMINAL
            raise
        return snapshot

    def process_time(self, at: datetime) -> LifecycleSnapshot:
        """Advance authoritative ARMED time policy and persist any transition."""

        self._require_processable()
        before_ids = {str(item.transition_id) for item in self.lifecycle.audit_transitions}
        before = self.lifecycle.snapshot()
        try:
            after = self.lifecycle.process_time(at)
            transitions = tuple(
                item
                for item in self.lifecycle.audit_transitions
                if str(item.transition_id) not in before_ids
            )
            if not transitions:
                return after
            setups: tuple[ArmedSetup, ...] = ()
            if after.arming is not None and after.arming is not before.arming:
                setups = (after.arming.armed_setup,)
            elif after.arming is not None and before.arming is not None:
                if after.arming.armed_setup.state != before.arming.armed_setup.state:
                    setups = (after.arming.armed_setup,)
            with self._session_factory() as session:
                PersistenceCoordinator(session).persist_live_market_input(
                    run=self.run,
                    commit=LiveMarketInputCommit(
                        setups=setups,
                        transitions=transitions,
                    ),
                )
            return after
        except Exception:
            self._continuity = LiveRuntimeContinuity.TERMINAL
            raise

    def _require_processable(self) -> None:
        if self._continuity is LiveRuntimeContinuity.RECONCILIATION_REQUIRED:
            raise LiveRuntimeReconciliationRequired(
                "Live market chronology is unprovable; reconciliation is required"
            )
        if self._continuity is LiveRuntimeContinuity.TERMINAL:
            raise LiveRuntimeError("Live runtime is terminal and requires fresh recovery")

    def _build_commit(
        self,
        *,
        transitions: tuple[StateTransition, ...],
        market_snapshot: LifecycleSnapshot,
        completed_snapshot: LifecycleSnapshot,
        final_snapshot: LifecycleSnapshot,
        trigger_after_market: TriggerEvent | None,
        evaluation: StrategyDecision | None,
        completed: bool,
    ) -> LiveMarketInputCommit:
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
        return LiveMarketInputCommit(
            indicator_state=self.indicator_engine.state if completed else None,
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
