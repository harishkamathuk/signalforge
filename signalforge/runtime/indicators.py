"""Requirement-driven composition of canonical indicator implementations."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from signalforge.domain.ids import InstrumentId
from signalforge.domain.indicators import (
    AdxRequirement,
    EmaRequirement,
    IndicatorReading,
    IndicatorRequirements,
    IndicatorSnapshot,
    MacdRequirement,
    RsiRequirement,
)
from signalforge.domain.market import CandleQuality, CompletedCandle
from signalforge.domain.time import CandleInterval
from signalforge.runtime.adx import Adx14, AdxState
from signalforge.runtime.ema import Ema, EmaState
from signalforge.runtime.macd import Macd12269, MacdState
from signalforge.runtime.rsi import Rsi14, RsiState


V1_INDICATOR_REQUIREMENTS = IndicatorRequirements.of(
    EmaRequirement(9),
    EmaRequirement(20),
    EmaRequirement(50),
    RsiRequirement(14),
    AdxRequirement(14),
    MacdRequirement(12, 26, 9),
)


class IndicatorContinuity(StrEnum):
    """Continuity state for one indicator-engine stream."""

    HEALTHY = "healthy"
    BROKEN = "broken"


class IndicatorContinuityBroken(RuntimeError):
    """Raised when advancement is attempted after indicator continuity is broken."""


@dataclass(frozen=True, slots=True)
class IndicatorEngineState:
    """Lossless self-describing state for exact indicator continuation."""

    instrument_id: InstrumentId
    calculation_version: str
    continuity: IndicatorContinuity
    last_interval: CandleInterval | None
    requirements: IndicatorRequirements
    ema_states: tuple[EmaState, ...]
    rsi_state: RsiState | None
    adx_state: AdxState | None
    macd_state: MacdState | None

    def __post_init__(self) -> None:
        if not self.calculation_version or not self.calculation_version.strip():
            raise ValueError("IndicatorEngine calculation_version must not be empty")
        expected_ema_periods = tuple(
            item.period for item in self.requirements.items if isinstance(item, EmaRequirement)
        )
        actual_ema_periods = tuple(state.period for state in self.ema_states)
        if actual_ema_periods != expected_ema_periods:
            raise ValueError("IndicatorEngine EMA state shape does not match requirements")
        if (self.rsi_state is not None) != any(
            isinstance(item, RsiRequirement) for item in self.requirements.items
        ):
            raise ValueError("IndicatorEngine RSI state shape does not match requirements")
        if (self.adx_state is not None) != any(
            isinstance(item, AdxRequirement) for item in self.requirements.items
        ):
            raise ValueError("IndicatorEngine ADX state shape does not match requirements")
        if (self.macd_state is not None) != any(
            isinstance(item, MacdRequirement) for item in self.requirements.items
        ):
            raise ValueError("IndicatorEngine MACD state shape does not match requirements")

        counts = [state.samples for state in self.ema_states]
        if self.rsi_state is not None:
            counts.append(self.rsi_state.samples)
        if self.adx_state is not None:
            counts.append(self.adx_state.samples)
        if self.macd_state is not None:
            counts.append(self.macd_state.samples)
        if not counts:
            raise ValueError("IndicatorEngine state requires at least one component")
        if len(set(counts)) != 1:
            raise ValueError("IndicatorEngine component sample counts must match")
        sample_count = counts[0]
        if sample_count == 0 and self.last_interval is not None:
            raise ValueError("Empty IndicatorEngine state cannot have last_interval")
        if sample_count > 0 and self.last_interval is None:
            raise ValueError("Non-empty IndicatorEngine state requires last_interval")

    @property
    def completed_candle_count(self) -> int:
        """Return the common completed-candle count across all components."""

        if self.ema_states:
            return self.ema_states[0].samples
        if self.rsi_state is not None:
            return self.rsi_state.samples
        if self.adx_state is not None:
            return self.adx_state.samples
        assert self.macd_state is not None
        return self.macd_state.samples

    def ema_state(self, period: int) -> EmaState:
        """Return persisted EMA state for a required period."""

        for state in self.ema_states:
            if state.period == period:
                return state
        raise KeyError(f"EMA({period}) is not required")

    # Compatibility accessors preserve existing V1 recovery/tests while the
    # persisted state shape is requirement-driven.
    @property
    def ema9(self) -> EmaState:
        return self.ema_state(9)

    @property
    def ema20(self) -> EmaState:
        return self.ema_state(20)

    @property
    def ema50(self) -> EmaState:
        return self.ema_state(50)

    @property
    def rsi14(self) -> RsiState:
        if self.rsi_state is None:
            raise KeyError("RSI(14) is not required")
        return self.rsi_state

    @property
    def adx14(self) -> AdxState:
        if self.adx_state is None:
            raise KeyError("ADX(14) is not required")
        return self.adx_state

    @property
    def macd(self) -> MacdState:
        if self.macd_state is None:
            raise KeyError("MACD(12,26,9) is not required")
        return self.macd_state


class IndicatorEngine:
    """Advance only the canonical indicators declared by a strategy."""

    def __init__(
        self,
        instrument_id: InstrumentId,
        calculation_version: str,
        *,
        requirements: IndicatorRequirements | None = None,
        state: IndicatorEngineState | None = None,
    ) -> None:
        if not calculation_version or not calculation_version.strip():
            raise ValueError("IndicatorEngine calculation_version must not be empty")
        selected = requirements or (state.requirements if state is not None else V1_INDICATOR_REQUIREMENTS)
        if state is not None:
            if state.instrument_id != instrument_id:
                raise ValueError("IndicatorEngine state instrument does not match engine")
            if state.calculation_version != calculation_version:
                raise ValueError("IndicatorEngine state calculation version does not match engine")
            if state.requirements != selected:
                raise ValueError("IndicatorEngine state requirements do not match engine")
            self._continuity = state.continuity
            self._last_interval = state.last_interval
            self._emas = {item.period: Ema.from_state(item) for item in state.ema_states}
            self._rsi14 = None if state.rsi_state is None else Rsi14(state=state.rsi_state)
            self._adx14 = None if state.adx_state is None else Adx14(state=state.adx_state)
            self._macd = None if state.macd_state is None else Macd12269(state=state.macd_state)
        else:
            self._continuity = IndicatorContinuity.HEALTHY
            self._last_interval = None
            self._emas = {
                item.period: Ema(period=item.period)
                for item in selected.items
                if isinstance(item, EmaRequirement)
            }
            self._rsi14 = (
                Rsi14() if any(isinstance(item, RsiRequirement) for item in selected.items) else None
            )
            self._adx14 = (
                Adx14() if any(isinstance(item, AdxRequirement) for item in selected.items) else None
            )
            self._macd = (
                Macd12269()
                if any(isinstance(item, MacdRequirement) for item in selected.items)
                else None
            )
        self.instrument_id = instrument_id
        self.calculation_version = calculation_version
        self.requirements = selected

    @property
    def continuity(self) -> IndicatorContinuity:
        """Return current continuity state."""

        return self._continuity

    @property
    def state(self) -> IndicatorEngineState:
        """Return a lossless checkpoint for the configured requirement shape."""

        return IndicatorEngineState(
            instrument_id=self.instrument_id,
            calculation_version=self.calculation_version,
            continuity=self._continuity,
            last_interval=self._last_interval,
            requirements=self.requirements,
            ema_states=tuple(self._emas[item.period].state for item in self.requirements.items if isinstance(item, EmaRequirement)),
            rsi_state=None if self._rsi14 is None else self._rsi14.snapshot(),
            adx_state=None if self._adx14 is None else self._adx14.snapshot(),
            macd_state=None if self._macd is None else self._macd.state,
        )

    def break_continuity(self) -> None:
        """Mark the stream broken; subsequent updates fail explicitly."""

        self._continuity = IndicatorContinuity.BROKEN

    def update(self, candle: CompletedCandle, *, continuity_ok: bool = True) -> IndicatorSnapshot:
        """Advance configured indicators from one valid completed candle."""

        if self._continuity is IndicatorContinuity.BROKEN:
            raise IndicatorContinuityBroken("IndicatorEngine continuity is broken")
        if candle.instrument_id != self.instrument_id:
            raise ValueError("IndicatorEngine candle instrument does not match engine")
        if not continuity_ok:
            self.break_continuity()
            raise IndicatorContinuityBroken("Upstream candle continuity is broken")
        if candle.quality is not CandleQuality.VALID:
            self.break_continuity()
            raise IndicatorContinuityBroken("Invalid candle quality breaks indicator continuity")
        if self._last_interval is not None and candle.interval.start < self._last_interval.end:
            self.break_continuity()
            raise IndicatorContinuityBroken("Out-of-order or overlapping candle interval")

        assert candle.close is not None
        close = candle.close.value
        ema_values = {period: ema.update(close) for period, ema in self._emas.items()}
        rsi_value = None if self._rsi14 is None else self._rsi14.update(close)
        if self._adx14 is None:
            adx_value = None
        else:
            assert candle.high is not None and candle.low is not None
            adx_value = self._adx14.update(candle.high.value, candle.low.value, close).adx
        macd_values = None if self._macd is None else self._macd.update(close)
        self._last_interval = candle.interval

        readings: list[IndicatorReading] = []
        for requirement in self.requirements.items:
            if isinstance(requirement, EmaRequirement):
                readings.append(IndicatorReading(requirement, ema_values[requirement.period]))
            elif isinstance(requirement, RsiRequirement):
                readings.append(IndicatorReading(requirement, rsi_value))
            elif isinstance(requirement, AdxRequirement):
                readings.append(IndicatorReading(requirement, adx_value))
            elif isinstance(requirement, MacdRequirement):
                assert macd_values is not None
                readings.append(
                    IndicatorReading(
                        requirement,
                        macd_values.macd_line,
                        macd_values.signal_line,
                        macd_values.histogram,
                    )
                )
            else:
                raise TypeError(
                    f"Unsupported indicator requirement type: {type(requirement).__name__}"
                )

        return IndicatorSnapshot(
            instrument_id=self.instrument_id,
            interval=candle.interval,
            calculation_version=self.calculation_version,
            readings=tuple(readings),
        )
