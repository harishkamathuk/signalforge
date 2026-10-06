"""Narrow NSE equities trading-calendar support for M8 live PAPER readiness."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

# Official NSE equities holidays published for calendar year 2026.
# Keep this deliberately bounded: SF-073 needs a correct current-M8 calendar,
# not a speculative generic exchange-calendar framework.
_NSE_EQUITY_HOLIDAYS_2026 = frozenset(
    {
        date(2026, 1, 15),
        date(2026, 1, 26),
        date(2026, 3, 3),
        date(2026, 3, 26),
        date(2026, 3, 31),
        date(2026, 4, 3),
        date(2026, 4, 14),
        date(2026, 5, 1),
        date(2026, 5, 28),
        date(2026, 6, 26),
        date(2026, 9, 14),
        date(2026, 10, 2),
        date(2026, 10, 20),
        date(2026, 11, 10),
        date(2026, 11, 24),
        date(2026, 12, 25),
    }
)


class TradingCalendarUnavailable(RuntimeError):
    """Raised when SignalForge has no authoritative calendar coverage."""


@dataclass(frozen=True, slots=True)
class NseEquityTradingCalendar:
    """Authoritative-enough bounded NSE equities calendar for calendar year 2026."""

    covered_year: int = 2026

    def _require_covered(self, value: date) -> None:
        if value.year != self.covered_year:
            raise TradingCalendarUnavailable(
                f"NSE equities trading calendar has no authoritative coverage for {value.year}"
            )

    def is_trading_day(self, value: date) -> bool:
        self._require_covered(value)
        return value.weekday() < 5 and value not in _NSE_EQUITY_HOLIDAYS_2026

    def previous_trading_day(self, target: date) -> date:
        """Return the immediately preceding NSE equities trading date."""

        self._require_covered(target)
        candidate = target - timedelta(days=1)
        while candidate.year == self.covered_year:
            if self.is_trading_day(candidate):
                return candidate
            candidate -= timedelta(days=1)
        raise TradingCalendarUnavailable(
            f"NSE equities trading calendar cannot resolve the session before {target.isoformat()}"
        )

    def trading_days(self, start: date, end: date) -> tuple[date, ...]:
        """Return covered trading dates inclusively."""

        self._require_covered(start)
        self._require_covered(end)
        if end < start:
            raise ValueError("trading calendar end must not precede start")
        days: list[date] = []
        current = start
        while current <= end:
            if self.is_trading_day(current):
                days.append(current)
            current += timedelta(days=1)
        return tuple(days)
