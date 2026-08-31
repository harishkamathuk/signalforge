from datetime import datetime, timedelta
from decimal import Decimal

from signalforge.config.strategy_v1 import StrategyV1EvaluationConfig
from signalforge.domain.ids import InstrumentId
from signalforge.domain.indicators import IndicatorSnapshot
from signalforge.domain.market import CandleQuality, CompletedCandle
from signalforge.domain.money import Price
from signalforge.domain.strategy import DecisionReason
from signalforge.domain.time import IST, CandleInterval
from signalforge.runtime.eligibility import EvaluationGuardReason, MarketDataFeedState
from signalforge.runtime.indicators import IndicatorContinuity
from signalforge.runtime.strategy_evaluator import (
    StrategyEvaluationContext,
    StrategyEvaluator,
)

INSTRUMENT = InstrumentId("NSE:TEST")


def _interval(*, end_hour: int = 10, end_minute: int = 0) -> CandleInterval:
    end = datetime(2026, 8, 31, end_hour, end_minute, tzinfo=IST)
    return CandleInterval(start=end - timedelta(minutes=5), end=end)


def _candle(*, close: str = "101", interval: CandleInterval | None = None) -> CompletedCandle:
    interval = interval or _interval()
    return CompletedCandle(
        instrument_id=INSTRUMENT,
        interval=interval,
        quality=CandleQuality.VALID,
        open=Price(Decimal("100")),
        high=Price(Decimal("102")),
        low=Price(Decimal("99")),
        close=Price(Decimal(close)),
        volume=100,
        source="test",
        source_event_count=4,
    )


def _snapshot(
    *,
    interval: CandleInterval | None = None,
    ema9: str = "100",
    ema20: str = "101",
    ema50: str = "100",
    rsi14: str = "60",
    adx14: str = "23",
    macd_signal: str | None = "1",
) -> IndicatorSnapshot:
    interval = interval or _interval()
    signal = Decimal(macd_signal) if macd_signal is not None else None
    return IndicatorSnapshot(
        instrument_id=INSTRUMENT,
        interval=interval,
        ready=True,
        calculation_version="test",
        ema9=Decimal(ema9),
        ema20=Decimal(ema20),
        ema50=Decimal(ema50),
        rsi14=Decimal(rsi14),
        adx14=Decimal(adx14),
        macd_line=Decimal("2"),
        macd_signal=signal,
        macd_histogram=Decimal("1") if signal is not None else None,
    )


def _context(
    *,
    warmup: int = 250,
    feed_state: MarketDataFeedState | None = MarketDataFeedState.HEALTHY,
) -> StrategyEvaluationContext:
    return StrategyEvaluationContext(
        completed_regular_session_candles=warmup,
        continuity=IndicatorContinuity.HEALTHY,
        feed_state=feed_state,
    )


def test_all_components_pass_and_guard_actionable() -> None:
    evaluator = StrategyEvaluator(StrategyV1EvaluationConfig())
    result = evaluator.evaluate(_candle(), _snapshot(), _context())

    assert result.evaluation.qualified is True
    assert result.evaluation.actionable is True
    assert result.evaluation.reasons == (
        DecisionReason.QUALIFIED,
        DecisionReason.ACTIONABLE,
    )
    assert result.guard.reasons == ()


def test_qualified_but_outside_signal_window_is_not_actionable() -> None:
    interval = _interval(end_hour=15, end_minute=5)
    evaluator = StrategyEvaluator(StrategyV1EvaluationConfig())
    result = evaluator.evaluate(
        _candle(interval=interval),
        _snapshot(interval=interval),
        _context(),
    )

    assert result.evaluation.qualified is True
    assert result.evaluation.actionable is False
    assert result.evaluation.reasons == (
        DecisionReason.QUALIFIED,
        DecisionReason.QUALIFIED_NOT_ACTIONABLE,
    )
    assert result.guard.reasons == (EvaluationGuardReason.OUTSIDE_SIGNAL_WINDOW,)


def test_qualified_but_stale_feed_is_not_actionable() -> None:
    evaluator = StrategyEvaluator(StrategyV1EvaluationConfig())
    result = evaluator.evaluate(
        _candle(),
        _snapshot(),
        _context(feed_state=MarketDataFeedState.STALE),
    )

    assert result.evaluation.qualified is True
    assert result.evaluation.actionable is False
    assert result.guard.reasons == (EvaluationGuardReason.FEED_NOT_HEALTHY,)


def test_trend_failure_reason_is_preserved() -> None:
    evaluator = StrategyEvaluator(StrategyV1EvaluationConfig())
    result = evaluator.evaluate(_candle(), _snapshot(ema20="100", ema50="100"), _context())

    assert result.evaluation.qualified is False
    assert result.evaluation.actionable is False
    assert result.evaluation.reasons == (DecisionReason.TREND_NOT_MET,)


def test_momentum_failure_reason_is_preserved() -> None:
    evaluator = StrategyEvaluator(StrategyV1EvaluationConfig())
    result = evaluator.evaluate(_candle(), _snapshot(rsi14="57.9"), _context())

    assert result.evaluation.reasons == (DecisionReason.MOMENTUM_NOT_MET,)


def test_setup_failure_reason_is_preserved() -> None:
    evaluator = StrategyEvaluator(StrategyV1EvaluationConfig())
    result = evaluator.evaluate(_candle(close="100"), _snapshot(ema9="100"), _context())

    assert result.evaluation.reasons == (DecisionReason.SETUP_NOT_MET,)


def test_multiple_failure_reasons_have_deterministic_domain_order() -> None:
    evaluator = StrategyEvaluator(StrategyV1EvaluationConfig())
    result = evaluator.evaluate(
        _candle(close="100"),
        _snapshot(ema9="100", ema20="99", ema50="100", rsi14="57"),
        _context(),
    )

    assert result.evaluation.reasons == (
        DecisionReason.TREND_NOT_MET,
        DecisionReason.MOMENTUM_NOT_MET,
        DecisionReason.SETUP_NOT_MET,
    )


def test_macd_diagnostic_never_changes_qualification_or_actionability() -> None:
    evaluator = StrategyEvaluator(StrategyV1EvaluationConfig())

    positive = evaluator.evaluate(_candle(), _snapshot(macd_signal="1"), _context())
    negative = evaluator.evaluate(_candle(), _snapshot(macd_signal="-1"), _context())

    assert positive.evaluation.qualified is True
    assert negative.evaluation.qualified is True
    assert positive.evaluation.actionable is True
    assert negative.evaluation.actionable is True
    assert positive.evaluation.momentum.macd_signal_positive is True
    assert negative.evaluation.momentum.macd_signal_positive is False


def test_identical_inputs_produce_identical_output() -> None:
    evaluator = StrategyEvaluator(StrategyV1EvaluationConfig())
    candle = _candle()
    snapshot = _snapshot()
    context = _context()

    assert evaluator.evaluate(candle, snapshot, context) == evaluator.evaluate(
        candle, snapshot, context
    )


def test_insufficient_warmup_retains_qualification_but_blocks_actionability() -> None:
    evaluator = StrategyEvaluator(StrategyV1EvaluationConfig())
    result = evaluator.evaluate(_candle(), _snapshot(), _context(warmup=249))

    assert result.evaluation.qualified is True
    assert result.evaluation.actionable is False
    assert result.evaluation.reasons == (
        DecisionReason.QUALIFIED,
        DecisionReason.QUALIFIED_NOT_ACTIONABLE,
    )
    assert result.guard.reasons == (EvaluationGuardReason.INSUFFICIENT_WARMUP,)
