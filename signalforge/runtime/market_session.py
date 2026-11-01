"""Typed market/session timing policy for shared runtime mechanics."""

from __future__ import annotations

from datetime import datetime, time
from typing import Protocol

from signalforge.domain.session import (
    NSE_REGULAR_SESSION_BOUNDARY,
    NSE_REGULAR_SESSION_OPEN,
)
from signalforge.domain.time import IST, require_aware


class MarketSessionPolicy(Protocol):
    """Market-level timing required by shared replay/lifecycle mechanics."""

    def accepts_event(self, at: datetime) -> bool:
        """Return whether an event timestamp belongs to the accepted input window."""
        ...

    def compulsory_exit_at(self, at: datetime) -> datetime:
        """Return the compulsory open-position exit boundary for *at*'s trading date."""
        ...


class NseIntradayMarketSessionPolicy:
    """Current NSE cash-equity regular-session policy, preserving existing semantics."""

    _FORCED_EXIT_TIME = time(15, 15)

    def accepts_event(self, at: datetime) -> bool:
        local = require_aware(at).astimezone(IST)
        local_time = local.time().replace(tzinfo=None)
        return NSE_REGULAR_SESSION_OPEN <= local_time <= NSE_REGULAR_SESSION_BOUNDARY

    def compulsory_exit_at(self, at: datetime) -> datetime:
        local = require_aware(at).astimezone(IST)
        return datetime.combine(local.date(), self._FORCED_EXIT_TIME, tzinfo=IST)


NSE_INTRADAY_MARKET_SESSION_POLICY = NseIntradayMarketSessionPolicy()
