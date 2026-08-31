"""Canonical incremental MACD(12,26,9) calculation for Strategy V1."""

from dataclasses import dataclass
from decimal import Decimal

from signalforge.runtime.ema import Ema, EmaState

_FAST_PERIOD = 12
_SLOW_PERIOD = 26
_SIGNAL_PERIOD = 9


@dataclass(frozen=True, slots=True)
class MacdValues:
    ema12: Decimal | None
    ema26: Decimal | None
    macd_line: Decimal | None
    signal_line: Decimal | None
    histogram: Decimal | None


@dataclass(frozen=True, slots=True)
class MacdState:
    samples: int
    fast_ema: EmaState
    slow_ema: EmaState
    signal_ema: EmaState

    def __post_init__(self) -> None:
        if isinstance(self.samples, bool) or not isinstance(self.samples, int):
            raise TypeError("MACD samples must be an integer")
        if self.samples < 0:
            raise ValueError("MACD samples must not be negative")
        if self.fast_ema.period != _FAST_PERIOD:
            raise ValueError("MACD fast EMA state must use period 12")
        if self.slow_ema.period != _SLOW_PERIOD:
            raise ValueError("MACD slow EMA state must use period 26")
        if self.signal_ema.period != _SIGNAL_PERIOD:
            raise ValueError("MACD signal EMA state must use period 9")
        if self.fast_ema.samples != self.samples:
            raise ValueError("MACD fast EMA sample count must match MACD sample count")
        if self.slow_ema.samples != self.samples:
            raise ValueError("MACD slow EMA sample count must match MACD sample count")

        expected_signal_samples = max(0, self.samples - (_SLOW_PERIOD - 1))
        if self.signal_ema.samples != expected_signal_samples:
            raise ValueError("MACD signal EMA sample count must match valid MACD observations")


class Macd12269:
    """Incremental MACD(12,26,9) with the frozen Gate 1 readiness convention."""

    def __init__(self, *, state: MacdState | None = None) -> None:
        if state is None:
            self._fast = Ema(period=_FAST_PERIOD)
            self._slow = Ema(period=_SLOW_PERIOD)
            self._signal = Ema(period=_SIGNAL_PERIOD)
            self._samples = 0
        else:
            self._fast = Ema.from_state(state.fast_ema)
            self._slow = Ema.from_state(state.slow_ema)
            self._signal = Ema.from_state(state.signal_ema)
            self._samples = state.samples

    @property
    def samples(self) -> int:
        return self._samples

    @property
    def macd_ready(self) -> bool:
        return self._slow.ready

    @property
    def fully_ready(self) -> bool:
        return self._signal.ready

    @property
    def state(self) -> MacdState:
        return MacdState(
            samples=self._samples,
            fast_ema=self._fast.state,
            slow_ema=self._slow.state,
            signal_ema=self._signal.state,
        )

    def update(self, close: Decimal) -> MacdValues:
        if not isinstance(close, Decimal):
            raise TypeError("MACD close must be a Decimal")
        if not close.is_finite():
            raise ValueError("MACD close must be finite")

        ema12 = self._fast.update(close)
        ema26 = self._slow.update(close)
        self._samples += 1

        if ema26 is None:
            return MacdValues(ema12, None, None, None, None)

        assert ema12 is not None
        macd_line = ema12 - ema26
        signal_line = self._signal.update(macd_line)
        histogram = None if signal_line is None else macd_line - signal_line
        return MacdValues(ema12, ema26, macd_line, signal_line, histogram)
