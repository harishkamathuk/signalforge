from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from signalforge.domain.execution import ExecutionMode, Fill, TriggerEvent
from signalforge.domain.ids import (
    ConfigId,
    EntryIntentId,
    FillId,
    InstrumentId,
    RunId,
    SignalId,
    TriggerEventId,
)
from signalforge.domain.instruments import TickSizeRule, TickSizeSchedule
from signalforge.domain.market import MarketEvent
from signalforge.domain.money import Price, Quantity
from signalforge.domain.positions import Position
from signalforge.domain.provenance import RunIdentity, StrategyIdentity
from signalforge.domain.signals import Signal
from signalforge.domain.time import IST, CandleInterval
from signalforge.domain.trades import Trade
from signalforge.runtime.position_manager import PositionManager

INSTRUMENT = InstrumentId("NSE:TEST")


def _run() -> RunIdentity:
    return RunIdentity(
        run_id=RunId("run-canonical"),
        strategy=StrategyIdentity("intraday_momentum_v1", "1.0.0"),
        config_id=ConfigId("config-canonical"),
        config_hash="hash-canonical",
        engine_calculation_version="engine-v1",
    )


def test_signal_identity_canonicalizes_equivalent_interval_instants() -> None:
    ist_start = datetime(2026, 8, 31, 10, 0, tzinfo=IST)
    utc_start = datetime(2026, 8, 31, 4, 30, tzinfo=UTC)

    def create(start: datetime) -> Signal:
        interval = CandleInterval.five_minutes(start)
        return Signal.create(
            instrument_id=INSTRUMENT,
            interval=interval,
            signal_close=Price(Decimal("156.5")),
            signal_low=Price(Decimal("155")),
            run=_run(),
            created_at=interval.end,
        )

    first = create(ist_start)
    timezone_variant = create(utc_start)
    repeated = create(ist_start)
    assert {first.signal_id, timezone_variant.signal_id, repeated.signal_id} == {first.signal_id}


def test_trigger_identity_canonicalizes_timestamp_and_decimal_components() -> None:
    common = {
        "signal_id": SignalId("signal-canonical"),
        "instrument_id": INSTRUMENT,
        "reference_price": Price(Decimal("156")),
        "run": _run(),
    }
    first = TriggerEvent.create(
        observed_price=Price(Decimal("156.5")),
        observed_at=datetime(2026, 8, 31, 10, 0, tzinfo=IST),
        **common,
    )
    timestamp_variant = TriggerEvent.create(
        observed_price=Price(Decimal("156.5")),
        observed_at=datetime(2026, 8, 31, 4, 30, tzinfo=UTC),
        **common,
    )
    decimal_variant = TriggerEvent.create(
        observed_price=Price(Decimal("156.5000")),
        observed_at=datetime(2026, 8, 31, 10, 0, tzinfo=IST),
        **common,
    )

    repeated = TriggerEvent.create(
        observed_price=Price(Decimal("156.5")),
        observed_at=datetime(2026, 8, 31, 10, 0, tzinfo=IST),
        **common,
    )

    assert {
        first.trigger_event_id,
        timestamp_variant.trigger_event_id,
        decimal_variant.trigger_event_id,
        repeated.trigger_event_id,
    } == {first.trigger_event_id}


def test_fill_identity_canonicalizes_timestamp_and_decimal_components() -> None:
    common = {
        "entry_intent_id": EntryIntentId("intent-canonical"),
        "trigger_event_id": TriggerEvent.create(
            signal_id=SignalId("signal-canonical"),
            instrument_id=INSTRUMENT,
            reference_price=Price(Decimal("156")),
            observed_price=Price(Decimal("156.5")),
            observed_at=datetime(2026, 8, 31, 10, 0, tzinfo=IST),
            run=_run(),
        ).trigger_event_id,
        "signal_id": SignalId("signal-canonical"),
        "instrument_id": INSTRUMENT,
        "reference_price": Price(Decimal("156")),
        "quantity": Quantity(10),
        "execution_mode": ExecutionMode.PAPER,
        "run": _run(),
    }
    first = Fill.create(
        fill_price=Price(Decimal("156.5")),
        filled_at=datetime(2026, 8, 31, 10, 0, tzinfo=IST),
        **common,
    )
    timestamp_variant = Fill.create(
        fill_price=Price(Decimal("156.5")),
        filled_at=datetime(2026, 8, 31, 4, 30, tzinfo=UTC),
        **common,
    )
    decimal_variant = Fill.create(
        fill_price=Price(Decimal("156.5000")),
        filled_at=datetime(2026, 8, 31, 10, 0, tzinfo=IST),
        **common,
    )

    repeated = Fill.create(
        fill_price=Price(Decimal("156.5")),
        filled_at=datetime(2026, 8, 31, 10, 0, tzinfo=IST),
        **common,
    )

    assert {
        first.fill_id,
        timestamp_variant.fill_id,
        decimal_variant.fill_id,
        repeated.fill_id,
    } == {first.fill_id}


def _open_position() -> tuple[PositionManager, Trade, Position]:
    end = datetime(2026, 8, 31, 10, 0, tzinfo=IST)
    signal = Signal.create(
        instrument_id=INSTRUMENT,
        interval=CandleInterval(start=end - timedelta(minutes=5), end=end),
        signal_close=Price(Decimal("101")),
        signal_low=Price(Decimal("100")),
        run=_run(),
        created_at=end,
    )
    fill = Fill.create(
        entry_intent_id=EntryIntentId("intent-exit-canonical"),
        trigger_event_id=TriggerEvent.create(
            signal_id=signal.signal_id,
            instrument_id=INSTRUMENT,
            reference_price=Price(Decimal("101")),
            observed_price=Price(Decimal("101.1")),
            observed_at=end + timedelta(minutes=1),
            run=_run(),
        ).trigger_event_id,
        signal_id=signal.signal_id,
        instrument_id=INSTRUMENT,
        reference_price=Price(Decimal("101")),
        fill_price=Price(Decimal("101.1")),
        quantity=Quantity(10),
        execution_mode=ExecutionMode.PAPER,
        filled_at=end + timedelta(minutes=1),
        run=_run(),
    )
    schedule = TickSizeSchedule(
        instrument_id=INSTRUMENT,
        rules=(TickSizeRule(Price(Decimal("0.05")), date(2026, 1, 1)),),
    )
    manager = PositionManager(tick_schedule=schedule)
    opened = manager.open_from_fill(fill, signal)
    assert opened.trade is not None and opened.position is not None
    return manager, opened.trade, opened.position


def test_exit_fill_identity_canonicalizes_timestamp_and_decimal_components() -> None:
    def exit_fill_id(at: datetime, price: str) -> FillId:
        manager, trade, position = _open_position()
        event = MarketEvent(
            instrument_id=INSTRUMENT,
            exchange_timestamp=at,
            received_timestamp=at,
            price=Price(Decimal(price)),
            quantity=1,
            source="canonical-test",
        )
        result = manager.process_market_event(trade, position, event)
        assert result is not None
        return result.exit_fill_id

    first = exit_fill_id(datetime(2026, 8, 31, 10, 5, tzinfo=IST), "99.5")
    timezone_variant = exit_fill_id(datetime(2026, 8, 31, 4, 35, tzinfo=UTC), "99.5")
    decimal_variant = exit_fill_id(datetime(2026, 8, 31, 10, 5, tzinfo=IST), "99.5000")
    repeated = exit_fill_id(datetime(2026, 8, 31, 10, 5, tzinfo=IST), "99.5")

    assert {first, timezone_variant, decimal_variant, repeated} == {first}


@pytest.mark.parametrize("zero", ["0", "-0.000"])
def test_signed_zero_is_rejected_by_positive_price_domain_paths(zero: str) -> None:
    at = datetime(2026, 8, 31, 10, 0, tzinfo=IST)
    with pytest.raises(ValueError, match="strictly positive"):
        TriggerEvent.create(
            signal_id=SignalId("signal-zero"),
            instrument_id=INSTRUMENT,
            reference_price=Price(Decimal("1")),
            observed_price=Price(Decimal(zero)),
            observed_at=at,
            run=_run(),
        )
    with pytest.raises(ValueError, match="strictly positive"):
        Fill.create(
            entry_intent_id=EntryIntentId("intent-zero"),
            trigger_event_id=TriggerEventId("trigger-zero"),
            signal_id=SignalId("signal-zero"),
            instrument_id=INSTRUMENT,
            reference_price=Price(Decimal("1")),
            fill_price=Price(Decimal(zero)),
            quantity=Quantity(1),
            execution_mode=ExecutionMode.PAPER,
            filled_at=at,
            run=_run(),
        )
    with pytest.raises(ValueError, match="strictly positive"):
        MarketEvent(
            instrument_id=INSTRUMENT,
            exchange_timestamp=at,
            received_timestamp=at,
            price=Price(Decimal(zero)),
            quantity=1,
            source="canonical-test",
        )
