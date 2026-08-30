"""Tests for SignalForge typed identifiers."""

from dataclasses import FrozenInstanceError

import pytest

from signalforge.domain.ids import (
    ConfigId,
    ExitId,
    FillId,
    InstrumentId,
    PositionId,
    RunId,
    SignalId,
    TradeId,
    TriggerEventId,
    deterministic_id,
)


def test_ids_reject_empty_values() -> None:
    with pytest.raises(ValueError):
        RunId("")

    with pytest.raises(ValueError):
        ConfigId("   ")


def test_ids_are_immutable() -> None:
    signal_id = SignalId("abc")

    with pytest.raises(FrozenInstanceError):
        signal_id.value = "def"  # type: ignore[misc]


def test_deterministic_id_is_stable_for_same_inputs() -> None:
    first = deterministic_id(
        SignalId,
        "strategy",
        "1.0.0",
        "config",
        "instrument",
        "2026-08-30T09:20",
    )
    second = deterministic_id(
        SignalId,
        "strategy",
        "1.0.0",
        "config",
        "instrument",
        "2026-08-30T09:20",
    )

    assert first == second


def test_deterministic_id_changes_when_material_input_changes() -> None:
    base = deterministic_id(SignalId, "strategy", "1.0.0", "config-a", "instrument", "candle")
    changed = deterministic_id(SignalId, "strategy", "1.0.0", "config-b", "instrument", "candle")

    assert base != changed


def test_deterministic_id_is_namespaced_by_id_type() -> None:
    signal = deterministic_id(SignalId, "same", "parts")
    trade = deterministic_id(TradeId, "same", "parts")

    assert signal.value != trade.value


def test_deterministic_id_rejects_missing_or_blank_components() -> None:
    with pytest.raises(ValueError):
        deterministic_id(SignalId)

    with pytest.raises(ValueError):
        deterministic_id(SignalId, "valid", " ")


def test_all_initial_id_types_can_be_constructed() -> None:
    id_types = (
        RunId,
        ConfigId,
        SignalId,
        TriggerEventId,
        FillId,
        TradeId,
        PositionId,
        ExitId,
        InstrumentId,
    )

    assert all(str(id_type("value")) == "value" for id_type in id_types)
