from decimal import Decimal

import pytest

from signalforge.domain.money import Price, ceil_to_tick


def test_tick_aligned_price_is_unchanged() -> None:
    price = Price(Decimal("100.10"))
    tick = Price(Decimal("0.05"))

    assert ceil_to_tick(price, tick) == price


def test_between_tick_price_rounds_up() -> None:
    price = Price(Decimal("100.11"))
    tick = Price(Decimal("0.05"))

    assert ceil_to_tick(price, tick) == Price(Decimal("100.15"))


def test_awkward_decimal_tick_is_deterministic() -> None:
    price = Price(Decimal("1.0000001"))
    tick = Price(Decimal("0.0000003"))

    assert ceil_to_tick(price, tick) == Price(Decimal("1.0000002"))


def test_non_power_of_ten_tick_is_supported() -> None:
    price = Price(Decimal("99.991"))
    tick = Price(Decimal("0.025"))

    assert ceil_to_tick(price, tick) == Price(Decimal("100.000"))


def test_tick_size_must_be_positive() -> None:
    price = Price(Decimal("100"))

    with pytest.raises(ValueError, match="strictly positive"):
        ceil_to_tick(price, Price(Decimal("0")))

    with pytest.raises(ValueError, match="strictly positive"):
        ceil_to_tick(price, Price(Decimal("-0.05")))


def test_ceiling_never_returns_below_input() -> None:
    price = Price(Decimal("123.4567"))
    tick = Price(Decimal("0.07"))

    normalized = ceil_to_tick(price, tick)

    assert normalized.value >= price.value
    assert normalized.value % tick.value == 0
