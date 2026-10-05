"""Canonical regular NSE cash-session boundaries used by live operation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from enum import StrEnum

from signalforge.domain.time import IST, require_aware

NSE_REGULAR_SESSION_OPEN = time(9, 15)
NSE_REGULAR_SESSION_CLOSE = time(15, 30)


class NseSessionPhase(StrEnum):
    """Operational phase relative to the accepted regular NSE session."""

    PRE_SESSION = "pre_session"
    ACTIVE = "active"
    POST_SESSION = "post_session"


@dataclass(frozen=True, slots=True)
class NseSessionBoundaries:
    """Timezone-aware regular-session boundaries for one NSE trading date."""

    trading_date: date
    opens_at: datetime
    closes_at: datetime


def nse_session_boundaries(trading_date: date) -> NseSessionBoundaries:
    """Return accepted regular-session boundaries without redefining strategy rules."""

    return NseSessionBoundaries(
        trading_date=trading_date,
        opens_at=datetime.combine(trading_date, NSE_REGULAR_SESSION_OPEN, tzinfo=IST),
        closes_at=datetime.combine(trading_date, NSE_REGULAR_SESSION_CLOSE, tzinfo=IST),
    )


def nse_session_phase(at: datetime) -> NseSessionPhase:
    """Classify an aware timestamp against its local NSE regular session."""

    local = require_aware(at).astimezone(IST)
    boundaries = nse_session_boundaries(local.date())
    if local < boundaries.opens_at:
        return NseSessionPhase.PRE_SESSION
    if local >= boundaries.closes_at:
        return NseSessionPhase.POST_SESSION
    return NseSessionPhase.ACTIVE
