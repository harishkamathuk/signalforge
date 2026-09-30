"""Generic Signal creation and ARMED lifecycle mechanism."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from signalforge.domain.armed import ArmedSetup, ArmedSetupState
from signalforge.domain.execution import TriggerEvent
from signalforge.domain.instruments import TickSizeSchedule
from signalforge.domain.market import CompletedCandle, MarketEvent
from signalforge.domain.money import ceil_to_tick
from signalforge.domain.provenance import RunIdentity
from signalforge.domain.signals import Signal
from signalforge.domain.time import IST, require_aware
from signalforge.runtime.strategy import (
    ArmedEventAction,
    ArmedEventDecision,
    ArmIntent,
    StrategyDecision,
)


@dataclass(frozen=True, slots=True)
class SignalArmingResult:
    """Immutable facts produced by one successful actionable evaluation."""

    signal: Signal
    armed_setup: ArmedSetup

    def __post_init__(self) -> None:
        if self.armed_setup.signal_id != self.signal.signal_id:
            raise ValueError("ArmedSetup must belong to the produced Signal")


class SignalLifecycleManager:
    """Own generic Signal creation and current single-security ARMED state transitions."""

    def __init__(self, *, run: RunIdentity, tick_schedule: TickSizeSchedule) -> None:
        self.run = run
        self.tick_schedule = tick_schedule
        self._active: SignalArmingResult | None = None
        self._trigger_event: TriggerEvent | None = None

    @property
    def active(self) -> SignalArmingResult | None:
        return self._active

    @property
    def trigger_event(self) -> TriggerEvent | None:
        return self._trigger_event

    def arm_if_actionable(
        self,
        candle: CompletedCandle,
        decision: StrategyDecision,
        intent: ArmIntent | None,
        *,
        open_position: bool = False,
    ) -> SignalArmingResult | None:
        """Create Signal + ARMED facts from accepted strategy intent."""

        if candle.instrument_id != decision.instrument_id:
            raise ValueError("Candle and strategy decision instruments must match")
        if candle.interval != decision.interval:
            raise ValueError("Candle and strategy decision intervals must match")
        if self.tick_schedule.instrument_id != candle.instrument_id:
            raise ValueError("TickSizeSchedule instrument must match the signal candle")
        if not isinstance(open_position, bool):
            raise TypeError("open_position must be a boolean")

        if not decision.actionable or open_position:
            return None
        if intent is None:
            raise ValueError("Actionable strategy decision requires ArmIntent")
        if candle.close is None or candle.low is None:
            raise ValueError("Actionable evaluation requires signal candle close and low")
        if intent.valid_until <= candle.interval.end:
            raise ValueError("ArmIntent validity must extend beyond signal candle completion")

        candidate = self._build_result(candle, intent)

        if self._active is not None and self._active.armed_setup.state is ArmedSetupState.ARMED:
            if self._active.signal.signal_id == candidate.signal.signal_id:
                if not self._same_arming_facts(self._active, candidate):
                    raise ValueError(
                        "Logical signal was already armed with different strategy intent"
                    )
                return self._active
            return None

        self._active = candidate
        self._trigger_event = None
        return candidate

    @staticmethod
    def _same_arming_facts(
        first: SignalArmingResult,
        second: SignalArmingResult,
    ) -> bool:
        first_setup = first.armed_setup
        second_setup = second.armed_setup
        return first.signal == second.signal and (
            first_setup.signal_id,
            first_setup.raw_trigger,
            first_setup.tradable_trigger,
            first_setup.signal_low,
            first_setup.armed_at,
            first_setup.valid_until,
        ) == (
            second_setup.signal_id,
            second_setup.raw_trigger,
            second_setup.tradable_trigger,
            second_setup.signal_low,
            second_setup.armed_at,
            second_setup.valid_until,
        )

    def process_market_event(
        self,
        event: MarketEvent,
        policy: ArmedEventDecision,
    ) -> TriggerEvent | None:
        """Apply a strategy decision to one ordered market event."""

        active = self._active
        if active is None:
            return None
        setup = active.armed_setup
        if setup.state is not ArmedSetupState.ARMED:
            return self._trigger_event
        if event.instrument_id != active.signal.instrument_id:
            raise ValueError("MarketEvent instrument must match the active setup")
        if event.exchange_timestamp < setup.armed_at:
            raise ValueError("MarketEvent timestamp must not precede setup arming")

        if policy.action is ArmedEventAction.NO_ACTION:
            return None
        if policy.action is ArmedEventAction.EXPIRE:
            if policy.at is None or policy.expiry_reason is None:
                raise ValueError("EXPIRE decision requires terminal metadata")
            setup.expire(at=policy.at, reason=policy.expiry_reason)
            return None
        if policy.action is not ArmedEventAction.TRIGGER or policy.at is None:
            raise ValueError("Unsupported ARMED market-event decision")
        if policy.at != event.exchange_timestamp:
            raise ValueError("Trigger decision timestamp must match observed market event")
        trigger_event = TriggerEvent.create(
            signal_id=active.signal.signal_id,
            instrument_id=active.signal.instrument_id,
            reference_price=setup.tradable_trigger,
            observed_price=event.price,
            observed_at=event.exchange_timestamp,
            run=self.run,
        )
        setup.trigger(at=policy.at)
        self._trigger_event = trigger_event
        return trigger_event

    def process_completed_candle(
        self,
        candle: CompletedCandle,
        policy: ArmedEventDecision,
    ) -> None:
        """Apply a strategy decision at a completed-candle boundary."""

        active = self._active
        if active is None or active.armed_setup.state is not ArmedSetupState.ARMED:
            return
        if candle.instrument_id != active.signal.instrument_id:
            raise ValueError("CompletedCandle instrument must match the active setup")
        self._apply_non_market_policy(policy)

    def process_time(self, at: datetime, policy: ArmedEventDecision) -> None:
        """Apply a strategy decision at an explicit time boundary."""

        require_aware(at)
        active = self._active
        if active is None or active.armed_setup.state is not ArmedSetupState.ARMED:
            return
        self._apply_non_market_policy(policy)

    def _apply_non_market_policy(self, policy: ArmedEventDecision) -> None:
        active = self._active
        if active is None:
            return
        if policy.action is ArmedEventAction.NO_ACTION:
            return
        if policy.action is not ArmedEventAction.EXPIRE:
            raise ValueError("Only EXPIRE or NO_ACTION is valid without a market event")
        if policy.at is None or policy.expiry_reason is None:
            raise ValueError("EXPIRE decision requires terminal metadata")
        active.armed_setup.expire(at=policy.at, reason=policy.expiry_reason)

    def _build_result(self, candle: CompletedCandle, intent: ArmIntent) -> SignalArmingResult:
        if candle.close is None or candle.low is None:
            raise ValueError("Actionable evaluation requires signal candle close and low")

        created_at = candle.interval.end
        signal = Signal.create(
            instrument_id=candle.instrument_id,
            interval=candle.interval,
            signal_close=candle.close,
            signal_low=candle.low,
            run=self.run,
            created_at=created_at,
        )
        trading_date = candle.interval.end.astimezone(IST).date()
        tick_size = self.tick_schedule.tick_size_on(trading_date)
        tradable_trigger = ceil_to_tick(intent.raw_trigger, tick_size)
        armed_setup = ArmedSetup(
            signal_id=signal.signal_id,
            raw_trigger=intent.raw_trigger,
            tradable_trigger=tradable_trigger,
            signal_low=intent.stop_price,
            armed_at=created_at,
            valid_until=intent.valid_until,
        )
        return SignalArmingResult(signal=signal, armed_setup=armed_setup)
