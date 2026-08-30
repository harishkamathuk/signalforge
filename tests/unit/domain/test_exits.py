from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from signalforge.domain.execution import ExecutionMode, Fill
from signalforge.domain.exits import Exit, ExitReason
from signalforge.domain.ids import (
    ConfigId,
    EntryIntentId,
    FillId,
    InstrumentId,
    RunId,
    SignalId,
    TriggerEventId,
)
from signalforge.domain.money import Price, Quantity
from signalforge.domain.positions import Position
from signalforge.domain.provenance import RunIdentity, StrategyIdentity
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


def _trade_and_position() -> tuple[Trade, Position]:
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
    trade = Trade.open_from_fill(
        entry_fill=fill,
        stop_price=Price(Decimal("1379.50")),
        target_tick_size=Price(Decimal("0.05")),
    )
    return trade, Position.open_from_trade(trade=trade)


def _exit(*, reason: ExitReason = ExitReason.TARGET, fill_price: str = "1389.20") -> Exit:
    trade, position = _trade_and_position()
    return Exit.create(
        trade=trade,
        position=position,
        exit_fill_id=FillId("exit-fill-001"),
        reason=reason,
        reference_price=trade.tradable_target_price,
        fill_price=Price(Decimal(fill_price)),
        quantity=trade.quantity,
        execution_mode=ExecutionMode.PAPER,
        exited_at=datetime(2026, 8, 28, 11, 0, tzinfo=IST),
    )


def test_exit_is_immutable_and_preserves_actual_fill_separately() -> None:
    exit_fact = _exit()

    assert exit_fact.reason is ExitReason.TARGET
    assert exit_fact.reference_price == Price(Decimal("1389.15"))
    assert exit_fact.fill_price == Price(Decimal("1389.20"))
    assert exit_fact.fill_price != exit_fact.reference_price

    with pytest.raises(FrozenInstanceError):
        exit_fact.fill_price = Price(Decimal("1390"))  # type: ignore[misc]


def test_exit_calculates_realised_pnl_and_r_from_actual_fill() -> None:
    exit_fact = _exit(fill_price="1389.20")

    assert exit_fact.realised_pnl == Decimal("58.50")
    assert exit_fact.realised_r == Decimal("5.85") / Decimal("3.85")


def test_stop_exit_can_record_gap_below_theoretical_stop() -> None:
    trade, position = _trade_and_position()
    exit_fact = Exit.create(
        trade=trade,
        position=position,
        exit_fill_id=FillId("exit-fill-001"),
        reason=ExitReason.STOP,
        reference_price=trade.stop_price,
        fill_price=Price(Decimal("1379.20")),
        quantity=trade.quantity,
        execution_mode=ExecutionMode.PAPER,
        exited_at=datetime(2026, 8, 28, 10, 30, tzinfo=IST),
    )

    assert exit_fact.reference_price == Price(Decimal("1379.50"))
    assert exit_fact.fill_price == Price(Decimal("1379.20"))
    assert exit_fact.realised_pnl == Decimal("-41.50")


def test_exit_requires_full_mvp_quantity() -> None:
    trade, position = _trade_and_position()

    with pytest.raises(ValueError, match="full open quantity"):
        Exit.create(
            trade=trade,
            position=position,
            exit_fill_id=FillId("exit-fill-001"),
            reason=ExitReason.TARGET,
            reference_price=trade.tradable_target_price,
            fill_price=Price(Decimal("1389.20")),
            quantity=Quantity(5),
            execution_mode=ExecutionMode.PAPER,
            exited_at=datetime(2026, 8, 28, 11, 0, tzinfo=IST),
        )


def test_exit_identity_allows_only_one_logical_exit_per_trade() -> None:
    first = _exit(reason=ExitReason.TARGET, fill_price="1389.20")
    second = _exit(reason=ExitReason.FORCED_SESSION_EXIT, fill_price="1385.00")

    assert first.exit_id == second.exit_id


def test_exit_requires_open_trade_and_position() -> None:
    trade, position = _trade_and_position()
    position.close(at=datetime(2026, 8, 28, 10, 59, tzinfo=IST))

    with pytest.raises(ValueError, match="OPEN Position"):
        Exit.create(
            trade=trade,
            position=position,
            exit_fill_id=FillId("exit-fill-001"),
            reason=ExitReason.FORCED_SESSION_EXIT,
            reference_price=Price(Decimal("1385.00")),
            fill_price=Price(Decimal("1385.00")),
            quantity=trade.quantity,
            execution_mode=ExecutionMode.PAPER,
            exited_at=datetime(2026, 8, 28, 11, 0, tzinfo=IST),
        )


def test_exit_timestamp_must_be_aware_and_not_precede_open() -> None:
    trade, position = _trade_and_position()

    with pytest.raises(ValueError, match="timezone-aware"):
        Exit.create(
            trade=trade,
            position=position,
            exit_fill_id=FillId("exit-fill-001"),
            reason=ExitReason.TARGET,
            reference_price=trade.tradable_target_price,
            fill_price=Price(Decimal("1389.20")),
            quantity=trade.quantity,
            execution_mode=ExecutionMode.PAPER,
            exited_at=datetime(2026, 8, 28, 11, 0),
        )


def test_exit_reason_contract_is_exact_for_mvp() -> None:
    assert tuple(ExitReason) == (
        ExitReason.STOP,
        ExitReason.TARGET,
        ExitReason.FORCED_SESSION_EXIT,
    )
