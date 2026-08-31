from decimal import Decimal

import pytest

from signalforge.runtime.macd import Macd12269, MacdState


def _closes(count: int) -> list[Decimal]:
    return [Decimal(index) + Decimal("100.125") for index in range(count)]


def test_readiness_boundaries_match_gate_1_contract() -> None:
    macd = Macd12269()
    outputs = [macd.update(close) for close in _closes(34)]

    assert outputs[10].ema12 is None
    assert outputs[11].ema12 is not None

    assert outputs[24].ema26 is None
    assert outputs[24].macd_line is None
    assert outputs[25].ema26 is not None
    assert outputs[25].macd_line is not None

    assert outputs[32].signal_line is None
    assert outputs[32].histogram is None
    assert outputs[33].signal_line is not None
    assert outputs[33].histogram is not None


def test_macd_line_is_available_before_signal_and_histogram() -> None:
    macd = Macd12269()
    outputs = [macd.update(close) for close in _closes(33)]

    for output in outputs[25:33]:
        assert output.macd_line is not None
        assert output.signal_line is None
        assert output.histogram is None


def test_signal_seed_uses_exactly_first_nine_macd_values() -> None:
    macd = Macd12269()
    outputs = [macd.update(close) for close in _closes(34)]

    macd_seed = [output.macd_line for output in outputs[25:34]]
    assert all(value is not None for value in macd_seed)
    expected = sum((value for value in macd_seed if value is not None), Decimal("0")) / Decimal(9)

    assert outputs[32].signal_line is None
    assert outputs[33].signal_line == expected
    assert macd.state.signal_ema.samples == 9


def test_histogram_is_macd_minus_signal() -> None:
    macd = Macd12269()
    output = None
    for close in _closes(34):
        output = macd.update(close)

    assert output is not None
    assert output.macd_line is not None
    assert output.signal_line is not None
    assert output.histogram == output.macd_line - output.signal_line


def test_constant_series_produces_valid_zero_values_when_ready() -> None:
    macd = Macd12269()
    outputs = [macd.update(Decimal("100")) for _ in range(34)]

    assert outputs[25].macd_line == Decimal("0")
    assert outputs[25].signal_line is None
    assert outputs[33].macd_line == Decimal("0")
    assert outputs[33].signal_line == Decimal("0")
    assert outputs[33].histogram == Decimal("0")


def test_recursive_signal_ema_uses_unrounded_previous_value() -> None:
    macd = Macd12269()
    outputs = [macd.update(close) for close in _closes(35)]

    previous_signal = outputs[33].signal_line
    current_macd = outputs[34].macd_line
    assert previous_signal is not None
    assert current_macd is not None

    alpha = Decimal("0.2")
    expected = alpha * current_macd + (Decimal("1") - alpha) * previous_signal
    assert outputs[34].signal_line == expected


def test_checkpoint_restore_before_macd_readiness_is_exact() -> None:
    uninterrupted = Macd12269()
    closes = _closes(45)
    for close in closes[:10]:
        uninterrupted.update(close)

    restored = Macd12269(state=uninterrupted.state)
    expected = [uninterrupted.update(close) for close in closes[10:]]
    actual = [restored.update(close) for close in closes[10:]]

    assert actual == expected
    assert restored.state == uninterrupted.state


def test_checkpoint_restore_during_partial_readiness_is_exact() -> None:
    uninterrupted = Macd12269()
    closes = _closes(45)
    for close in closes[:30]:
        uninterrupted.update(close)

    assert uninterrupted.macd_ready is True
    assert uninterrupted.fully_ready is False

    restored = Macd12269(state=uninterrupted.state)
    expected = [uninterrupted.update(close) for close in closes[30:]]
    actual = [restored.update(close) for close in closes[30:]]

    assert actual == expected
    assert restored.state == uninterrupted.state


def test_checkpoint_restore_after_full_readiness_is_exact() -> None:
    uninterrupted = Macd12269()
    closes = _closes(50)
    for close in closes[:40]:
        uninterrupted.update(close)

    assert uninterrupted.fully_ready is True

    restored = Macd12269(state=uninterrupted.state)
    expected = [uninterrupted.update(close) for close in closes[40:]]
    actual = [restored.update(close) for close in closes[40:]]

    assert actual == expected
    assert restored.state == uninterrupted.state


def test_invalid_input_and_corrupt_state_are_rejected() -> None:
    macd = Macd12269()
    with pytest.raises(TypeError, match="Decimal"):
        macd.update(100.0)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="finite"):
        macd.update(Decimal("NaN"))

    state = macd.state
    with pytest.raises(ValueError, match="sample count"):
        MacdState(
            samples=1,
            fast_ema=state.fast_ema,
            slow_ema=state.slow_ema,
            signal_ema=state.signal_ema,
        )
