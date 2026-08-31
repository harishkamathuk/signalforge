from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from signalforge.domain.execution import ExecutionMode, TriggerEvent
from signalforge.domain.ids import ConfigId, InstrumentId, RunId, SignalId
from signalforge.domain.money import Price, Quantity
from signalforge.domain.provenance import RunIdentity, StrategyIdentity
from signalforge.domain.time import IST
from signalforge.runtime.execution import PaperExecutionPort


def _run() -> RunIdentity:
    return RunIdentity(
        run_id=RunId("run-001"),
        strategy=StrategyIdentity("intraday_momentum_v1", "1.0.0"),
        config_id=ConfigId("config-001"),
        config_hash="abc123",
        engine_calculation_version="engine-v1",
    )


def _trigger(
    *,
    reference: str = "100.10",
    observed: str = "100.10",
) -> TriggerEvent:
    return TriggerEvent.create(
        signal_id=SignalId("signal-001"),
        instrument_id=InstrumentId("NSE:TEST"),
        reference_price=Price(Decimal(reference)),
        observed_price=Price(Decimal(observed)),
        observed_at=datetime(2026, 8, 31, 10, 5, tzinfo=IST),
        run=_run(),
    )


def test_paper_fill_uses_actual_observed_price() -> None:
    trigger = _trigger(reference="100.10", observed="100.15")
    result = PaperExecutionPort().execute(trigger, quantity=Quantity(10))

    assert result.entry_intent.reference_price == Price(Decimal("100.10"))
    assert result.fill.reference_price == Price(Decimal("100.10"))
    assert result.fill.fill_price == Price(Decimal("100.15"))
    assert result.fill.fill_price != result.fill.reference_price
    assert result.fill.execution_mode is ExecutionMode.PAPER


def test_gap_above_trigger_fills_at_observed_gap_price() -> None:
    trigger = _trigger(reference="100.10", observed="101.25")
    result = PaperExecutionPort().execute(trigger, quantity=Quantity(3))

    assert result.fill.fill_price == Price(Decimal("101.25"))
    assert result.fill.fill_price != Price(Decimal("100.10"))


def test_quantity_is_supplied_by_caller_and_preserved() -> None:
    result = PaperExecutionPort().execute(_trigger(), quantity=Quantity(17))

    assert result.entry_intent.quantity == Quantity(17)
    assert result.fill.quantity == Quantity(17)


def test_trigger_evidence_timestamp_drives_intent_and_fill() -> None:
    trigger = _trigger(observed="100.20")
    result = PaperExecutionPort().execute(trigger, quantity=Quantity(2))

    assert result.entry_intent.created_at == trigger.observed_at
    assert result.fill.filled_at == trigger.observed_at


def test_duplicate_execution_request_is_idempotent() -> None:
    trigger = _trigger(observed="100.20")
    port = PaperExecutionPort()

    first = port.execute(trigger, quantity=Quantity(5))
    second = port.execute(trigger, quantity=Quantity(5))

    assert second is first
    assert second.entry_intent.entry_intent_id == first.entry_intent.entry_intent_id
    assert second.fill.fill_id == first.fill.fill_id


def test_same_trigger_with_different_quantity_is_a_distinct_intent() -> None:
    trigger = _trigger(observed="100.20")
    port = PaperExecutionPort()

    first = port.execute(trigger, quantity=Quantity(5))
    second = port.execute(trigger, quantity=Quantity(6))

    assert first.entry_intent.entry_intent_id != second.entry_intent.entry_intent_id
    assert first.fill.fill_id != second.fill.fill_id


def test_execution_is_deterministic_for_identical_inputs() -> None:
    trigger = _trigger(reference="100.10", observed="100.35")

    first = PaperExecutionPort().execute(trigger, quantity=Quantity(4))
    second = PaperExecutionPort().execute(trigger, quantity=Quantity(4))

    assert first == second
