from datetime import datetime, timedelta
from decimal import Decimal

from signalforge.config.rsi_mean_reversion_v1 import RsiMeanReversionV1Config
from signalforge.config.strategy_v1 import StrategyV1EvaluationConfig
from signalforge.domain.armed import ExpiryReason
from signalforge.domain.execution import ExecutionMode, Fill
from signalforge.domain.ids import EntryIntentId, InstrumentId, RunId, TriggerEventId
from signalforge.domain.market import CandleQuality, CompletedCandle, MarketEvent
from signalforge.domain.money import Price, Quantity
from signalforge.domain.provenance import RunIdentity
from signalforge.domain.signals import Signal
from signalforge.domain.strategy import (
    DecisionReason,
    MomentumResult,
    SetupResult,
    StrategyEvaluation,
    TrendResult,
)
from signalforge.domain.time import IST, CandleInterval
from signalforge.runtime.rsi_mean_reversion_v1 import (
    RsiMeanReversionDecision,
    RsiMeanReversionV1Strategy,
)
from signalforge.runtime.strategy import ArmedEventAction, ArmedSetupView
from signalforge.runtime.strategy_v1 import IntradayMomentumV1Strategy

INSTRUMENT = InstrumentId("NSE:SF066SEM")


def _candle(end: datetime) -> CompletedCandle:
    return CompletedCandle(
        instrument_id=INSTRUMENT,
        interval=CandleInterval(end - timedelta(minutes=5), end),
        quality=CandleQuality.VALID,
        open=Price(Decimal("100")),
        high=Price(Decimal("102")),
        low=Price(Decimal("99")),
        close=Price(Decimal("100.11")),
        volume=100,
        source="sf066-semantic",
        source_event_count=1,
    )


def _v1() -> IntradayMomentumV1Strategy:
    return IntradayMomentumV1Strategy(StrategyV1EvaluationConfig())


def _reference() -> RsiMeanReversionV1Strategy:
    return RsiMeanReversionV1Strategy(RsiMeanReversionV1Config())


def _run(strategy) -> RunIdentity:
    return RunIdentity(
        run_id=RunId(f"sf066-{strategy.identity.strategy_id}"),
        strategy=strategy.identity,
        config_id=strategy.config_identity.config_id,
        config_hash=strategy.config_identity.config_hash,
        engine_calculation_version="engine-v1",
    )


def _signal(strategy, candle: CompletedCandle) -> Signal:
    return Signal.create(
        instrument_id=INSTRUMENT,
        interval=candle.interval,
        signal_close=candle.close,
        signal_low=candle.low,
        run=_run(strategy),
        created_at=candle.interval.end,
    )


def _view(candle: CompletedCandle, raw_trigger: Decimal, tradable_trigger: Decimal) -> ArmedSetupView:
    return ArmedSetupView(
        signal_id=_signal(_v1(), candle).signal_id,
        raw_trigger=Price(raw_trigger),
        tradable_trigger=Price(tradable_trigger),
        stop_price=candle.low,
        armed_at=candle.interval.end,
        valid_until=candle.interval.end + timedelta(minutes=5),
        state="armed",
    )


def _fill(strategy, signal: Signal, view: ArmedSetupView, price: Decimal) -> Fill:
    return Fill.create(
        entry_intent_id=EntryIntentId(f"sf066-intent-{strategy.identity.strategy_id}"),
        trigger_event_id=TriggerEventId(f"sf066-trigger-{strategy.identity.strategy_id}"),
        signal_id=signal.signal_id,
        instrument_id=signal.instrument_id,
        reference_price=view.tradable_trigger,
        fill_price=Price(price),
        quantity=Quantity(10),
        execution_mode=ExecutionMode.PAPER,
        filled_at=view.armed_at + timedelta(seconds=1),
        run=signal.run,
    )


def test_v1_semantic_matrix_remains_exact() -> None:
    strategy = _v1()
    candle = _candle(datetime(2026, 10, 3, 10, 0, tzinfo=IST))
    evaluation = StrategyEvaluation(
        instrument_id=INSTRUMENT,
        interval=candle.interval,
        trend=TrendResult(True),
        momentum=MomentumResult(True, True, True, None),
        setup=SetupResult(True),
        qualified=True,
        actionable=True,
        reasons=(DecisionReason.QUALIFIED, DecisionReason.ACTIONABLE),
    )
    intent = strategy.arm_intent(candle, evaluation)

    assert intent.raw_trigger == Price(Decimal("100.21011"))
    assert intent.stop_price == Price(Decimal("99"))
    assert intent.valid_until == candle.interval.end + timedelta(minutes=5)

    signal = _signal(strategy, candle)
    view = ArmedSetupView(
        signal_id=signal.signal_id,
        raw_trigger=intent.raw_trigger,
        tradable_trigger=Price(Decimal("100.25")),
        stop_price=intent.stop_price,
        armed_at=candle.interval.end,
        valid_until=intent.valid_until,
        state="armed",
    )
    breach_at = view.armed_at + timedelta(seconds=1)
    breach = MarketEvent(
        instrument_id=INSTRUMENT,
        exchange_timestamp=breach_at,
        received_timestamp=breach_at,
        price=view.stop_price,
        quantity=1,
        source="sf066",
    )
    invalidation = strategy.evaluate_armed_market_event(signal, view, breach)
    assert invalidation.action is ArmedEventAction.EXPIRE
    assert invalidation.expiry_reason is ExpiryReason.SIGNAL_LOW_BREACH

    fill = _fill(strategy, signal, view, Decimal("100.50"))
    economics = strategy.post_fill_economics(fill, view)
    assert economics.stop_price == Price(Decimal("99"))
    assert economics.raw_target_price == Price(Decimal("102.75"))


def test_v1_retains_1505_strategy_cutoff() -> None:
    strategy = _v1()
    candle = _candle(datetime(2026, 10, 3, 15, 0, tzinfo=IST))
    signal = _signal(strategy, candle)
    view = ArmedSetupView(
        signal_id=signal.signal_id,
        raw_trigger=Price(Decimal("100")),
        tradable_trigger=Price(Decimal("100")),
        stop_price=Price(Decimal("99")),
        armed_at=candle.interval.end,
        valid_until=datetime(2026, 10, 3, 15, 10, tzinfo=IST),
        state="armed",
    )

    decision = strategy.evaluate_armed_time(
        signal,
        view,
        datetime(2026, 10, 3, 15, 5, tzinfo=IST),
    )

    assert decision.action is ArmedEventAction.EXPIRE
    assert decision.at == datetime(2026, 10, 3, 15, 5, tzinfo=IST)
    assert decision.expiry_reason is ExpiryReason.ENTRY_CUTOFF_REACHED


def test_reference_semantic_matrix_remains_independent_of_v1() -> None:
    strategy = _reference()
    candle = _candle(datetime(2026, 10, 3, 10, 0, tzinfo=IST))
    decision = RsiMeanReversionDecision(
        instrument_id=INSTRUMENT,
        interval=candle.interval,
        qualified=True,
        actionable=True,
        reasons=("rsi_below_threshold",),
        rsi14=Decimal("29.9"),
    )
    intent = strategy.arm_intent(candle, decision)
    assert intent.raw_trigger == candle.close
    assert intent.stop_price == candle.low

    signal = _signal(strategy, candle)
    view = ArmedSetupView(
        signal_id=signal.signal_id,
        raw_trigger=intent.raw_trigger,
        tradable_trigger=Price(Decimal("100.15")),
        stop_price=intent.stop_price,
        armed_at=candle.interval.end,
        valid_until=intent.valid_until,
        state="armed",
    )
    low_at = view.armed_at + timedelta(seconds=1)
    low_event = MarketEvent(
        instrument_id=INSTRUMENT,
        exchange_timestamp=low_at,
        received_timestamp=low_at,
        price=view.stop_price,
        quantity=1,
        source="sf066",
    )
    assert (
        strategy.evaluate_armed_market_event(signal, view, low_event).action
        is ArmedEventAction.NO_ACTION
    )

    fill = _fill(strategy, signal, view, Decimal("100.50"))
    economics = strategy.post_fill_economics(fill, view)
    assert economics.raw_target_price == Price(Decimal("102.00"))
