"""Signal creation and initial ARMED lifecycle for Strategy V1."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from signalforge.domain.armed import ArmedSetup, ArmedSetupState
from signalforge.domain.instruments import TickSizeSchedule
from signalforge.domain.market import CompletedCandle
from signalforge.domain.money import Price, ceil_to_tick
from signalforge.domain.provenance import RunIdentity
from signalforge.domain.signals import Signal
from signalforge.domain.time import IST
from signalforge.runtime.strategy_evaluator import StrategyEvaluatorResult

_ENTRY_OFFSET = Decimal("1.001")


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

    @property
    def active(self) -> SignalArmingResult | None:
        return self._active

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

        if not evaluation.actionable:
            return None
        if candle.close is None or candle.low is None:
            raise ValueError("Actionable evaluation requires signal candle close and low")

        candidate = self._build_result(candle)

        if open_position:
            return None
        if self._active is not None and self._active.armed_setup.state is ArmedSetupState.ARMED:
            if self._active.signal.signal_id == candidate.signal.signal_id:
                return self._active
            return None

        self._active = candidate
        return candidate

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
