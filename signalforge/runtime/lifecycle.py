"""Thin deterministic coordinator for the in-memory M4 paper lifecycle."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from signalforge.domain.armed import ArmedSetupState
from signalforge.domain.audit import StateTransition, TransitionEntityType
from signalforge.domain.exits import Exit
from signalforge.domain.instruments import TickSizeSchedule
from signalforge.domain.market import CompletedCandle, MarketEvent
from signalforge.domain.money import Quantity
from signalforge.domain.positions import Position, PositionState
from signalforge.domain.provenance import RunIdentity
from signalforge.domain.time import require_aware
from signalforge.domain.trades import Trade, TradeState
from signalforge.runtime.execution import PaperExecutionPort, PaperExecutionResult
from signalforge.runtime.position_manager import PositionManager, PositionOpenResult
from signalforge.runtime.signal_lifecycle import SignalArmingResult, SignalLifecycleManager
from signalforge.runtime.strategy_evaluator import StrategyEvaluatorResult


class LifecycleState(StrEnum):
    IDLE = "idle"
    ARMED = "armed"
    TRIGGERED = "triggered"
    EXPIRED = "expired"
    OPEN = "open"
    CLOSED = "closed"


@dataclass(frozen=True, slots=True)
class LifecycleSnapshot:
    state: LifecycleState
    arming: SignalArmingResult | None
    execution: PaperExecutionResult | None
    open_result: PositionOpenResult | None
    exit: Exit | None


class LifecycleCoordinator:
    """Serially compose M4 components without duplicating their business rules."""

    def __init__(
        self,
        *,
        run: RunIdentity,
        tick_schedule: TickSizeSchedule,
        quantity: Quantity,
    ) -> None:
        self.run = run
        self.quantity = quantity
        self.signal_lifecycle = SignalLifecycleManager(run=run, tick_schedule=tick_schedule)
        self.execution_port = PaperExecutionPort()
        self.position_manager = PositionManager(tick_schedule=tick_schedule)
        self._arming: SignalArmingResult | None = None
        self._execution: PaperExecutionResult | None = None
        self._open_result: PositionOpenResult | None = None
        self._exit: Exit | None = None
        self._audit: dict[str, StateTransition] = {}

    @property
    def audit_transitions(self) -> tuple[StateTransition, ...]:
        return tuple(self._audit.values())

    @property
    def state(self) -> LifecycleState:
        if self._exit is not None:
            return LifecycleState.CLOSED
        if self._open_result is not None and self._open_result.opened:
            trade = self._open_result.trade
            position = self._open_result.position
            if trade is None or position is None:
                raise RuntimeError("Opened lifecycle is missing Trade or Position")
            if trade.state is TradeState.CLOSED or position.state is PositionState.CLOSED:
                raise RuntimeError("Closed Trade/Position requires an Exit fact")
            return LifecycleState.OPEN
        if self._arming is None:
            return LifecycleState.IDLE
        setup_state = self._arming.armed_setup.state
        if setup_state is ArmedSetupState.ARMED:
            return LifecycleState.ARMED
        if setup_state is ArmedSetupState.TRIGGERED:
            return LifecycleState.TRIGGERED
        return LifecycleState.EXPIRED

    def snapshot(self) -> LifecycleSnapshot:
        return LifecycleSnapshot(
            state=self.state,
            arming=self._arming,
            execution=self._execution,
            open_result=self._open_result,
            exit=self._exit,
        )

    def process_evaluation(
        self,
        candle: CompletedCandle,
        evaluator_result: StrategyEvaluatorResult,
    ) -> LifecycleSnapshot:
        """Route one already-computed strategy evaluation into Signal/ARMED creation."""

        before = self.signal_lifecycle.active
        arming = self.signal_lifecycle.arm_if_actionable(
            candle,
            evaluator_result,
            open_position=self.state is LifecycleState.OPEN,
        )
        if arming is not None:
            self._arming = arming
            if before is not arming:
                self._record(
                    entity_type=TransitionEntityType.ARMED_SETUP,
                    entity_id=str(arming.signal.signal_id),
                    from_state="none",
                    to_state=ArmedSetupState.ARMED.value,
                    cause_type="strategy_evaluation",
                    cause_id=self._evaluation_cause_id(evaluator_result),
                    occurred_at=arming.armed_setup.armed_at,
                )
        return self.snapshot()

    def process_market_event(self, event: MarketEvent) -> LifecycleSnapshot:
        """Route one ordered market event through ARMED or OPEN lifecycle handling."""

        if self.state is LifecycleState.OPEN:
            self._process_open_event(event)
            return self.snapshot()

        arming = self._arming
        if arming is None or arming.armed_setup.state is not ArmedSetupState.ARMED:
            return self.snapshot()

        prior_state = arming.armed_setup.state
        trigger = self.signal_lifecycle.process_market_event(event)
        self._record_setup_terminal_if_changed(arming, prior_state, event)
        if trigger is None:
            return self.snapshot()

        self._execution = self.execution_port.execute(trigger, quantity=self.quantity)
        self._open_result = self.position_manager.open_from_fill(
            self._execution.fill,
            arming.signal,
        )
        if self._open_result.opened:
            trade = self._require_trade()
            position = self._require_position()
            self._record(
                entity_type=TransitionEntityType.TRADE,
                entity_id=str(trade.trade_id),
                from_state="none",
                to_state=TradeState.OPEN.value,
                cause_type="fill",
                cause_id=str(self._execution.fill.fill_id),
                occurred_at=trade.opened_at,
            )
            self._record(
                entity_type=TransitionEntityType.POSITION,
                entity_id=str(position.position_id),
                from_state="none",
                to_state=PositionState.OPEN.value,
                cause_type="trade",
                cause_id=str(trade.trade_id),
                occurred_at=position.opened_at,
            )
        return self.snapshot()

    def process_completed_candle(self, candle: CompletedCandle) -> LifecycleSnapshot:
        arming = self._arming
        if arming is None or arming.armed_setup.state is not ArmedSetupState.ARMED:
            return self.snapshot()
        prior_state = arming.armed_setup.state
        self.signal_lifecycle.process_completed_candle(candle)
        self._record_setup_terminal_if_changed(arming, prior_state, candle)
        return self.snapshot()

    def process_time(self, at: datetime) -> LifecycleSnapshot:
        require_aware(at)
        arming = self._arming
        if arming is None or arming.armed_setup.state is not ArmedSetupState.ARMED:
            return self.snapshot()
        prior_state = arming.armed_setup.state
        self.signal_lifecycle.process_time(at)
        self._record_setup_terminal_if_changed(arming, prior_state, at)
        return self.snapshot()

    def _process_open_event(self, event: MarketEvent) -> None:
        trade = self._require_trade()
        position = self._require_position()
        exit_fact = self.position_manager.process_market_event(trade, position, event)
        if exit_fact is None:
            return
        prior_exit = self._exit
        self._exit = exit_fact
        if prior_exit is not None:
            return
        self._record(
            entity_type=TransitionEntityType.TRADE,
            entity_id=str(trade.trade_id),
            from_state=TradeState.OPEN.value,
            to_state=TradeState.CLOSED.value,
            cause_type="exit",
            cause_id=str(exit_fact.exit_id),
            occurred_at=exit_fact.exited_at,
        )
        self._record(
            entity_type=TransitionEntityType.POSITION,
            entity_id=str(position.position_id),
            from_state=PositionState.OPEN.value,
            to_state=PositionState.CLOSED.value,
            cause_type="exit",
            cause_id=str(exit_fact.exit_id),
            occurred_at=exit_fact.exited_at,
        )

    def _record_setup_terminal_if_changed(
        self,
        arming: SignalArmingResult,
        prior_state: ArmedSetupState,
        cause: object,
    ) -> None:
        setup = arming.armed_setup
        if setup.state is prior_state:
            return
        if setup.terminal_at is None:
            raise RuntimeError("Terminal ArmedSetup requires terminal_at")
        if setup.state is ArmedSetupState.TRIGGERED:
            trigger = self.signal_lifecycle.trigger_event
            if trigger is None:
                raise RuntimeError("TRIGGERED ArmedSetup requires TriggerEvent")
            cause_type = "trigger_event"
            cause_id = str(trigger.trigger_event_id)
        else:
            cause_type = type(cause).__name__
            cause_id = self._cause_id(cause)
        self._record(
            entity_type=TransitionEntityType.ARMED_SETUP,
            entity_id=str(arming.signal.signal_id),
            from_state=prior_state.value,
            to_state=setup.state.value,
            cause_type=cause_type,
            cause_id=cause_id,
            occurred_at=setup.terminal_at,
        )

    def _record(
        self,
        *,
        entity_type: TransitionEntityType,
        entity_id: str,
        from_state: str,
        to_state: str,
        cause_type: str,
        cause_id: str,
        occurred_at: datetime,
    ) -> None:
        fact = StateTransition.create(
            entity_type=entity_type,
            entity_id=entity_id,
            from_state=from_state,
            to_state=to_state,
            cause_type=cause_type,
            cause_id=cause_id,
            occurred_at=occurred_at,
            run=self.run,
        )
        self._audit.setdefault(str(fact.transition_id), fact)

    def _require_trade(self) -> Trade:
        if self._open_result is None or self._open_result.trade is None:
            raise RuntimeError("Lifecycle has no Trade")
        return self._open_result.trade

    def _require_position(self) -> Position:
        if self._open_result is None or self._open_result.position is None:
            raise RuntimeError("Lifecycle has no Position")
        return self._open_result.position

    @staticmethod
    def _evaluation_cause_id(result: StrategyEvaluatorResult) -> str:
        evaluation = result.evaluation
        return f"{evaluation.instrument_id}:{evaluation.interval.start.isoformat()}"

    @staticmethod
    def _cause_id(cause: object) -> str:
        if isinstance(cause, CompletedCandle):
            return f"{cause.instrument_id}:{cause.interval.start.isoformat()}"
        if isinstance(cause, MarketEvent):
            return cause.source_event_id or (
                f"{cause.instrument_id}:{cause.exchange_timestamp.isoformat()}:{cause.price.value}"
            )
        if isinstance(cause, datetime):
            return cause.isoformat()
        return type(cause).__name__
