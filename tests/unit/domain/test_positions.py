from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from signalforge.domain.execution import ExecutionMode, Fill
from signalforge.domain.ids import (
    ConfigId,
    EntryIntentId,
    ExitId,
    InstrumentId,
    RunId,
    SignalId,
    TriggerEventId,
)
from signalforge.domain.money import Price, Quantity
from signalforge.domain.positions import Position, PositionState
from signalforge.domain.provenance import RunIdentity, StrategyIdentity
from signalforge.domain.states import InvalidStateTransition
from signalforge.domain.trades import Trade

IST = ZoneInfo("Asia/Kolkata")


def _run() -> RunIdentity:
    return RunIdentity(
        run_id=RunId("run-001"),
        strategy=StrategyIdentity("intraday_momentum_v1", "1.0.0"),
        config_id=ConfigId("config-001"),
        config_hash="abc123",
        engine_calculation_version="engine-v1",
    )


def _trade() -> Trade:
    fill = Fill.create(
        entry_intent_id=EntryIntentId("intent-001"),
        trigger_event_id=TriggerEventId("trigger-001"),
        signal_id=SignalId("signal-001"),
        instrument_id=InstrumentId("NSE:RELIANCE"),
        reference_price=Price(Decimal("1383.15")),
        fill_price=Price(Decimal("1383.35")),
        quantity=Quantity(10),
        execution_mode=ExecutionMode.PAPER,
        filled_at=datetime(2026, 8, 28, 10, 7, 2, tzinfo=IST),
        run=_run(),
    )
    return Trade.open_from_fill(
        entry_fill=fill,
        stop_price=Price(Decimal("1379.50")),
        target_tick_size=Price(Decimal("0.05")),
    )


def _position() -> Position:
    return Position.open_from_trade(trade=_trade())


def test_position_opens_from_trade_as_distinct_exposure_entity() -> None:
    trade = _trade()
    position = Position.open_from_trade(trade=trade)

    assert position.state is PositionState.OPEN
    assert position.trade_id == trade.trade_id
    assert position.position_id.value != trade.trade_id.value
    assert position.instrument_id == trade.instrument_id
    assert position.quantity == trade.quantity
    assert position.average_entry_price == trade.entry_price
    assert position.opened_at == trade.opened_at


def test_position_identity_is_deterministic_for_one_trade() -> None:
    trade = _trade()

    first = Position.open_from_trade(trade=trade)
    second = Position.open_from_trade(trade=trade)

    assert first.position_id == second.position_id


def test_position_cannot_open_from_closed_trade() -> None:
    trade = _trade()
    trade.close(
        exit_id=ExitId("exit-001"),
        at=datetime(2026, 8, 28, 11, 0, tzinfo=IST),
    )

    with pytest.raises(InvalidStateTransition, match="non-OPEN Trade"):
        Position.open_from_trade(trade=trade)


def test_position_closes_once_and_cannot_reopen_or_reclose() -> None:
    position = _position()
    closed_at = datetime(2026, 8, 28, 11, 0, tzinfo=IST)

    position.close(at=closed_at)

    assert position.state is PositionState.CLOSED
    assert position.closed_at == closed_at

    with pytest.raises(InvalidStateTransition):
        position.close(at=closed_at)

    with pytest.raises(FrozenInstanceError):
        position.state = PositionState.OPEN  # type: ignore[misc]


def test_position_close_timestamp_must_be_aware_and_not_precede_open() -> None:
    position = _position()

    with pytest.raises(ValueError, match="timezone-aware"):
        position.close(at=datetime(2026, 8, 28, 11, 0))

    with pytest.raises(ValueError, match="must not precede"):
        position.close(at=datetime(2026, 8, 28, 10, 0, tzinfo=IST))


def test_position_exposure_fields_are_immutable_and_no_scaling_fields_exist() -> None:
    position = _position()

    with pytest.raises(FrozenInstanceError):
        position.quantity = Quantity(20)  # type: ignore[misc]

    with pytest.raises(FrozenInstanceError):
        position.average_entry_price = Price(Decimal("1384"))  # type: ignore[misc]

    field_names = set(Position.__dataclass_fields__)
    assert "remaining_quantity" not in field_names
    assert "partial_exit_quantity" not in field_names
    assert "scale_count" not in field_names


def test_position_reconstruction_requires_consistent_state_metadata() -> None:
    valid = _position()

    with pytest.raises(ValueError, match="CLOSED Position requires closed_at"):
        Position(
            position_id=valid.position_id,
            trade_id=valid.trade_id,
            instrument_id=valid.instrument_id,
            quantity=valid.quantity,
            average_entry_price=valid.average_entry_price,
            opened_at=valid.opened_at,
            run=valid.run,
            state=PositionState.CLOSED,
        )


def test_position_has_stable_object_identity_while_state_changes() -> None:
    position = _position()
    original_hash = hash(position)

    position.close(at=datetime(2026, 8, 28, 11, 0, tzinfo=IST))

    assert hash(position) == original_hash
