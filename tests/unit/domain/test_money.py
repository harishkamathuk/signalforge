from dataclasses import FrozenInstanceError
from decimal import Decimal

import pytest

from signalforge.domain.money import Price, Quantity


def test_price_requires_decimal() -> None:
    with pytest.raises(TypeError, match="Decimal"):
        Price(100.25)  # type: ignore[arg-type]


def test_price_rejects_non_finite_decimal() -> None:
    for value in (Decimal("NaN"), Decimal("Infinity"), Decimal("-Infinity")):
        with pytest.raises(ValueError, match="finite"):
            Price(value)


def test_price_preserves_decimal_exactness() -> None:
    first = Price(Decimal("0.1"))
    second = Price(Decimal("0.2"))

    assert first.value + second.value == Decimal("0.3")
    assert str(Price(Decimal("123.4500"))) == "123.4500"


def test_price_is_immutable() -> None:
    price = Price(Decimal("100.00"))

    with pytest.raises(FrozenInstanceError):
        price.value = Decimal("101.00")  # type: ignore[misc]


def test_quantity_accepts_positive_integer() -> None:
    quantity = Quantity(25)

    assert quantity.value == 25
    assert int(quantity) == 25


@pytest.mark.parametrize("value", [0, -1, -100])
def test_quantity_rejects_non_positive_values(value: int) -> None:
    with pytest.raises(ValueError, match="strictly positive"):
        Quantity(value)


@pytest.mark.parametrize("value", [True, False, 1.5, Decimal("2")])
def test_quantity_rejects_non_integer_values(value: object) -> None:
    with pytest.raises(TypeError, match="integer"):
        Quantity(value)  # type: ignore[arg-type]


def test_quantity_is_immutable() -> None:
    quantity = Quantity(5)

    with pytest.raises(FrozenInstanceError):
        quantity.value = 6  # type: ignore[misc]
