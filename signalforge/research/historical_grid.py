"""Explicit expected coverage for provider-neutral canonical historical bars.

Coverage segments are half-open UTC instants. Five-minute buckets anchor at each
segment's beginning, not at a market open or a UTC-midnight convention.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterator

from signalforge.domain.time import CandleInterval, require_aware, to_utc

_MINUTE = timedelta(minutes=1)
_FIVE_MINUTES = timedelta(minutes=5)


@dataclass(frozen=True, slots=True)
class HistoricalBarGrid:
    """Versioned, deterministic expected one-minute and five-minute coverage."""

    grid_id: str
    version: str
    coverage: tuple[CandleInterval, ...]

    def __post_init__(self) -> None:
        if not self.grid_id.strip() or not self.version.strip():
            raise ValueError("Historical grid requires non-empty identity and version")
        if not self.coverage:
            raise ValueError("Historical grid requires at least one coverage interval")
        normalized: list[CandleInterval] = []
        previous_end: datetime | None = None
        for interval in self.coverage:
            require_aware(interval.start)
            require_aware(interval.end)
            start, end = to_utc(interval.start), to_utc(interval.end)
            if start.second or start.microsecond or end.second or end.microsecond:
                raise ValueError("Historical grid boundaries must align to exact minutes")
            if end <= start or (end - start) % _FIVE_MINUTES:
                raise ValueError("Historical grid segments must have positive five-minute length")
            if previous_end is not None and start < previous_end:
                raise ValueError("Historical grid coverage must be ordered and non-overlapping")
            normalized.append(CandleInterval(start=start, end=end))
            previous_end = end
        object.__setattr__(self, "coverage", tuple(normalized))

    def minute_starts(self) -> Iterator[datetime]:
        """Enumerate expected minute starts without introducing session assumptions."""
        for segment in self.coverage:
            current = segment.start
            while current < segment.end:
                yield current
                current += _MINUTE

    def five_minute_intervals(self) -> Iterator[CandleInterval]:
        """Enumerate complete five-minute intervals anchored to each segment start."""
        for segment in self.coverage:
            current = segment.start
            while current < segment.end:
                yield CandleInterval(current, current + _FIVE_MINUTES)
                current += _FIVE_MINUTES

    @property
    def expected_minute_count(self) -> int:
        """Return expected one-minute observations across all coverage segments."""
        return sum(int((part.end - part.start) / _MINUTE) for part in self.coverage)

    def contains_minute(self, start: datetime) -> bool:
        """Return whether an aligned canonical minute belongs to this grid."""
        instant = to_utc(start)
        return any(part.start <= instant < part.end for part in self.coverage)

    def semantic_mapping(self) -> dict[str, object]:
        """Return versioned coverage identity for dataset hashing and persistence."""
        return {
            "grid_id": self.grid_id,
            "version": self.version,
            "coverage": [
                {"start": part.start.isoformat(), "end": part.end.isoformat()}
                for part in self.coverage
            ],
        }
