from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from signalforge.domain.execution import EntryIntent, ExecutionMode, Fill, TriggerEvent
from signalforge.domain.ids import ConfigId, InstrumentId, RunId, SignalId
from signalforge.domain.money import Price, Quantity
from signalforge.domain.provenance import RunIdentity, StrategyIdentity

IST = ZoneInfo("Asia/Kolkata")


def _run() -> RunIdentity:
    return RunIdentity(
        run_id=RunId("run-001"),
        strategy=StrategyIdentity("intraday_momentum_v1", "1.0.0"),
        config_id=ConfigId("config-001"),
        config_hash="abc123",
        engine_calculation_version="engine-v1",
    )


def _trigger() -> TriggerEvent:
    return TriggerEvent.create(
        signal_id=SignalId("signal-001"),
        instrument_id=InstrumentId("NSE:RELIANCE"),
        reference_price=Price(Decimal("1383.15")),
        observed_price=Price(Decimal("1383.20")),
        observed_at=datetime(2026, 8, 28, 10, 7, tzinfo=IST),
        run=_run(),
    )


def _intent(trigger: TriggerEvent) -> EntryIntent:
    return EntryIntent.create(
        trigger_event_id=trigger.trigger_event_id,
        signal_id=trigger.signal_id,
        instrument_id=trigger.instrument_id,
        reference_price=trigger.reference_price,
        quantity=Quantity(10),
        execution_mode=ExecutionMode.PAPER,
        created_at=datetime(2026, 8, 28, 10, 7, 1, tzinfo=IST),
        run=trigger.run,
    )


def test_trigger_event_is_immutable_and_does_not_imply_trade() -> None:
    trigger = _trigger()

    assert trigger.observed_price == Price(Decimal("1383.20"))
    assert "trade_id" not in TriggerEvent.__dataclass_fields__
    assert "position_id" not in TriggerEvent.__dataclass_fields__

    with pytest.raises(FrozenInstanceError):
        trigger.observed_price = Price(Decimal("1384"))  # type: ignore[misc]


def test_trigger_event_requires_observed_price_at_or_above_reference() -> None:
    with pytest.raises(ValueError, match="meet or exceed"):
        TriggerEvent.create(
            signal_id=SignalId("signal-001"),
            instrument_id=InstrumentId("NSE:RELIANCE"),
            reference_price=Price(Decimal("1383.15")),
            observed_price=Price(Decimal("1383.10")),
            observed_at=datetime(2026, 8, 28, 10, 7, tzinfo=IST),
            run=_run(),
        )


def test_trigger_identity_is_deterministic() -> None:
    assert _trigger().trigger_event_id == _trigger().trigger_event_id


def test_entry_intent_is_distinct_immutable_execution_request() -> None:
    trigger = _trigger()
    intent = _intent(trigger)

    assert intent.trigger_event_id == trigger.trigger_event_id
    assert intent.quantity == Quantity(10)
    assert intent.execution_mode is ExecutionMode.PAPER
    assert "fill_price" not in EntryIntent.__dataclass_fields__

    with pytest.raises(FrozenInstanceError):
        intent.quantity = Quantity(20)  # type: ignore[misc]


def test_fill_retains_actual_price_separately_from_reference_price() -> None:
    trigger = _trigger()
    intent = _intent(trigger)
    fill = Fill.create(
        entry_intent_id=intent.entry_intent_id,
        trigger_event_id=trigger.trigger_event_id,
        signal_id=trigger.signal_id,
        instrument_id=trigger.instrument_id,
        reference_price=intent.reference_price,
        fill_price=Price(Decimal("1383.35")),
        quantity=intent.quantity,
        execution_mode=intent.execution_mode,
        filled_at=datetime(2026, 8, 28, 10, 7, 2, tzinfo=IST),
        run=intent.run,
    )

    assert fill.reference_price == Price(Decimal("1383.15"))
    assert fill.fill_price == Price(Decimal("1383.35"))
    assert fill.fill_price != fill.reference_price
    assert fill.quantity == Quantity(10)


def test_fill_identity_changes_with_actual_execution_fact() -> None:
    trigger = _trigger()
    intent = _intent(trigger)
    common = {
        "entry_intent_id": intent.entry_intent_id,
        "trigger_event_id": trigger.trigger_event_id,
        "signal_id": trigger.signal_id,
        "instrument_id": trigger.instrument_id,
        "reference_price": intent.reference_price,
        "quantity": intent.quantity,
        "execution_mode": intent.execution_mode,
        "filled_at": datetime(2026, 8, 28, 10, 7, 2, tzinfo=IST),
        "run": intent.run,
    }
    first = Fill.create(fill_price=Price(Decimal("1383.30")), **common)
    second = Fill.create(fill_price=Price(Decimal("1383.35")), **common)

    assert first.fill_id != second.fill_id


def test_execution_timestamps_must_be_timezone_aware() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        TriggerEvent.create(
            signal_id=SignalId("signal-001"),
            instrument_id=InstrumentId("NSE:RELIANCE"),
            reference_price=Price(Decimal("1383.15")),
            observed_price=Price(Decimal("1383.20")),
            observed_at=datetime(2026, 8, 28, 10, 7),
            run=_run(),
        )


def test_domain_execution_mode_is_broker_independent() -> None:
    assert tuple(ExecutionMode) == (ExecutionMode.PAPER, ExecutionMode.LIVE)
