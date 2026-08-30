"""Immutable indicator result contract for SignalForge strategy consumers."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from signalforge.domain.ids import InstrumentId
from signalforge.domain.time import CandleInterval


@dataclass(frozen=True, slots=True)
class IndicatorSnapshot:
    """Indicator values produced for one completed canonical candle."""

    instrument_id: InstrumentId
    interval: CandleInterval
    ready: bool
    calculation_version: str
    ema9: Decimal | None = None
    ema20: Decimal | None = None
    ema50: Decimal | None = None
    rsi14: Decimal | None = None
    adx14: Decimal | None = None
    macd_line: Decimal | None = None
    macd_signal: Decimal | None = None
    macd_histogram: Decimal | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.ready, bool):
            raise TypeError("IndicatorSnapshot ready must be a boolean")
        if not self.calculation_version or not self.calculation_version.strip():
            raise ValueError("IndicatorSnapshot calculation_version must not be empty")

        values = self._values()
        for name, value in values.items():
            if value is not None and not isinstance(value, Decimal):
                raise TypeError(f"IndicatorSnapshot {name} must be a Decimal when provided")
            if value is not None and not value.is_finite():
                raise ValueError(f"IndicatorSnapshot {name} must be finite when provided")

        if self.ready and any(value is None for value in values.values()):
            raise ValueError("Ready IndicatorSnapshot requires all indicator values")

    def _values(self) -> dict[str, Decimal | None]:
        return {
            "ema9": self.ema9,
            "ema20": self.ema20,
            "ema50": self.ema50,
            "rsi14": self.rsi14,
            "adx14": self.adx14,
            "macd_line": self.macd_line,
            "macd_signal": self.macd_signal,
            "macd_histogram": self.macd_histogram,
        }
