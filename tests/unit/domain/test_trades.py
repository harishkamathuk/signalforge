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
    FillId,
    InstrumentId,
    RunId,
    SignalId,
    TriggerEventId,
)
from signalforge.domain.money import Price, Quantity
from signalforge.domain.provenance import RunIdentity, StrategyIdentity
from signalforge.domain.states import InvalidStateTransition
from signalforge.domain.trades import Trade, TradeState

IST = ZoneInfo("Asia/Kolkata")


def _run() -> RunIdentity:
    return RunIdentity(
        run_id=RunId("run-001"),
        strategy=StrategyIdentity("intraday_momentum_v1", "1.0.0"),
        config_id=ConfigId("config-001"),
        config_hash="abc123",
        engine_calculation_version="engine-v1",
    )


def _fill(*, fill_price: str = "1383.35", quantity: int = 10) -> Fill:
    return Fill.create(
        entry_intent_id=EntryIntentId("intent-001"),
        trigger_event_id=TriggerEventId("trigger-001"),
        signal_id=SignalId("signal-001"),
        instrument_id=InstrumentId("NSE:RELIANCE"),
        reference_price=Price(Decimal("1383.15")),
        fill_price=Price(Decimal(fill_price)),
        quantity=Quantity(quantity),
        execution_mode=ExecutionMode.PAPER,
        filled_at=datetime(2026, 8, 28, 10, 7, 2, tzinfo=IST),
        run=_run(),
    )


def _trade() -> Trade:
    return Trade.open_from_fill(
        entry_fill=_fill(),
        stop_price=Price(Decimal("1379.50")),
        target_tick_size=Price(Decimal("0.05")),
    )


def test_trade_opens_from_actual_fill_with_frozen_economics() -> None:
    trade = _trade()

    assert trade.state is TradeState.OPEN
    assert trade.entry_price == Price(Decimal("1383.35"))
    assert trade.stop_price == Price(Decimal("1379.50"))
    assert trade.risk_per_share == Price(Decimal("3.85"))
    assert trade.raw_target_price == Price(Decimal("1389.125"))
    assert trade.tradable_target_price == Price(Decimal("1389.15"))
    assert trade.quantity == Quantity(10)

    with pytest.raises(FrozenInstanceError):
        trade.stop_price = Price(Decimal("1380"))  # type: ignore[misc]


def test_trade_risk_uses_actual_fill_not_reference_price() -> None:
    trade = Trade.open_from_fill(
        entry_fill=_fill(fill_price="1383.35"),
        stop_price=Price(Decimal("1380.00")),
        target_tick_size=Price(Decimal("0.05")),
    )

    assert trade.entry_price == Price(Decimal("1383.35"))
    assert trade.risk_per_share == Price(Decimal("3.35"))
    assert trade.raw_target_price == Price(Decimal("1388.375"))
    assert trade.tradable_target_price == Price(Decimal("1388.40"))


def test_trade_rejects_zero_or_negative_risk_before_open() -> None:
    with pytest.raises(ValueError, match="strictly positive before OPEN"):
        Trade.open_from_fill(
            entry_fill=_fill(fill_price="1383.35"),
            stop_price=Price(Decimal("1383.35")),
            target_tick_size=Price(Decimal("0.05")),
        )

    with pytest.raises(ValueError, match="strictly positive before OPEN"):
        Trade.open_from_fill(
            entry_fill=_fill(fill_price="1383.35"),
            stop_price=Price(Decimal("1384.00")),
            target_tick_size=Price(Decimal("0.05")),
        )


def test_trade_identity_is_deterministic_from_run_and_entry_fill() -> None:
    first = _trade()
    second = _trade()

    assert first.trade_id == second.trade_id


def test_trade_closes_once_and_cannot_reopen_or_reclose() -> None:
    trade = _trade()
    exit_id = ExitId("exit-001")
    closed_at = datetime(2026, 8, 28, 11, 0, tzinfo=IST)

    trade.close(exit_id=exit_id, at=closed_at)

    assert trade.state is TradeState.CLOSED
    assert trade.closed_at == closed_at
    assert trade.exit_id == exit_id

    with pytest.raises(InvalidStateTransition):
        trade.close(exit_id=ExitId("exit-002"), at=closed_at)

    with pytest.raises(FrozenInstanceError):
        trade.state = TradeState.OPEN  # type: ignore[misc]


def test_trade_close_timestamp_must_be_timezone_aware_and_not_precede_open() -> None:
    trade = _trade()

    with pytest.raises(ValueError, match="timezone-aware"):
        trade.close(exit_id=ExitId("exit-001"), at=datetime(2026, 8, 28, 11, 0))

    with pytest.raises(ValueError, match="must not precede"):
        trade.close(
            exit_id=ExitId("exit-001"),
            at=datetime(2026, 8, 28, 10, 0, tzinfo=IST),
        )


def test_trade_reconstruction_requires_consistent_economics() -> None:
    valid = _trade()

    with pytest.raises(ValueError, match="risk_per_share must equal"):
        Trade(
            trade_id=valid.trade_id,
            entry_fill_id=valid.entry_fill_id,
            signal_id=valid.signal_id,
            instrument_id=valid.instrument_id,
            entry_price=valid.entry_price,
            stop_price=valid.stop_price,
            raw_target_price=valid.raw_target_price,
            tradable_target_price=valid.tradable_target_price,
            risk_per_share=Price(Decimal("1.00")),
            quantity=valid.quantity,
            opened_at=valid.opened_at,
            run=valid.run,
        )


def test_closed_trade_reconstruction_requires_exit_metadata() -> None:
    valid = _trade()

    with pytest.raises(ValueError, match="CLOSED trade requires"):
        Trade(
            trade_id=valid.trade_id,
            entry_fill_id=valid.entry_fill_id,
            signal_id=valid.signal_id,
            instrument_id=valid.instrument_id,
            entry_price=valid.entry_price,
            stop_price=valid.stop_price,
            raw_target_price=valid.raw_target_price,
            tradable_target_price=valid.tradable_target_price,
            risk_per_share=valid.risk_per_share,
            quantity=valid.quantity,
            opened_at=valid.opened_at,
            run=valid.run,
            state=TradeState.CLOSED,
        )


def test_trade_has_stable_object_identity_while_state_changes() -> None:
    trade = _trade()
    original_hash = hash(trade)

    trade.close(
        exit_id=ExitId("exit-001"),
        at=datetime(2026, 8, 28, 11, 0, tzinfo=IST),
    )

    assert hash(trade) == original_hash


def test_fill_reference_is_retained() -> None:
    fill = _fill()
    trade = Trade.open_from_fill(
        entry_fill=fill,
        stop_price=Price(Decimal("1379.50")),
        target_tick_size=Price(Decimal("0.05")),
    )

    assert trade.entry_fill_id == fill.fill_id
    assert isinstance(trade.entry_fill_id, FillId)
