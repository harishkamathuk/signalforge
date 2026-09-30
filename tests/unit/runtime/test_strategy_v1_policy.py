from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from signalforge.config.strategy_v1 import StrategyV1EvaluationConfig
from signalforge.domain.armed import ArmedSetup, ExpiryReason
from signalforge.domain.execution import ExecutionMode, Fill
from signalforge.domain.ids import EntryIntentId, InstrumentId, TriggerEventId
from signalforge.domain.market import CandleQuality, CompletedCandle, MarketEvent
from signalforge.domain.money import Price, Quantity
from signalforge.domain.signals import Signal
from signalforge.domain.time import IST, CandleInterval
from signalforge.runtime.strategy import ArmedEventAction, ArmedSetupView
from signalforge.runtime.strategy_v1 import IntradayMomentumV1Strategy

INSTRUMENT = InstrumentId("NSE:TEST")


@dataclass(frozen=True, slots=True)
class _Decision:
    instrument_id: InstrumentId
    interval: CandleInterval
    qualified: bool = True
    actionable: bool = True
    reasons: tuple[str, ...] = ("qualified", "actionable")


def _candle(*, end_hour: int = 10, end_minute: int = 0) -> CompletedCandle:
    end = datetime(2026, 8, 31, end_hour, end_minute, tzinfo=IST)
    return CompletedCandle(
        instrument_id=INSTRUMENT,
        interval=CandleInterval(start=end - timedelta(minutes=5), end=end),
        quality=CandleQuality.VALID,
        open=Price(Decimal("100.00")),
        high=Price(Decimal("101.00")),
        low=Price(Decimal("99.00")),
        close=Price(Decimal("100.11")),
        volume=100,
        source="test",
        source_event_count=4,
    )


def _strategy() -> IntradayMomentumV1Strategy:
    return IntradayMomentumV1Strategy(StrategyV1EvaluationConfig())


def _signal_and_setup(candle: CompletedCandle) -> tuple[Signal, ArmedSetup]:
    strategy = _strategy()
    intent = strategy.arm_intent(candle, _Decision(INSTRUMENT, candle.interval))
    signal = Signal.create(
        instrument_id=INSTRUMENT,
        interval=candle.interval,
        signal_close=candle.close,
        signal_low=candle.low,
        run=_run(),
        created_at=candle.interval.end,
    )
    setup = ArmedSetup(
        signal_id=signal.signal_id,
        raw_trigger=intent.raw_trigger,
        tradable_trigger=Price(Decimal("100.30")),
        signal_low=intent.stop_price,
        armed_at=candle.interval.end,
        valid_until=intent.valid_until,
    )
    return signal, setup


def _setup_view(setup: ArmedSetup) -> ArmedSetupView:
    return ArmedSetupView(
        signal_id=setup.signal_id,
        raw_trigger=setup.raw_trigger,
        tradable_trigger=setup.tradable_trigger,
        stop_price=setup.signal_low,
        armed_at=setup.armed_at,
        valid_until=setup.valid_until,
        state=setup.state,
    )


def _run():
    from signalforge.domain.ids import ConfigId, RunId
    from signalforge.domain.provenance import RunIdentity, StrategyIdentity

    return RunIdentity(
        run_id=RunId("run-v1-policy"),
        strategy=StrategyIdentity("intraday_momentum_v1", "1.0.0"),
        config_id=ConfigId("config-v1-policy"),
        config_hash="hash-v1-policy",
        engine_calculation_version="engine-v1",
    )


def test_v1_arm_intent_preserves_trigger_stop_and_validity() -> None:
    candle = _candle()
    intent = _strategy().arm_intent(candle, _Decision(INSTRUMENT, candle.interval))

    assert intent.raw_trigger == Price(Decimal("100.21011"))
    assert intent.stop_price == Price(Decimal("99.00"))
    assert intent.valid_until == candle.interval.end + timedelta(minutes=5)


def test_v1_armed_market_policy_preserves_ordering_and_low_invalidation() -> None:
    candle = _candle()
    signal, setup = _signal_and_setup(candle)
    strategy = _strategy()
    low_at = setup.armed_at + timedelta(seconds=1)
    low_event = MarketEvent(
        instrument_id=INSTRUMENT,
        exchange_timestamp=low_at,
        received_timestamp=low_at,
        price=Price(Decimal("99.00")),
        quantity=1,
        source="test",
    )

    low_decision = strategy.evaluate_armed_market_event(signal, _setup_view(setup), low_event)

    assert low_decision.action is ArmedEventAction.EXPIRE
    assert low_decision.expiry_reason is ExpiryReason.SIGNAL_LOW_BREACH
    assert low_decision.at == low_at

    cutoff_candle = _candle(end_hour=15, end_minute=0)
    cutoff_signal, cutoff_setup = _signal_and_setup(cutoff_candle)
    cutoff_at = datetime(2026, 8, 31, 15, 5, tzinfo=IST)
    cutoff_event = MarketEvent(
        instrument_id=INSTRUMENT,
        exchange_timestamp=cutoff_at,
        received_timestamp=cutoff_at,
        price=Price(Decimal("200.00")),
        quantity=1,
        source="test",
    )
    cutoff_decision = strategy.evaluate_armed_market_event(
        cutoff_signal,
        _setup_view(cutoff_setup),
        cutoff_event,
    )

    assert cutoff_decision.action is ArmedEventAction.EXPIRE
    assert cutoff_decision.expiry_reason is ExpiryReason.ENTRY_CUTOFF_REACHED
    assert cutoff_decision.at == cutoff_at


def test_v1_post_fill_economics_uses_actual_fill_and_one_point_five_r() -> None:
    candle = _candle()
    signal, setup = _signal_and_setup(candle)
    fill = Fill.create(
        entry_intent_id=EntryIntentId("intent-v1-policy"),
        trigger_event_id=TriggerEventId("trigger-v1-policy"),
        signal_id=signal.signal_id,
        instrument_id=INSTRUMENT,
        reference_price=setup.tradable_trigger,
        fill_price=Price(Decimal("100.50")),
        quantity=Quantity(10),
        execution_mode=ExecutionMode.PAPER,
        filled_at=setup.armed_at + timedelta(seconds=1),
        run=signal.run,
    )

    economics = _strategy().post_fill_economics(
        fill,
        _setup_view(setup),
    )

    assert economics.stop_price == Price(Decimal("99.00"))
    assert economics.raw_target_price == Price(Decimal("102.750"))


def test_v1_post_fill_non_positive_risk_defers_to_generic_rejection() -> None:
    candle = _candle()
    signal, setup = _signal_and_setup(candle)
    fill = Fill.create(
        entry_intent_id=EntryIntentId("intent-v1-zero-risk"),
        trigger_event_id=TriggerEventId("trigger-v1-zero-risk"),
        signal_id=signal.signal_id,
        instrument_id=INSTRUMENT,
        reference_price=setup.tradable_trigger,
        fill_price=setup.signal_low,
        quantity=Quantity(10),
        execution_mode=ExecutionMode.PAPER,
        filled_at=setup.armed_at + timedelta(seconds=1),
        run=signal.run,
    )

    economics = _strategy().post_fill_economics(
        fill,
        _setup_view(setup),
    )

    assert economics.stop_price == setup.signal_low
    assert economics.raw_target_price is None
