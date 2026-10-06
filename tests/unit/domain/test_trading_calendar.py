from datetime import date

import pytest

from signalforge.domain.trading_calendar import (
    NseEquityTradingCalendar,
    TradingCalendarUnavailable,
)


def test_previous_session_respects_nse_holiday_and_weekend() -> None:
    calendar = NseEquityTradingCalendar()

    assert calendar.previous_trading_day(date(2026, 10, 5)) == date(2026, 10, 1)
    assert not calendar.is_trading_day(date(2026, 10, 2))


def test_calendar_fails_outside_authoritative_coverage() -> None:
    calendar = NseEquityTradingCalendar()

    with pytest.raises(TradingCalendarUnavailable):
        calendar.is_trading_day(date(2027, 1, 4))
