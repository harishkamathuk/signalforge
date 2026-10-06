from __future__ import annotations

from datetime import datetime

from signalforge.domain.session import (
    NSE_REGULAR_SESSION_BOUNDARY,
    NSE_REGULAR_SESSION_OPEN,
    NseSessionPhase,
    nse_regular_session_boundary_at,
    nse_regular_session_open_at,
    nse_session_phase,
)
from signalforge.domain.time import IST


def test_canonical_nse_session_boundaries_are_shared_contract() -> None:
    assert NSE_REGULAR_SESSION_OPEN.isoformat(timespec="minutes") == "09:15"
    assert NSE_REGULAR_SESSION_BOUNDARY.isoformat(timespec="minutes") == "15:30"


def test_nse_session_phase_is_half_open() -> None:
    assert (
        nse_session_phase(datetime(2026, 10, 5, 9, 14, 59, tzinfo=IST))
        is NseSessionPhase.PRE_SESSION
    )
    assert (
        nse_session_phase(datetime(2026, 10, 5, 9, 15, tzinfo=IST))
        is NseSessionPhase.ACTIVE
    )
    assert (
        nse_session_phase(datetime(2026, 10, 5, 15, 29, 59, tzinfo=IST))
        is NseSessionPhase.ACTIVE
    )
    assert (
        nse_session_phase(datetime(2026, 10, 5, 15, 30, tzinfo=IST))
        is NseSessionPhase.POST_SESSION
    )


def test_session_boundary_helpers_preserve_ist_date() -> None:
    at = datetime(2026, 10, 5, 8, 0, tzinfo=IST)

    assert nse_regular_session_open_at(at) == datetime(2026, 10, 5, 9, 15, tzinfo=IST)
    assert nse_regular_session_boundary_at(at) == datetime(
        2026, 10, 5, 15, 30, tzinfo=IST
    )
