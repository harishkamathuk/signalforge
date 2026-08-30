from datetime import date
from decimal import Decimal

import pytest

from signalforge.domain.ids import InstrumentId
from signalforge.domain.instruments import Instrument, TickSizeRule, TickSizeSchedule
from signalforge.domain.money import Price


def _price(value: str) -> Price:
    return Price(Decimal(value))


def test_instrument_metadata_is_broker_independent() -> None:
    instrument = Instrument(
        instrument_id=InstrumentId("nse-equity-reliance"),
        exchange="NSE",
        symbol="RELIANCE",
    )

    assert instrument.exchange == "NSE"
    assert instrument.symbol == "RELIANCE"
    assert not hasattr(instrument, "broker_id")
    assert not hasattr(instrument, "token")


def test_instrument_rejects_empty_exchange_or_symbol() -> None:
    with pytest.raises(ValueError, match="exchange"):
        Instrument(InstrumentId("x"), " ", "RELIANCE")

    with pytest.raises(ValueError, match="symbol"):
        Instrument(InstrumentId("x"), "NSE", " ")


def test_tick_size_rule_rejects_non_positive_tick_size() -> None:
    with pytest.raises(ValueError, match="strictly positive"):
        TickSizeRule(_price("0"), date(2026, 1, 1))

    with pytest.raises(ValueError, match="strictly positive"):
        TickSizeRule(_price("-0.05"), date(2026, 1, 1))


def test_tick_size_rule_rejects_reversed_effective_dates() -> None:
    with pytest.raises(ValueError, match="effective_to"):
        TickSizeRule(_price("0.05"), date(2026, 2, 1), date(2026, 1, 31))


def test_tick_size_rule_dates_are_inclusive() -> None:
    rule = TickSizeRule(_price("0.05"), date(2026, 1, 1), date(2026, 1, 31))

    assert rule.applies_on(date(2026, 1, 1))
    assert rule.applies_on(date(2026, 1, 31))
    assert not rule.applies_on(date(2025, 12, 31))
    assert not rule.applies_on(date(2026, 2, 1))


def test_schedule_resolves_historical_tick_size() -> None:
    schedule = TickSizeSchedule(
        instrument_id=InstrumentId("nse-equity-example"),
        rules=(
            TickSizeRule(_price("0.10"), date(2026, 7, 1)),
            TickSizeRule(_price("0.05"), date(2025, 1, 1), date(2026, 6, 30)),
        ),
    )

    assert schedule.tick_size_on(date(2026, 6, 30)) == _price("0.05")
    assert schedule.tick_size_on(date(2026, 7, 1)) == _price("0.10")
    assert schedule.rules[0].effective_from == date(2025, 1, 1)


def test_schedule_rejects_overlapping_rules() -> None:
    with pytest.raises(ValueError, match="must not overlap"):
        TickSizeSchedule(
            instrument_id=InstrumentId("nse-equity-example"),
            rules=(
                TickSizeRule(_price("0.05"), date(2026, 1, 1), date(2026, 6, 30)),
                TickSizeRule(_price("0.10"), date(2026, 6, 30), date(2026, 12, 31)),
            ),
        )


def test_open_ended_rule_must_be_last_chronologically() -> None:
    with pytest.raises(ValueError, match="must not overlap"):
        TickSizeSchedule(
            instrument_id=InstrumentId("nse-equity-example"),
            rules=(
                TickSizeRule(_price("0.05"), date(2026, 1, 1)),
                TickSizeRule(_price("0.10"), date(2026, 7, 1)),
            ),
        )


def test_schedule_raises_when_no_rule_applies() -> None:
    schedule = TickSizeSchedule(
        instrument_id=InstrumentId("nse-equity-example"),
        rules=(TickSizeRule(_price("0.05"), date(2026, 1, 1)),),
    )

    with pytest.raises(LookupError, match="No tick-size rule"):
        schedule.tick_size_on(date(2025, 12, 31))


def test_tick_rule_and_schedule_are_immutable() -> None:
    rule = TickSizeRule(_price("0.05"), date(2026, 1, 1))
    schedule = TickSizeSchedule(InstrumentId("nse-equity-example"), (rule,))

    with pytest.raises(AttributeError):
        rule.effective_to = date(2026, 12, 31)  # type: ignore[misc]

    with pytest.raises(AttributeError):
        schedule.rules = ()  # type: ignore[misc]
