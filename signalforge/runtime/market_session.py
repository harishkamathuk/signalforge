"""Typed market/session timing policy for shared runtime mechanics."""

from __future__ import annotations

from datetime import date, datetime, time
from typing import Protocol

from signalforge.domain.provenance import (
    LEGACY_NSE_MARKET_SESSION_POLICY_IDENTITY,
    MarketSessionPolicyIdentity,
)
from signalforge.domain.session import (
    NSE_REGULAR_SESSION_BOUNDARY,
    NSE_REGULAR_SESSION_OPEN,
)
from signalforge.domain.time import IST, require_aware


class MarketSessionPolicy(Protocol):
    """Market-level timing required by shared replay/lifecycle mechanics."""

    @property
    def identity(self) -> MarketSessionPolicyIdentity:
        """Return stable trade-affecting policy identity."""
        ...

    def accepts_event(self, at: datetime) -> bool:
        """Return whether an event timestamp belongs to the accepted input window."""
        ...

    def trading_date(self, at: datetime) -> date:
        """Resolve the market trading date used by effective-dated rules."""
        ...

    def compulsory_exit_at(self, at: datetime) -> datetime:
        """Return the compulsory open-position exit boundary for *at*'s trading date."""
        ...


class NseIntradayMarketSessionPolicy:
    """Current NSE cash-equity regular-session policy, preserving existing semantics."""

    _FORCED_EXIT_TIME = time(15, 15)

    @property
    def identity(self) -> MarketSessionPolicyIdentity:
        return LEGACY_NSE_MARKET_SESSION_POLICY_IDENTITY

    def accepts_event(self, at: datetime) -> bool:
        local = require_aware(at).astimezone(IST)
        local_time = local.time().replace(tzinfo=None)
        return NSE_REGULAR_SESSION_OPEN <= local_time <= NSE_REGULAR_SESSION_BOUNDARY

    def trading_date(self, at: datetime) -> date:
        return require_aware(at).astimezone(IST).date()

    def compulsory_exit_at(self, at: datetime) -> datetime:
        local = require_aware(at).astimezone(IST)
        return datetime.combine(local.date(), self._FORCED_EXIT_TIME, tzinfo=IST)


NSE_INTRADAY_MARKET_SESSION_POLICY = NseIntradayMarketSessionPolicy()
