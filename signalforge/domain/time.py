"""Timezone-safe primitives for SignalForge market and candle timestamps."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


def require_aware(value: datetime) -> datetime:
    """Return *value* if timezone-aware; reject naive datetimes."""

    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must be timezone-aware")
    return value


def to_utc(value: datetime) -> datetime:
    """Convert an aware datetime to UTC without changing the instant."""

    return require_aware(value).astimezone(UTC)


def to_ist(value: datetime) -> datetime:
    """Convert an aware datetime to Asia/Kolkata without changing the instant."""

    return require_aware(value).astimezone(IST)


@dataclass(frozen=True, slots=True)
class CandleInterval:
    """Half-open candle interval ``[start, end)``."""

    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        require_aware(self.start)
        require_aware(self.end)
        if self.end <= self.start:
            raise ValueError("CandleInterval end must be after start")

    @classmethod
    def five_minutes(cls, start: datetime) -> CandleInterval:
        """Build a deterministic five-minute interval from an aware start."""

        start = require_aware(start)
        return cls(start=start, end=start + timedelta(minutes=5))

    def contains(self, value: datetime) -> bool:
        """Return whether *value* belongs to this half-open interval."""

        value = require_aware(value)
        return self.start <= value < self.end
