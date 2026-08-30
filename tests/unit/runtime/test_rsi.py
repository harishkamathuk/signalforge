from __future__ import annotations

from decimal import Decimal

import pytest

from signalforge.runtime.rsi import Rsi14, RsiState


def _run(closes: list[str]) -> list[Decimal | None]:
    rsi = Rsi14()
    return [rsi.update(Decimal(close)) for close in closes]


def test_first_rsi_is_produced_on_fifteenth_close() -> None:
    rsi = Rsi14()

    for close in range(1, 15):
        assert rsi.update(Decimal(close)) is None

    assert rsi.update(Decimal("15")) == Decimal("100")
    assert rsi.ready is True
    assert rsi.samples == 15


def test_rising_falling_and_constant_seed_edge_cases() -> None:
    rising = [str(value) for value in range(1, 16)]
    falling = [str(value) for value in range(15, 0, -1)]
    constant = ["123.45"] * 15

    assert _run(rising)[-1] == Decimal("100")
    assert _run(falling)[-1] == Decimal("0")
    assert _run(constant)[-1] == Decimal("50")


def test_first_rsi_uses_arithmetic_mean_seed_averages() -> None:
    closes = [Decimal("100")]
    deltas = [
        Decimal("1"),
        Decimal("-2"),
        Decimal("3"),
        Decimal("-4"),
        Decimal("5"),
        Decimal("-6"),
        Decimal("7"),
        Decimal("-8"),
        Decimal("9"),
        Decimal("-10"),
        Decimal("11"),
        Decimal("-12"),
        Decimal("13"),
        Decimal("-14"),
    ]
    for delta in deltas:
        closes.append(closes[-1] + delta)

    rsi = Rsi14()
    values = [rsi.update(close) for close in closes]

    average_gain = Decimal("49") / Decimal("14")
    average_loss = Decimal("56") / Decimal("14")
    expected = Decimal("100") - (
        Decimal("100") / (Decimal("1") + average_gain / average_loss)
    )
    assert values[-1] == expected


def test_subsequent_value_uses_wilder_smoothing() -> None:
    rsi = Rsi14()
    closes = [Decimal(value) for value in range(1, 16)]
    for close in closes:
        rsi.update(close)

    assert rsi.value == Decimal("100")
    value = rsi.update(Decimal("14"))

    average_gain = Decimal("13") / Decimal("14")
    average_loss = Decimal("1") / Decimal("14")
    expected = Decimal("100") - (
        Decimal("100") / (Decimal("1") + average_gain / average_loss)
    )
    assert value == expected


def test_awkward_decimals_remain_decimal_and_deterministic() -> None:
    closes = [Decimal("100.01") + Decimal(index) / Decimal("37") for index in range(20)]

    first = Rsi14()
    first_values = [first.update(close) for close in closes]

    second = Rsi14()
    second_values = [second.update(close) for close in closes]

    assert first_values == second_values
    assert isinstance(first_values[-1], Decimal)


def test_checkpoint_restore_before_readiness_matches_uninterrupted_path() -> None:
    closes = [Decimal(index) / Decimal("7") for index in range(1, 25)]

    uninterrupted = Rsi14()
    uninterrupted_values = [uninterrupted.update(close) for close in closes]

    partial = Rsi14()
    for close in closes[:8]:
        partial.update(close)
    restored = Rsi14(state=partial.snapshot())
    restored_values = [restored.update(close) for close in closes[8:]]

    assert restored_values == uninterrupted_values[8:]
    assert restored.snapshot() == uninterrupted.snapshot()


def test_checkpoint_restore_after_readiness_matches_uninterrupted_path() -> None:
    closes = [Decimal(index * index) / Decimal("11") for index in range(1, 30)]

    uninterrupted = Rsi14()
    uninterrupted_values = [uninterrupted.update(close) for close in closes]

    partial = Rsi14()
    for close in closes[:20]:
        partial.update(close)
    restored = Rsi14(state=partial.snapshot())
    restored_values = [restored.update(close) for close in closes[20:]]

    assert restored_values == uninterrupted_values[20:]
    assert restored.snapshot() == uninterrupted.snapshot()


def test_rsi_rejects_invalid_input_and_inconsistent_reconstruction_state() -> None:
    rsi = Rsi14()
    with pytest.raises(TypeError, match="Decimal"):
        rsi.update(1.0)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="finite"):
        rsi.update(Decimal("NaN"))

    with pytest.raises(ValueError, match="previous_close"):
        RsiState(
            samples=1,
            previous_close=None,
            seed_gain_sum=Decimal("0"),
            seed_loss_sum=Decimal("0"),
            average_gain=None,
            average_loss=None,
        )

    with pytest.raises(ValueError, match="Wilder averages"):
        RsiState(
            samples=15,
            previous_close=Decimal("100"),
            seed_gain_sum=Decimal("0"),
            seed_loss_sum=Decimal("0"),
            average_gain=None,
            average_loss=None,
        )

    with pytest.raises(ValueError, match="seed sums"):
        RsiState(
            samples=15,
            previous_close=Decimal("100"),
            seed_gain_sum=Decimal("1"),
            seed_loss_sum=Decimal("0"),
            average_gain=Decimal("1"),
            average_loss=Decimal("1"),
        )
