from __future__ import annotations

from decimal import Decimal

import pytest

from signalforge.runtime.ema import Ema, EmaSet


def test_ema_produces_no_value_before_seed_period() -> None:
    ema = Ema(period=3)

    assert ema.update(Decimal("10")) is None
    assert ema.update(Decimal("20")) is None
    assert ema.ready is False
    assert ema.samples == 2


def test_nth_close_seeds_ema_with_simple_moving_average() -> None:
    ema = Ema(period=3)

    ema.update(Decimal("10"))
    ema.update(Decimal("20"))
    value = ema.update(Decimal("40"))

    assert value == Decimal("70") / Decimal("3")
    assert ema.value == value
    assert ema.ready is True
    assert ema.samples == 3


def test_subsequent_close_uses_frozen_recursive_formula() -> None:
    ema = Ema(period=3)
    ema.update(Decimal("10"))
    ema.update(Decimal("20"))
    seed = ema.update(Decimal("40"))
    assert seed is not None

    value = ema.update(Decimal("50"))
    expected = Decimal("0.5") * Decimal("50") + Decimal("0.5") * seed

    assert ema.alpha == Decimal("0.5")
    assert value == expected


def test_constant_series_remains_constant_after_seed() -> None:
    ema = Ema(period=4)

    values = [ema.update(Decimal("123.45")) for _ in range(8)]

    assert values[:3] == [None, None, None]
    assert values[3:] == [Decimal("123.45")] * 5


def test_awkward_decimal_values_are_processed_as_decimals() -> None:
    ema = Ema(period=2)

    assert ema.update(Decimal("100.01")) is None
    seed = ema.update(Decimal("100.02"))
    assert seed == Decimal("100.015")

    value = ema.update(Decimal("100.04"))
    expected = ema.alpha * Decimal("100.04") + (Decimal(1) - ema.alpha) * seed

    assert value == expected
    assert isinstance(value, Decimal)


def test_ema_set_tracks_independent_readiness() -> None:
    emas = EmaSet()

    ninth = None
    twentieth = None
    fiftieth = None
    for index in range(1, 51):
        values = emas.update(Decimal(index))
        if index == 9:
            ninth = values
        if index == 20:
            twentieth = values
        if index == 50:
            fiftieth = values

    assert ninth is not None
    assert ninth.ema9 == Decimal("5")
    assert ninth.ema20 is None
    assert ninth.ema50 is None

    assert twentieth is not None
    assert twentieth.ema9 is not None
    assert twentieth.ema20 == Decimal("10.5")
    assert twentieth.ema50 is None

    assert fiftieth is not None
    assert fiftieth.ema9 is not None
    assert fiftieth.ema20 is not None
    assert fiftieth.ema50 == Decimal("25.5")


def test_batch_replay_matches_incremental_outputs() -> None:
    closes = [Decimal(index) / Decimal("7") for index in range(1, 65)]

    first = Ema(period=9)
    incremental = [first.update(close) for close in closes]

    second = Ema(period=9)
    replayed: list[Decimal | None] = []
    for close in closes:
        replayed.append(second.update(close))

    assert replayed == incremental
    assert second.samples == first.samples
    assert second.value == first.value


def test_ema_rejects_invalid_period_close_and_reconstruction_state() -> None:
    with pytest.raises(ValueError, match="strictly positive"):
        Ema(period=0)
    with pytest.raises(TypeError, match="integer"):
        Ema(period=True)

    ema = Ema(period=3)
    with pytest.raises(TypeError, match="Decimal"):
        ema.update(1.0)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="finite"):
        ema.update(Decimal("NaN"))

    with pytest.raises(ValueError, match="before its seed period"):
        Ema(period=3, samples=2, value=Decimal("10"))
    with pytest.raises(ValueError, match="requires a value"):
        Ema(period=3, samples=3, value=None)
