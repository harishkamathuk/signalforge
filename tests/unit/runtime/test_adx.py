from decimal import Decimal

import pytest

from signalforge.runtime.adx import Adx14, AdxState


def _trend_candle(index: int) -> tuple[Decimal, Decimal, Decimal]:
    base = Decimal(index)
    return base + Decimal("11"), base + Decimal("9"), base + Decimal("10")


def test_first_candle_creates_no_raw_adx_observation() -> None:
    adx = Adx14()

    values = adx.update(Decimal("10"), Decimal("8"), Decimal("9"))

    assert values.tr is None
    assert values.plus_dm is None
    assert values.minus_dm is None
    assert values.dx is None
    assert adx.samples == 1


def test_raw_tr_and_directional_movement_follow_wilder_rules() -> None:
    adx = Adx14()
    adx.update(Decimal("10"), Decimal("8"), Decimal("9"))

    values = adx.update(Decimal("12"), Decimal("8.5"), Decimal("11"))

    assert values.tr == Decimal("3.5")
    assert values.plus_dm == Decimal("2")
    assert values.minus_dm == Decimal("0")


def test_tied_directional_moves_produce_zero_dm() -> None:
    adx = Adx14()
    adx.update(Decimal("10"), Decimal("8"), Decimal("9"))

    values = adx.update(Decimal("11"), Decimal("7"), Decimal("9"))

    assert values.plus_dm == 0
    assert values.minus_dm == 0


def test_first_di_and_dx_are_available_on_c14() -> None:
    adx = Adx14()
    outputs = []
    for index in range(15):
        outputs.append(adx.update(*_trend_candle(index)))

    assert outputs[13].plus_di is None
    assert outputs[13].dx is None
    assert outputs[14].plus_di == Decimal("50")
    assert outputs[14].minus_di == Decimal("0")
    assert outputs[14].dx == Decimal("100")
    assert outputs[14].adx is None


def test_first_adx_is_ready_on_c27_not_c26() -> None:
    adx = Adx14()
    outputs = [adx.update(*_trend_candle(index)) for index in range(28)]

    assert outputs[26].adx is None
    assert outputs[27].adx == Decimal("100")
    assert adx.ready is True


def test_first_adx_seed_uses_exactly_fourteen_dx_values() -> None:
    adx = Adx14()
    for index in range(27):
        adx.update(*_trend_candle(index))

    before = adx.snapshot()
    assert before.samples == 27
    assert before.dx_seed_count == 13
    assert before.dx_seed_sum == Decimal("1300")
    assert before.adx is None

    values = adx.update(*_trend_candle(27))
    after = adx.snapshot()
    assert values.dx == Decimal("100")
    assert values.adx == Decimal("100")
    assert after.dx_seed_count == 14
    assert after.dx_seed_sum == 0


def test_zero_denominators_produce_zero_di_dx_and_adx() -> None:
    adx = Adx14()
    outputs = [
        adx.update(Decimal("10"), Decimal("10"), Decimal("10"))
        for _ in range(28)
    ]

    assert outputs[14].plus_di == 0
    assert outputs[14].minus_di == 0
    assert outputs[14].dx == 0
    assert outputs[27].adx == 0


def test_wilder_adx_recursion_uses_unrounded_previous_value() -> None:
    adx = Adx14()
    for index in range(28):
        adx.update(*_trend_candle(index))
    previous = adx.value
    assert previous == Decimal("100")

    values = adx.update(Decimal("37"), Decimal("20"), Decimal("21"))
    assert values.dx is not None
    expected = ((previous * Decimal("13")) + values.dx) / Decimal("14")
    assert values.adx == expected


def test_checkpoint_restore_before_readiness_is_exact() -> None:
    uninterrupted = Adx14()
    closes = [_trend_candle(index) for index in range(40)]
    for candle in closes[:10]:
        uninterrupted.update(*candle)

    restored = Adx14(state=uninterrupted.snapshot())
    expected = [uninterrupted.update(*candle) for candle in closes[10:]]
    actual = [restored.update(*candle) for candle in closes[10:]]

    assert actual == expected
    assert restored.snapshot() == uninterrupted.snapshot()


def test_checkpoint_restore_after_readiness_is_exact() -> None:
    uninterrupted = Adx14()
    candles = [_trend_candle(index) for index in range(45)]
    for candle in candles[:32]:
        uninterrupted.update(*candle)

    restored = Adx14(state=uninterrupted.snapshot())
    expected = [uninterrupted.update(*candle) for candle in candles[32:]]
    actual = [restored.update(*candle) for candle in candles[32:]]

    assert actual == expected
    assert restored.snapshot() == uninterrupted.snapshot()


def test_checkpoint_dx_seed_count_must_match_candle_progress() -> None:
    with pytest.raises(ValueError, match="seed count must match candle progress"):
        AdxState(
            samples=20,
            previous_high=Decimal("10"),
            previous_low=Decimal("9"),
            previous_close=Decimal("9.5"),
            seed_tr_sum=Decimal("0"),
            seed_plus_dm_sum=Decimal("0"),
            seed_minus_dm_sum=Decimal("0"),
            smoothed_tr=Decimal("14"),
            smoothed_plus_dm=Decimal("7"),
            smoothed_minus_dm=Decimal("0"),
            dx_seed_sum=Decimal("500"),
            dx_seed_count=5,
            adx=None,
        )


def test_invalid_input_and_reconstruction_state_are_rejected() -> None:
    adx = Adx14()
    with pytest.raises(TypeError, match="Decimal"):
        adx.update(10.0, Decimal("9"), Decimal("9.5"))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="greater than or equal"):
        adx.update(Decimal("8"), Decimal("9"), Decimal("8.5"))

    with pytest.raises(ValueError, match="cannot be ready before C27"):
        AdxState(
            samples=20,
            previous_high=Decimal("10"),
            previous_low=Decimal("9"),
            previous_close=Decimal("9.5"),
            seed_tr_sum=Decimal("0"),
            seed_plus_dm_sum=Decimal("0"),
            seed_minus_dm_sum=Decimal("0"),
            smoothed_tr=Decimal("14"),
            smoothed_plus_dm=Decimal("7"),
            smoothed_minus_dm=Decimal("0"),
            dx_seed_sum=Decimal("500"),
            dx_seed_count=5,
            adx=Decimal("100"),
        )
