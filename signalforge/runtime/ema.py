"""Canonical incremental EMA calculations for Strategy V1."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(slots=True)
class Ema:
    """Incremental EMA with SMA seeding under the frozen Strategy V1 convention."""

    period: int
    samples: int = 0
    value: Decimal | None = None
    _seed_sum: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        if isinstance(self.period, bool) or not isinstance(self.period, int):
            raise TypeError("EMA period must be an integer")
        if self.period <= 0:
            raise ValueError("EMA period must be strictly positive")
        if isinstance(self.samples, bool) or not isinstance(self.samples, int):
            raise TypeError("EMA samples must be an integer")
        if self.samples < 0:
            raise ValueError("EMA samples must not be negative")
        if not isinstance(self._seed_sum, Decimal) or not self._seed_sum.is_finite():
            raise ValueError("EMA seed sum must be a finite Decimal")
        if self.value is not None:
            if not isinstance(self.value, Decimal):
                raise TypeError("EMA value must be a Decimal when provided")
            if not self.value.is_finite():
                raise ValueError("EMA value must be finite")
        if self.samples < self.period and self.value is not None:
            raise ValueError("EMA cannot have a value before its seed period is complete")
        if self.samples >= self.period and self.value is None:
            raise ValueError("EMA requires a value once its seed period is complete")

    @property
    def ready(self) -> bool:
        return self.value is not None

    @property
    def alpha(self) -> Decimal:
        return Decimal(2) / Decimal(self.period + 1)

    def update(self, close: Decimal) -> Decimal | None:
        """Consume one close and return the current EMA when ready."""

        if not isinstance(close, Decimal):
            raise TypeError("EMA close must be a Decimal")
        if not close.is_finite():
            raise ValueError("EMA close must be finite")

        if self.samples < self.period:
            self._seed_sum += close
            self.samples += 1
            if self.samples == self.period:
                self.value = self._seed_sum / Decimal(self.period)
            return self.value

        assert self.value is not None
        self.samples += 1
        alpha = self.alpha
        self.value = alpha * close + (Decimal(1) - alpha) * self.value
        return self.value


@dataclass(frozen=True, slots=True)
class EmaValues:
    ema9: Decimal | None
    ema20: Decimal | None
    ema50: Decimal | None


class EmaSet:
    """Advance EMA(9), EMA(20), and EMA(50) from one canonical close stream."""

    def __init__(self) -> None:
        self.ema9 = Ema(period=9)
        self.ema20 = Ema(period=20)
        self.ema50 = Ema(period=50)

    def update(self, close: Decimal) -> EmaValues:
        return EmaValues(
            ema9=self.ema9.update(close),
            ema20=self.ema20.update(close),
            ema50=self.ema50.update(close),
        )
