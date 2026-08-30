"""Canonical incremental EMA calculations for Strategy V1."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class EmaState:
    """Serializable numerical state required to resume one EMA exactly."""

    period: int
    samples: int
    value: Decimal | None
    seed_sum: Decimal

    def __post_init__(self) -> None:
        _validate_period(self.period)
        if isinstance(self.samples, bool) or not isinstance(self.samples, int):
            raise TypeError("EMA samples must be an integer")
        if self.samples < 0:
            raise ValueError("EMA samples must not be negative")
        if not isinstance(self.seed_sum, Decimal):
            raise TypeError("EMA seed sum must be a Decimal")
        if not self.seed_sum.is_finite():
            raise ValueError("EMA seed sum must be finite")
        if self.value is not None:
            if not isinstance(self.value, Decimal):
                raise TypeError("EMA value must be a Decimal when provided")
            if not self.value.is_finite():
                raise ValueError("EMA value must be finite")
        if self.samples < self.period and self.value is not None:
            raise ValueError("EMA cannot have a value before its seed period is complete")
        if self.samples >= self.period and self.value is None:
            raise ValueError("EMA requires a value once its seed period is complete")


def _validate_period(period: int) -> None:
    if isinstance(period, bool) or not isinstance(period, int):
        raise TypeError("EMA period must be an integer")
    if period <= 0:
        raise ValueError("EMA period must be strictly positive")


@dataclass(slots=True)
class Ema:
    """Incremental EMA with SMA seeding under the frozen Strategy V1 convention."""

    period: int
    samples: int = field(default=0, init=False)
    value: Decimal | None = field(default=None, init=False)
    _seed_sum: Decimal = field(default=Decimal("0"), init=False, repr=False)

    def __post_init__(self) -> None:
        _validate_period(self.period)

    @classmethod
    def from_state(cls, state: EmaState) -> Ema:
        """Restore an EMA from complete checkpoint state."""

        ema = cls(period=state.period)
        ema.samples = state.samples
        ema.value = state.value
        ema._seed_sum = state.seed_sum
        return ema

    @property
    def ready(self) -> bool:
        return self.value is not None

    @property
    def alpha(self) -> Decimal:
        return Decimal(2) / Decimal(self.period + 1)

    @property
    def state(self) -> EmaState:
        return EmaState(
            period=self.period,
            samples=self.samples,
            value=self.value,
            seed_sum=self._seed_sum,
        )

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
