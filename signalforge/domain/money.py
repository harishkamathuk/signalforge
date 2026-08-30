"""Decimal-safe monetary and quantity primitives."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class Price:
    """Immutable finite Decimal-backed price value."""

    value: Decimal

    def __post_init__(self) -> None:
        if not isinstance(self.value, Decimal):
            raise TypeError("Price value must be a Decimal")
        if not self.value.is_finite():
            raise ValueError("Price value must be finite")

    def __str__(self) -> str:
        return str(self.value)


@dataclass(frozen=True, slots=True)
class Quantity:
    """Immutable strictly positive integral quantity."""

    value: int

    def __post_init__(self) -> None:
        if isinstance(self.value, bool) or not isinstance(self.value, int):
            raise TypeError("Quantity value must be an integer")
        if self.value <= 0:
            raise ValueError("Quantity value must be strictly positive")

    def __int__(self) -> int:
        return self.value
