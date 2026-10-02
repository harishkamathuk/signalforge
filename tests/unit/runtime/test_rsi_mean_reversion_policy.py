from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from signalforge.config.rsi_mean_reversion_v1 import RsiMeanReversionV1Config
from signalforge.domain.armed import ArmedSetup, ExpiryReason
from signalforge.domain.execution import ExecutionMode, Fill
from signalforge.domain.ids import (
    EntryIntentId,
    InstrumentId,
    RunId,
    TriggerEventId,
)
from signalforge.domain.indicators import IndicatorReading, IndicatorSnapshot, RsiRequirement
from signalforge.domain.market import CandleQuality, CompletedCandle, MarketEvent
from signalforge.domain.money import Price, Quantity
from signalforge.domain.provenance import RunIdentity
from signalforge.domain.signals import Signal
from signalforge.domain.time import IST, CandleInterval
from signalforge.runtime.indicators import IndicatorContinuity
from signalforge.runtime.rsi_mean_reversion_v1 import (
    RsiMeanReversionDecision,
    RsiMeanReversionV1Strategy,
)
from signalforge.runtime.strategy import (
    ArmedEventAction,
    ArmedSetupView,
    CompletedCandleStrategyContext,
)

INSTRUMENT = InstrumentId("NSE:TEST")


def _strategy() -> RsiMeanReversionV1Strategy:
    return RsiMeanReversionV1Strategy(RsiMeanReversionV1Config())


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


def _snapshot(candle: CompletedCandle, rsi: Decimal | None) -> IndicatorSnapshot:
    return IndicatorSnapshot(
        instrument_id=INSTRUMENT,
        interval=candle.interval,
        calculation_version="engine-v1",
        readings=(IndicatorReading(RsiRequirement(14), rsi),),
    )


def _context(candle: CompletedCandle, rsi: Decimal | None) -> CompletedCandleStrategyContext:
    return CompletedCandleStrategyContext(
        candle=candle,
        indicators=_snapshot(candle, rsi),
        completed_regular_session_candles=20,
        continuity=IndicatorContinuity.HEALTHY,
    )


def _run() -> RunIdentity:
    strategy = _strategy()
    identity = strategy.config_identity
    return RunIdentity(
        run_id=RunId("run-rsi-reference"),
        strategy=strategy.identity,
        config_id=identity.config_id,
        config_hash=identity.config_hash,
        engine_calculation_version="engine-v1",
    )


def _signal_and_setup(candle: CompletedCandle) -> tuple[Signal, ArmedSetup]:
    strategy = _strategy()
    decision = strategy.evaluate_completed_candle(_context(candle, Decimal("29")))
    intent = strategy.arm_intent(candle, decision)
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
        tradable_trigger=Price(Decimal("100.20")),
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


@pytest.mark.parametrize(
    ("rsi", "qualified", "reason"),
    (
        (None, False, "rsi_unavailable"),
        (Decimal("30"), False, "rsi_not_below_threshold"),
        (Decimal("31"), False, "rsi_not_below_threshold"),
        (Decimal("29.999"), True, "rsi_below_threshold"),
    ),
)
def test_reference_rsi_boundary_semantics(
    rsi: Decimal | None,
    qualified: bool,
    reason: str,
) -> None:
    decision = _strategy().evaluate_completed_candle(_context(_candle(), rsi))

    assert decision.qualified is qualified
    assert decision.actionable is qualified
    assert decision.reasons == (reason,)
    assert decision.rsi14 == rsi


def test_reference_declares_only_rsi14() -> None:
    requirements = _strategy().indicator_requirements

    assert requirements.items == (RsiRequirement(14),)
    assert requirements.keys == ("rsi:14",)


def test_reference_decision_is_immutable_and_enforces_actionable_invariant() -> None:
    candle = _candle()
    decision = _strategy().evaluate_completed_candle(_context(candle, Decimal("29")))

    with pytest.raises(FrozenInstanceError):
        decision.qualified = False

    with pytest.raises(ValueError, match="must be qualified"):
        RsiMeanReversionDecision(
            INSTRUMENT,
            candle.interval,
            qualified=False,
            actionable=True,
            reasons=("invalid",),
            rsi14=Decimal("29"),
        )


def test_reference_arm_intent_is_signal_close_low_and_one_candle() -> None:
    candle = _candle()
    strategy = _strategy()
    decision = strategy.evaluate_completed_candle(_context(candle, Decimal("29")))

    intent = strategy.arm_intent(candle, decision)

    assert intent.raw_trigger == candle.close
    assert intent.stop_price == candle.low
    assert intent.valid_until == candle.interval.end + timedelta(minutes=5)


def test_reference_arm_intent_rejects_non_actionable_decision() -> None:
    candle = _candle()
    strategy = _strategy()
    decision = strategy.evaluate_completed_candle(_context(candle, Decimal("30")))

    with pytest.raises(ValueError, match="requires an actionable decision"):
        strategy.arm_intent(candle, decision)


def test_reference_market_policy_trigger_equality_and_no_low_invalidation() -> None:
    candle = _candle()
    signal, setup = _signal_and_setup(candle)
    strategy = _strategy()
    view = _setup_view(setup)

    low_at = setup.armed_at + timedelta(seconds=1)
    low_event = MarketEvent(
        instrument_id=INSTRUMENT,
        exchange_timestamp=low_at,
        received_timestamp=low_at,
        price=setup.signal_low,
        quantity=1,
        source="test",
    )
    assert strategy.evaluate_armed_market_event(signal, view, low_event).action is (
        ArmedEventAction.NO_ACTION
    )

    trigger_at = setup.armed_at + timedelta(seconds=2)
    trigger_event = MarketEvent(
        instrument_id=INSTRUMENT,
        exchange_timestamp=trigger_at,
        received_timestamp=trigger_at,
        price=setup.tradable_trigger,
        quantity=1,
        source="test",
    )
    decision = strategy.evaluate_armed_market_event(signal, view, trigger_event)

    assert decision.action is ArmedEventAction.TRIGGER
    assert decision.at == trigger_at


def test_reference_market_policy_expires_before_trigger_at_validity_boundary() -> None:
    candle = _candle()
    signal, setup = _signal_and_setup(candle)
    event = MarketEvent(
        instrument_id=INSTRUMENT,
        exchange_timestamp=setup.valid_until,
        received_timestamp=setup.valid_until,
        price=Price(Decimal("200")),
        quantity=1,
        source="test",
    )

    decision = _strategy().evaluate_armed_market_event(signal, _setup_view(setup), event)

    assert decision.action is ArmedEventAction.EXPIRE
    assert decision.at == setup.valid_until
    assert decision.expiry_reason is ExpiryReason.VALIDITY_WINDOW_END


def test_reference_completed_candle_and_time_expire_at_validity_end() -> None:
    signal_candle = _candle()
    signal, setup = _signal_and_setup(signal_candle)
    following = CompletedCandle(
        instrument_id=INSTRUMENT,
        interval=CandleInterval(start=setup.armed_at, end=setup.valid_until),
        quality=CandleQuality.VALID,
        open=Price(Decimal("100")),
        high=Price(Decimal("101")),
        low=Price(Decimal("98")),
        close=Price(Decimal("99")),
        volume=100,
        source="test",
        source_event_count=2,
    )
    strategy = _strategy()

    completed = strategy.evaluate_armed_completed_candle(
        signal,
        _setup_view(setup),
        following,
    )
    timed = strategy.evaluate_armed_time(
        signal,
        _setup_view(setup),
        setup.valid_until,
    )

    assert completed.action is ArmedEventAction.EXPIRE
    assert completed.at == setup.valid_until
    assert completed.expiry_reason is ExpiryReason.VALIDITY_WINDOW_END
    assert timed == completed


def test_reference_post_fill_economics_uses_actual_fill_and_one_r() -> None:
    candle = _candle()
    signal, setup = _signal_and_setup(candle)
    fill = Fill.create(
        entry_intent_id=EntryIntentId("intent-rsi-reference"),
        trigger_event_id=TriggerEventId("trigger-rsi-reference"),
        signal_id=signal.signal_id,
        instrument_id=INSTRUMENT,
        reference_price=setup.tradable_trigger,
        fill_price=Price(Decimal("100.50")),
        quantity=Quantity(10),
        execution_mode=ExecutionMode.PAPER,
        filled_at=setup.armed_at + timedelta(seconds=1),
        run=signal.run,
    )

    economics = _strategy().post_fill_economics(fill, _setup_view(setup))

    assert economics.stop_price == Price(Decimal("99.00"))
    assert economics.raw_target_price == Price(Decimal("102.00"))


def test_reference_post_fill_non_positive_risk_defers_to_generic_rejection() -> None:
    candle = _candle()
    signal, setup = _signal_and_setup(candle)
    fill = Fill.create(
        entry_intent_id=EntryIntentId("intent-rsi-zero-risk"),
        trigger_event_id=TriggerEventId("trigger-rsi-zero-risk"),
        signal_id=signal.signal_id,
        instrument_id=INSTRUMENT,
        reference_price=setup.tradable_trigger,
        fill_price=setup.signal_low,
        quantity=Quantity(10),
        execution_mode=ExecutionMode.PAPER,
        filled_at=setup.armed_at + timedelta(seconds=1),
        run=signal.run,
    )

    economics = _strategy().post_fill_economics(fill, _setup_view(setup))

    assert economics.stop_price == setup.signal_low
    assert economics.raw_target_price is None
