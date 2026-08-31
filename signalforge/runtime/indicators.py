"""Canonical indicator-engine composition for Strategy V1."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from signalforge.domain.ids import InstrumentId
from signalforge.domain.indicators import IndicatorSnapshot
from signalforge.domain.market import CandleQuality, CompletedCandle
from signalforge.domain.time import CandleInterval
from signalforge.runtime.adx import Adx14, AdxState
from signalforge.runtime.ema import Ema, EmaState
from signalforge.runtime.macd import Macd12269, MacdState
from signalforge.runtime.rsi import Rsi14, RsiState


class IndicatorContinuity(StrEnum):
    HEALTHY = "healthy"
    BROKEN = "broken"


class IndicatorContinuityBroken(RuntimeError):
    """Raised when advancement is attempted after indicator continuity is broken."""


@dataclass(frozen=True, slots=True)
class IndicatorEngineState:
    instrument_id: InstrumentId
    calculation_version: str
    continuity: IndicatorContinuity
    last_interval: CandleInterval | None
    ema9: EmaState
    ema20: EmaState
    ema50: EmaState
    rsi14: RsiState
    adx14: AdxState
    macd: MacdState

    def __post_init__(self) -> None:
        if not self.calculation_version or not self.calculation_version.strip():
            raise ValueError("IndicatorEngine calculation_version must not be empty")
        samples = {
            self.ema9.samples,
            self.ema20.samples,
            self.ema50.samples,
            self.rsi14.samples,
            self.adx14.samples,
            self.macd.samples,
        }
        if len(samples) != 1:
            raise ValueError("IndicatorEngine component sample counts must match")
        sample_count = next(iter(samples))
        if sample_count == 0 and self.last_interval is not None:
            raise ValueError("Empty IndicatorEngine state cannot have last_interval")
        if sample_count > 0 and self.last_interval is None:
            raise ValueError("Non-empty IndicatorEngine state requires last_interval")


class IndicatorEngine:
    """Advance all canonical Strategy V1 indicators from one candle stream."""

    def __init__(
        self,
        instrument_id: InstrumentId,
        calculation_version: str,
        *,
        state: IndicatorEngineState | None = None,
    ) -> None:
        if not calculation_version or not calculation_version.strip():
            raise ValueError("IndicatorEngine calculation_version must not be empty")
        if state is not None:
            if state.instrument_id != instrument_id:
                raise ValueError("IndicatorEngine state instrument does not match engine")
            if state.calculation_version != calculation_version:
                raise ValueError("IndicatorEngine state calculation version does not match engine")
            self._continuity = state.continuity
            self._last_interval = state.last_interval
            self._ema9 = Ema.from_state(state.ema9)
            self._ema20 = Ema.from_state(state.ema20)
            self._ema50 = Ema.from_state(state.ema50)
            self._rsi14 = Rsi14(state=state.rsi14)
            self._adx14 = Adx14(state=state.adx14)
            self._macd = Macd12269(state=state.macd)
        else:
            self._continuity = IndicatorContinuity.HEALTHY
            self._last_interval = None
            self._ema9 = Ema(period=9)
            self._ema20 = Ema(period=20)
            self._ema50 = Ema(period=50)
            self._rsi14 = Rsi14()
            self._adx14 = Adx14()
            self._macd = Macd12269()
        self.instrument_id = instrument_id
        self.calculation_version = calculation_version

    @property
    def continuity(self) -> IndicatorContinuity:
        return self._continuity

    @property
    def state(self) -> IndicatorEngineState:
        return IndicatorEngineState(
            instrument_id=self.instrument_id,
            calculation_version=self.calculation_version,
            continuity=self._continuity,
            last_interval=self._last_interval,
            ema9=self._ema9.state,
            ema20=self._ema20.state,
            ema50=self._ema50.state,
            rsi14=self._rsi14.snapshot(),
            adx14=self._adx14.snapshot(),
            macd=self._macd.state,
        )

    def break_continuity(self) -> None:
        self._continuity = IndicatorContinuity.BROKEN

    def update(self, candle: CompletedCandle, *, continuity_ok: bool = True) -> IndicatorSnapshot:
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

        assert candle.high is not None
        assert candle.low is not None
        assert candle.close is not None
        close = candle.close.value
        ema9 = self._ema9.update(close)
        ema20 = self._ema20.update(close)
        ema50 = self._ema50.update(close)
        rsi14 = self._rsi14.update(close)
        adx_values = self._adx14.update(candle.high.value, candle.low.value, close)
        macd_values = self._macd.update(close)
        self._last_interval = candle.interval

        values = (
            ema9,
            ema20,
            ema50,
            rsi14,
            adx_values.adx,
            macd_values.macd_line,
            macd_values.signal_line,
            macd_values.histogram,
        )
        return IndicatorSnapshot(
            instrument_id=self.instrument_id,
            interval=candle.interval,
            ready=all(value is not None for value in values),
            calculation_version=self.calculation_version,
            ema9=ema9,
            ema20=ema20,
            ema50=ema50,
            rsi14=rsi14,
            adx14=adx_values.adx,
            macd_line=macd_values.macd_line,
            macd_signal=macd_values.signal_line,
            macd_histogram=macd_values.histogram,
        )
