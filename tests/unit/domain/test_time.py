from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from signalforge.domain.time import IST, CandleInterval, require_aware, to_ist, to_utc


def test_require_aware_rejects_naive_datetime() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        require_aware(datetime(2026, 8, 30, 9, 15))


def test_timezone_conversion_preserves_instant() -> None:
    ist_value = datetime(2026, 8, 30, 9, 15, tzinfo=IST)
    utc_value = to_utc(ist_value)

    assert utc_value == datetime(2026, 8, 30, 3, 45, tzinfo=UTC)
    assert to_ist(utc_value) == ist_value


def test_ist_constant_uses_exchange_timezone() -> None:
    assert IST.key == "Asia/Kolkata"


def test_candle_interval_requires_aware_timestamps() -> None:
    aware = datetime(2026, 8, 30, 9, 15, tzinfo=IST)

    with pytest.raises(ValueError, match="timezone-aware"):
        CandleInterval(start=datetime(2026, 8, 30, 9, 15), end=aware)

    with pytest.raises(ValueError, match="timezone-aware"):
        CandleInterval(start=aware, end=datetime(2026, 8, 30, 9, 20))


def test_candle_interval_requires_positive_duration() -> None:
    start = datetime(2026, 8, 30, 9, 15, tzinfo=IST)

    with pytest.raises(ValueError, match="after start"):
        CandleInterval(start=start, end=start)

    with pytest.raises(ValueError, match="after start"):
        CandleInterval(start=start, end=start - timedelta(minutes=5))


def test_five_minute_interval_is_deterministic() -> None:
    start = datetime(2026, 8, 30, 9, 15, tzinfo=IST)

    interval = CandleInterval.five_minutes(start)

    assert interval.start == start
    assert interval.end == datetime(2026, 8, 30, 9, 20, tzinfo=IST)


def test_candle_interval_is_half_open() -> None:
    interval = CandleInterval.five_minutes(datetime(2026, 8, 30, 9, 15, tzinfo=IST))

    assert interval.contains(datetime(2026, 8, 30, 9, 15, tzinfo=IST))
    assert interval.contains(datetime(2026, 8, 30, 9, 19, 59, 999999, tzinfo=IST))
    assert not interval.contains(datetime(2026, 8, 30, 9, 20, tzinfo=IST))


def test_interval_membership_compares_same_instant_across_timezones() -> None:
    interval = CandleInterval.five_minutes(datetime(2026, 8, 30, 9, 15, tzinfo=IST))

    assert interval.contains(datetime(2026, 8, 30, 3, 47, tzinfo=UTC))
    assert not interval.contains(datetime(2026, 8, 30, 3, 50, tzinfo=UTC))


def test_candle_interval_is_immutable() -> None:
    interval = CandleInterval.five_minutes(datetime(2026, 8, 30, 9, 15, tzinfo=IST))

    with pytest.raises(AttributeError):
        interval.start = datetime(2026, 8, 30, 9, 20, tzinfo=IST)  # type: ignore[misc]


def test_conversion_accepts_non_ist_aware_timezone() -> None:
    london = ZoneInfo("Europe/London")
    value = datetime(2026, 8, 30, 9, 15, tzinfo=london)

    assert to_utc(value).tzinfo is UTC
    assert to_ist(value).tzinfo == IST
