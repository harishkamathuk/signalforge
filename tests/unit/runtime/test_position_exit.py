from datetime import date, datetime, timedelta
from decimal import Decimal

from signalforge.domain.execution import ExecutionMode, Fill
from signalforge.domain.exits import ExitReason
from signalforge.domain.ids import ConfigId, EntryIntentId, InstrumentId, RunId, TriggerEventId
from signalforge.domain.instruments import TickSizeRule, TickSizeSchedule
from signalforge.domain.market import MarketEvent
from signalforge.domain.money import Price, Quantity
from signalforge.domain.positions import PositionState
from signalforge.domain.provenance import RunIdentity, StrategyIdentity
from signalforge.domain.signals import Signal
from signalforge.domain.time import IST, CandleInterval
from signalforge.domain.trades import TradeState
from signalforge.runtime.position_manager import PositionManager

INSTRUMENT = InstrumentId("NSE:TEST")


def _run() -> RunIdentity:
    return RunIdentity(
        run_id=RunId("run-036"),
        strategy=StrategyIdentity("intraday_momentum_v1", "1.0.0"),
        config_id=ConfigId("config-036"),
        config_hash="hash-036",
        engine_calculation_version="engine-v1",
    )


def _schedule() -> TickSizeSchedule:
    return TickSizeSchedule(
        instrument_id=INSTRUMENT,
        rules=(TickSizeRule(Price(Decimal("0.05")), date(2026, 1, 1)),),
    )


def _open_position() -> tuple[PositionManager, object, object]:
    end = datetime(2026, 8, 31, 10, 0, tzinfo=IST)
    signal = Signal.create(
        instrument_id=INSTRUMENT,
        interval=CandleInterval(start=end - timedelta(minutes=5), end=end),
        signal_close=Price(Decimal("101.00")),
        signal_low=Price(Decimal("100.00")),
        run=_run(),
        created_at=end,
    )
    fill = Fill.create(
        entry_intent_id=EntryIntentId("intent-036"),
        trigger_event_id=TriggerEventId("trigger-036"),
        signal_id=signal.signal_id,
        instrument_id=INSTRUMENT,
        reference_price=Price(Decimal("101.05")),
        fill_price=Price(Decimal("101.10")),
        quantity=Quantity(10),
        execution_mode=ExecutionMode.PAPER,
        filled_at=datetime(2026, 8, 31, 10, 1, tzinfo=IST),
        run=_run(),
    )
    manager = PositionManager(tick_schedule=_schedule())
    opened = manager.open_from_fill(fill, signal)
    assert opened.trade is not None and opened.position is not None
    return manager, opened.trade, opened.position


def _event(price: str, *, hour: int = 10, minute: int = 5) -> MarketEvent:
    at = datetime(2026, 8, 31, hour, minute, tzinfo=IST)
    return MarketEvent(
        instrument_id=INSTRUMENT,
        exchange_timestamp=at,
        received_timestamp=at,
        price=Price(Decimal(price)),
        quantity=1,
        source="test",
    )


def test_stop_equality_closes_at_actual_observed_price() -> None:
    manager, trade, position = _open_position()
    exit_fact = manager.process_market_event(trade, position, _event("100.00"))

    assert exit_fact is not None
    assert exit_fact.reason is ExitReason.STOP
    assert exit_fact.reference_price == Price(Decimal("100.00"))
    assert exit_fact.fill_price == Price(Decimal("100.00"))
    assert trade.state is TradeState.CLOSED
    assert position.state is PositionState.CLOSED


def test_stop_gap_through_uses_observed_price_and_actual_realised_values() -> None:
    manager, trade, position = _open_position()
    exit_fact = manager.process_market_event(trade, position, _event("99.50"))

    assert exit_fact is not None
    assert exit_fact.reason is ExitReason.STOP
    assert exit_fact.reference_price == Price(Decimal("100.00"))
    assert exit_fact.fill_price == Price(Decimal("99.50"))
    assert exit_fact.realised_pnl == Decimal("-16.00")
    assert exit_fact.realised_r == Decimal("-1.454545454545454545454545455")


def test_target_equality_and_gap_through_use_actual_observed_price() -> None:
    manager, trade, position = _open_position()
    target = trade.tradable_target_price
    at_target = manager.process_market_event(trade, position, _event(str(target.value)))

    assert at_target is not None
    assert at_target.reason is ExitReason.TARGET
    assert at_target.fill_price == target

    manager2, trade2, position2 = _open_position()
    gap = manager2.process_market_event(trade2, position2, _event("103.20"))
    assert gap is not None
    assert gap.reason is ExitReason.TARGET
    assert gap.reference_price == trade2.tradable_target_price
    assert gap.fill_price == Price(Decimal("103.20"))


def test_non_crossing_event_keeps_position_open() -> None:
    manager, trade, position = _open_position()

    assert manager.process_market_event(trade, position, _event("101.50")) is None
    assert trade.state is TradeState.OPEN
    assert position.state is PositionState.OPEN


def test_first_valid_event_at_1515_forces_exit_even_if_price_is_beyond_target() -> None:
    manager, trade, position = _open_position()
    exit_fact = manager.process_market_event(trade, position, _event("104.00", hour=15, minute=15))

    assert exit_fact is not None
    assert exit_fact.reason is ExitReason.FORCED_SESSION_EXIT
    assert exit_fact.reference_price == Price(Decimal("104.00"))
    assert exit_fact.fill_price == Price(Decimal("104.00"))


def test_pre_1515_cross_uses_stop_or_target_not_forced_exit() -> None:
    manager, trade, position = _open_position()
    exit_fact = manager.process_market_event(trade, position, _event("103.00", hour=15, minute=14))

    assert exit_fact is not None
    assert exit_fact.reason is ExitReason.TARGET


def test_duplicate_event_processing_returns_same_exit_without_double_close() -> None:
    manager, trade, position = _open_position()
    event = _event("99.80")

    first = manager.process_market_event(trade, position, event)
    second = manager.process_market_event(trade, position, event)

    assert first is not None
    assert second is first
    assert trade.state is TradeState.CLOSED
    assert position.state is PositionState.CLOSED


def test_later_event_after_terminal_exit_cannot_replace_first_exit() -> None:
    manager, trade, position = _open_position()
    first = manager.process_market_event(trade, position, _event("99.90"))
    later = manager.process_market_event(trade, position, _event("104.00", minute=6))

    assert later is first
    assert first is not None
    assert first.reason is ExitReason.STOP
    assert first.fill_price == Price(Decimal("99.90"))
