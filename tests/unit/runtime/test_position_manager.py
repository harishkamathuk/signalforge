from datetime import date, datetime, timedelta
from decimal import Decimal

from signalforge.domain.execution import ExecutionMode, Fill
from signalforge.domain.ids import ConfigId, EntryIntentId, InstrumentId, RunId, TriggerEventId
from signalforge.domain.instruments import TickSizeRule, TickSizeSchedule
from signalforge.domain.money import Price, Quantity
from signalforge.domain.provenance import RunIdentity, StrategyIdentity
from signalforge.domain.signals import Signal
from signalforge.domain.time import IST, CandleInterval
from signalforge.runtime.position_manager import PositionManager, PositionOpenRejection

INSTRUMENT = InstrumentId("NSE:TEST")


def _run() -> RunIdentity:
    return RunIdentity(
        run_id=RunId("run-035"),
        strategy=StrategyIdentity("intraday_momentum_v1", "1.0.0"),
        config_id=ConfigId("config-035"),
        config_hash="hash-035",
        engine_calculation_version="engine-v1",
    )


def _signal(*, low: str = "100.00", end_minute: int = 0) -> Signal:
    end = datetime(2026, 8, 31, 10, end_minute, tzinfo=IST)
    return Signal.create(
        instrument_id=INSTRUMENT,
        interval=CandleInterval(start=end - timedelta(minutes=5), end=end),
        signal_close=Price(Decimal("101.00")),
        signal_low=Price(Decimal(low)),
        run=_run(),
        created_at=end,
    )


def _fill(signal: Signal, *, price: str = "101.10", quantity: int = 10) -> Fill:
    return Fill.create(
        entry_intent_id=EntryIntentId("intent-035"),
        trigger_event_id=TriggerEventId("trigger-035"),
        signal_id=signal.signal_id,
        instrument_id=signal.instrument_id,
        reference_price=Price(Decimal("101.05")),
        fill_price=Price(Decimal(price)),
        quantity=Quantity(quantity),
        execution_mode=ExecutionMode.PAPER,
        filled_at=datetime(2026, 8, 31, 10, 1, tzinfo=IST),
        run=signal.run,
    )


def _schedule(*, tick: str = "0.05") -> TickSizeSchedule:
    return TickSizeSchedule(
        instrument_id=INSTRUMENT,
        rules=(
            TickSizeRule(
                tick_size=Price(Decimal(tick)),
                effective_from=date(2026, 1, 1),
            ),
        ),
    )


def test_actual_fill_drives_risk_and_target_and_opens_one_to_one_position() -> None:
    signal = _signal(low="100.00")
    fill = _fill(signal, price="101.10", quantity=7)
    result = PositionManager(tick_schedule=_schedule()).open_from_fill(fill, signal)

    assert result.opened is True
    assert result.rejection is None
    assert result.trade is not None
    assert result.position is not None
    assert result.trade.entry_price == Price(Decimal("101.10"))
    assert result.trade.stop_price == Price(Decimal("100.00"))
    assert result.trade.risk_per_share == Price(Decimal("1.10"))
    assert result.trade.raw_target_price == Price(Decimal("102.750"))
    assert result.trade.tradable_target_price == Price(Decimal("102.75"))
    assert result.trade.quantity == Quantity(7)
    assert result.position.trade_id == result.trade.trade_id
    assert result.position.average_entry_price == fill.fill_price
    assert result.position.quantity == fill.quantity


def test_target_rounds_up_using_effective_tick_schedule() -> None:
    signal = _signal(low="100.00")
    fill = _fill(signal, price="101.11")
    result = PositionManager(tick_schedule=_schedule(tick="0.05")).open_from_fill(fill, signal)

    assert result.trade is not None
    assert result.trade.raw_target_price == Price(Decimal("102.775"))
    assert result.trade.tradable_target_price == Price(Decimal("102.80"))


def test_non_positive_risk_is_explicitly_rejected_without_open_lifecycle() -> None:
    signal = _signal(low="101.10")
    fill = _fill(signal, price="101.10")
    result = PositionManager(tick_schedule=_schedule()).open_from_fill(fill, signal)

    assert result.opened is False
    assert result.trade is None
    assert result.position is None
    assert result.rejection is PositionOpenRejection.NON_POSITIVE_RISK


def test_duplicate_fill_processing_is_idempotent() -> None:
    signal = _signal()
    fill = _fill(signal)
    manager = PositionManager(tick_schedule=_schedule())

    first = manager.open_from_fill(fill, signal)
    second = manager.open_from_fill(fill, signal)

    assert second is first
    assert second.trade is first.trade
    assert second.position is first.position


def test_reference_trigger_price_does_not_drive_trade_economics() -> None:
    signal = _signal(low="100.00")
    fill = _fill(signal, price="101.40")
    result = PositionManager(tick_schedule=_schedule()).open_from_fill(fill, signal)

    assert fill.reference_price == Price(Decimal("101.05"))
    assert result.trade is not None
    assert result.trade.entry_price == Price(Decimal("101.40"))
    assert result.trade.risk_per_share == Price(Decimal("1.40"))
    assert result.trade.raw_target_price == Price(Decimal("103.500"))


def test_fill_and_signal_identity_mismatch_fails_fast() -> None:
    signal = _signal()
    fill = _fill(signal)
    other_signal = _signal(end_minute=5)

    manager = PositionManager(tick_schedule=_schedule())
    try:
        manager.open_from_fill(fill, other_signal)
    except ValueError as exc:
        assert "identities must match" in str(exc)
    else:
        raise AssertionError("expected identity mismatch to fail")
