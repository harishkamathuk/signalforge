"""Canonical NSE regular-session timing shared by runtime-facing applications."""

from __future__ import annotations

from datetime import datetime, time
from enum import StrEnum

from signalforge.domain.time import IST, require_aware

NSE_REGULAR_SESSION_OPEN = time(9, 15)
NSE_REGULAR_SESSION_BOUNDARY = time(15, 30)


class NseSessionPhase(StrEnum):
    """Operational phase for the canonical NSE regular session."""

    PRE_SESSION = "pre_session"
    ACTIVE = "active"
    POST_SESSION = "post_session"


def nse_session_phase(at: datetime) -> NseSessionPhase:
    """Classify an aware timestamp against the accepted regular-session window."""

    local = require_aware(at).astimezone(IST)
    local_time = local.time().replace(tzinfo=None)
    if local_time < NSE_REGULAR_SESSION_OPEN:
        return NseSessionPhase.PRE_SESSION
    if local_time < NSE_REGULAR_SESSION_BOUNDARY:
        return NseSessionPhase.ACTIVE
    return NseSessionPhase.POST_SESSION


def nse_regular_session_open_at(at: datetime) -> datetime:
    """Return the canonical regular-session activation instant for *at*'s IST date."""

    local = require_aware(at).astimezone(IST)
    return datetime.combine(local.date(), NSE_REGULAR_SESSION_OPEN, tzinfo=IST)


def nse_regular_session_boundary_at(at: datetime) -> datetime:
    """Return the canonical regular-session end boundary for *at*'s IST date."""

    local = require_aware(at).astimezone(IST)
    return datetime.combine(local.date(), NSE_REGULAR_SESSION_BOUNDARY, tzinfo=IST)
