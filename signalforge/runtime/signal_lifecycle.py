"""Signal creation and ARMED lifecycle management for Strategy V1."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from decimal import Decimal

from signalforge.domain.armed import ArmedSetup, ArmedSetupState, ExpiryReason
from signalforge.domain.execution import TriggerEvent
from signalforge.domain.instruments import TickSizeSchedule
from signalforge.domain.market import CompletedCandle, MarketEvent
from signalforge.domain.money import Price, ceil_to_tick
from signalforge.domain.provenance import RunIdentity
from signalforge.domain.signals import Signal
from signalforge.domain.time import IST, require_aware
from signalforge.runtime.strategy_evaluator import StrategyEvaluatorResult

_ENTRY_OFFSET = Decimal("1.001")
_ENTRY_CUTOFF = time(15, 5)


@dataclass(frozen=True, slots=True)
class SignalArmingResult:
    """Immutable facts produced by one successful actionable evaluation."""

    signal: Signal
    armed_setup: ArmedSetup

    def __post_init__(self) -> None:
        if self.armed_setup.signal_id != self.signal.signal_id:
            raise ValueError("ArmedSetup must belong to the produced Signal")
        if self.armed_setup.signal_low != self.signal.signal_low:
            raise ValueError("ArmedSetup signal_low must match the produced Signal")


class SignalLifecycleManager:
    """Own Signal creation and the current single-security ARMED lifecycle."""

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
        evaluator_result: StrategyEvaluatorResult,
        *,
        open_position: bool = False,
    ) -> SignalArmingResult | None:
        """Create one Signal + ARMED setup when the evaluation is actionable.

        Reprocessing the same logical evaluation while its setup remains ARMED is
        idempotent and returns the existing facts. A different actionable evaluation
        is blocked while another setup is ARMED or while an OPEN position exists.
        """

        evaluation = evaluator_result.evaluation
        if candle.instrument_id != evaluation.instrument_id:
            raise ValueError("Candle and StrategyEvaluation instruments must match")
        if candle.interval != evaluation.interval:
            raise ValueError("Candle and StrategyEvaluation intervals must match")
        if self.tick_schedule.instrument_id != candle.instrument_id:
            raise ValueError("TickSizeSchedule instrument must match the signal candle")
        if not isinstance(open_position, bool):
            raise TypeError("open_position must be a boolean")

        if not evaluation.actionable or open_position:
            return None
        if candle.close is None or candle.low is None:
            raise ValueError("Actionable evaluation requires signal candle close and low")

        candidate = self._build_result(candle)

        if self._active is not None and self._active.armed_setup.state is ArmedSetupState.ARMED:
            if self._active.signal.signal_id == candidate.signal.signal_id:
                return self._active
            return None

        self._active = candidate
        self._trigger_event = None
        return candidate

    def process_market_event(self, event: MarketEvent) -> TriggerEvent | None:
        """Apply one ordered observed trade event to the current ARMED setup."""

        active = self._active
        if active is None:
            return None
        setup = active.armed_setup
        if setup.state is not ArmedSetupState.ARMED:
            return self._trigger_event
        if event.instrument_id != active.signal.instrument_id:
            raise ValueError("MarketEvent instrument must match the active setup")

        observed_at = event.exchange_timestamp
        if observed_at < setup.armed_at:
            raise ValueError("MarketEvent timestamp must not precede setup arming")

        cutoff = self._entry_cutoff(active.signal.interval.end)
        if observed_at >= cutoff:
            setup.expire(at=cutoff, reason=ExpiryReason.ENTRY_CUTOFF_REACHED)
            return None
        if observed_at >= setup.valid_until:
            setup.expire(at=setup.valid_until, reason=ExpiryReason.VALIDITY_WINDOW_END)
            return None

        if event.price.value >= setup.tradable_trigger.value:
            trigger_event = TriggerEvent.create(
                signal_id=active.signal.signal_id,
                instrument_id=active.signal.instrument_id,
                reference_price=setup.tradable_trigger,
                observed_price=event.price,
                observed_at=observed_at,
                run=self.run,
            )
            setup.trigger(at=observed_at)
            self._trigger_event = trigger_event
            return trigger_event

        if event.price.value <= setup.signal_low.value:
            setup.expire(at=observed_at, reason=ExpiryReason.SIGNAL_LOW_BREACH)
        return None

    def process_completed_candle(self, candle: CompletedCandle) -> None:
        """Expire an ARMED setup when its immediately following candle completes."""

        active = self._active
        if active is None or active.armed_setup.state is not ArmedSetupState.ARMED:
            return
        if candle.instrument_id != active.signal.instrument_id:
            raise ValueError("CompletedCandle instrument must match the active setup")

        setup = active.armed_setup
        if candle.interval.start != setup.armed_at or candle.interval.end != setup.valid_until:
            raise ValueError("CompletedCandle must be the active setup's following candle")

        cutoff = self._entry_cutoff(active.signal.interval.end)
        if setup.valid_until >= cutoff:
            setup.expire(at=cutoff, reason=ExpiryReason.ENTRY_CUTOFF_REACHED)
        else:
            setup.expire(at=setup.valid_until, reason=ExpiryReason.VALIDITY_WINDOW_END)

    def process_time(self, at: datetime) -> None:
        """Expire an ARMED setup once the 15:05 IST entry cutoff is reached."""

        require_aware(at)
        active = self._active
        if active is None or active.armed_setup.state is not ArmedSetupState.ARMED:
            return

        cutoff = self._entry_cutoff(active.signal.interval.end)
        if at >= cutoff:
            active.armed_setup.expire(at=cutoff, reason=ExpiryReason.ENTRY_CUTOFF_REACHED)

    def _entry_cutoff(self, signal_time: datetime) -> datetime:
        local = signal_time.astimezone(IST)
        return datetime.combine(local.date(), _ENTRY_CUTOFF, tzinfo=IST)

    def _build_result(self, candle: CompletedCandle) -> SignalArmingResult:
        assert candle.close is not None
        assert candle.low is not None

        created_at = candle.interval.end
        signal = Signal.create(
            instrument_id=candle.instrument_id,
            interval=candle.interval,
            signal_close=candle.close,
            signal_low=candle.low,
            run=self.run,
            created_at=created_at,
        )

        raw_trigger = Price(candle.close.value * _ENTRY_OFFSET)
        trading_date = candle.interval.end.astimezone(IST).date()
        tick_size = self.tick_schedule.tick_size_on(trading_date)
        tradable_trigger = ceil_to_tick(raw_trigger, tick_size)
        armed_setup = ArmedSetup(
            signal_id=signal.signal_id,
            raw_trigger=raw_trigger,
            tradable_trigger=tradable_trigger,
            signal_low=candle.low,
            armed_at=created_at,
            valid_until=created_at + timedelta(minutes=5),
        )
        return SignalArmingResult(signal=signal, armed_setup=armed_setup)
