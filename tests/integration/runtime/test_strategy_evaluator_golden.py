from dataclasses import asdict
from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from signalforge.config.strategy_v1 import StrategyV1EvaluationConfig
from signalforge.domain.ids import InstrumentId
from signalforge.domain.indicators import IndicatorSnapshot
from signalforge.domain.market import CandleQuality, CompletedCandle
from signalforge.domain.money import Price
from signalforge.domain.strategy import DecisionReason, StrategyEvaluation
from signalforge.domain.time import IST, CandleInterval
from signalforge.runtime.eligibility import EvaluationGuardReason, MarketDataFeedState
from signalforge.runtime.indicators import IndicatorContinuity
from signalforge.runtime.strategy_evaluator import (
    StrategyEvaluationContext,
    StrategyEvaluator,
    StrategyEvaluatorResult,
)

INSTRUMENT = InstrumentId("NSE:GOLDEN")
CONFIG = StrategyV1EvaluationConfig()
EVALUATOR = StrategyEvaluator(CONFIG)


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
        volume=1000,
        source="golden",
        source_event_count=10,
    )


def _snapshot(
    *,
    interval: CandleInterval | None = None,
    ready: bool = True,
    ema9: str | None = "100",
    ema20: str | None = "101",
    ema50: str | None = "100",
    rsi14: str | None = "60",
    adx14: str | None = "23",
    macd_signal: str | None = "1",
) -> IndicatorSnapshot:
    interval = interval or _interval()

    def dec(value: str | None) -> Decimal | None:
        return Decimal(value) if value is not None else None

    signal = dec(macd_signal)
    return IndicatorSnapshot(
        instrument_id=INSTRUMENT,
        interval=interval,
        ready=ready,
        calculation_version="golden-v1",
        ema9=dec(ema9),
        ema20=dec(ema20),
        ema50=dec(ema50),
        rsi14=dec(rsi14),
        adx14=dec(adx14),
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


def _evaluate(
    *,
    candle: CompletedCandle | None = None,
    snapshot: IndicatorSnapshot | None = None,
    context: StrategyEvaluationContext | None = None,
) -> StrategyEvaluatorResult:
    candle = candle or _candle()
    snapshot = snapshot or _snapshot(interval=candle.interval)
    return EVALUATOR.evaluate(candle, snapshot, context or _context())


def test_positive_golden_vector_is_exact() -> None:
    result = _evaluate()

    assert result.evaluation == StrategyEvaluation(
        instrument_id=INSTRUMENT,
        interval=_interval(),
        trend=result.evaluation.trend,
        momentum=result.evaluation.momentum,
        setup=result.evaluation.setup,
        qualified=True,
        actionable=True,
        reasons=(DecisionReason.QUALIFIED, DecisionReason.ACTIONABLE),
    )
    assert result.evaluation.trend.passed is True
    assert result.evaluation.momentum.passed is True
    assert result.evaluation.momentum.rsi_passed is True
    assert result.evaluation.momentum.adx_passed is True
    assert result.evaluation.setup.passed is True
    assert result.guard.reasons == ()


@pytest.mark.parametrize(
    ("ema20", "ema50", "expected"),
    [("100.0001", "100", True), ("100", "100", False), ("99.9999", "100", False)],
)
def test_trend_strict_boundary_golden(ema20: str, ema50: str, expected: bool) -> None:
    result = _evaluate(snapshot=_snapshot(ema20=ema20, ema50=ema50))

    assert result.evaluation.trend.passed is expected
    assert result.evaluation.qualified is expected


@pytest.mark.parametrize(
    ("close", "ema9", "expected"),
    [("100.0001", "100", True), ("100", "100", False), ("99.9999", "100", False)],
)
def test_setup_strict_boundary_golden(close: str, ema9: str, expected: bool) -> None:
    result = _evaluate(candle=_candle(close=close), snapshot=_snapshot(ema9=ema9))

    assert result.evaluation.setup.passed is expected
    assert result.evaluation.qualified is expected


@pytest.mark.parametrize(
    ("rsi", "expected"),
    [("57.9999", False), ("58", True), ("65", True), ("65.0001", False)],
)
def test_rsi_inclusive_boundary_golden(rsi: str, expected: bool) -> None:
    result = _evaluate(snapshot=_snapshot(rsi14=rsi))

    assert result.evaluation.momentum.rsi_passed is expected
    assert result.evaluation.qualified is expected


@pytest.mark.parametrize(
    ("adx", "expected"),
    [("22", False), ("22.0001", True)],
)
def test_adx_strict_boundary_golden(adx: str, expected: bool) -> None:
    result = _evaluate(snapshot=_snapshot(adx14=adx))

    assert result.evaluation.momentum.adx_passed is expected
    assert result.evaluation.qualified is expected


@pytest.mark.parametrize(
    ("hour", "minute", "expected"),
    [(9, 19, False), (9, 20, True), (15, 0, True), (15, 1, False)],
)
def test_signal_window_boundary_golden(hour: int, minute: int, expected: bool) -> None:
    interval = _interval(end_hour=hour, end_minute=minute)
    result = _evaluate(candle=_candle(interval=interval), snapshot=_snapshot(interval=interval))

    assert result.evaluation.qualified is True
    assert result.evaluation.actionable is expected
    assert (EvaluationGuardReason.OUTSIDE_SIGNAL_WINDOW in result.guard.reasons) is (not expected)


@pytest.mark.parametrize(("warmup", "expected"), [(249, False), (250, True)])
def test_warmup_boundary_golden(warmup: int, expected: bool) -> None:
    result = _evaluate(context=_context(warmup=warmup))

    assert result.evaluation.qualified is True
    assert result.evaluation.actionable is expected
    assert (EvaluationGuardReason.INSUFFICIENT_WARMUP in result.guard.reasons) is (not expected)


def test_unavailable_indicator_snapshot_is_not_actionable() -> None:
    result = _evaluate(snapshot=_snapshot(ready=False, ema50=None))

    assert result.guard.eligible is False
    assert result.evaluation.actionable is False
    assert EvaluationGuardReason.INDICATORS_NOT_READY in result.guard.reasons


def test_macd_sign_is_diagnostic_only_in_golden_vector() -> None:
    positive = _evaluate(snapshot=_snapshot(macd_signal="1"))
    zero = _evaluate(snapshot=_snapshot(macd_signal="0"))
    negative = _evaluate(snapshot=_snapshot(macd_signal="-1"))

    assert positive.evaluation.qualified is True
    assert zero.evaluation.qualified is True
    assert negative.evaluation.qualified is True
    assert positive.evaluation.actionable is True
    assert zero.evaluation.actionable is True
    assert negative.evaluation.actionable is True
    assert positive.evaluation.momentum.macd_signal_positive is True
    assert zero.evaluation.momentum.macd_signal_positive is False
    assert negative.evaluation.momentum.macd_signal_positive is False


def test_qualified_but_non_actionable_preserves_strategy_truth() -> None:
    result = _evaluate(context=_context(feed_state=MarketDataFeedState.STALE))

    assert result.evaluation.qualified is True
    assert result.evaluation.actionable is False
    assert result.evaluation.reasons == (
        DecisionReason.QUALIFIED,
        DecisionReason.QUALIFIED_NOT_ACTIONABLE,
    )
    assert result.guard.reasons == (EvaluationGuardReason.FEED_NOT_HEALTHY,)


def test_replay_of_identical_canonical_sequence_is_logically_identical() -> None:
    vectors = [
        (_candle(close="101"), _snapshot()),
        (_candle(close="100"), _snapshot(ema9="100")),
        (_candle(close="101"), _snapshot(rsi14="65")),
        (_candle(close="101"), _snapshot(adx14="22")),
    ]

    first = [EVALUATOR.evaluate(candle, snapshot, _context()) for candle, snapshot in vectors]
    second = [EVALUATOR.evaluate(candle, snapshot, _context()) for candle, snapshot in vectors]

    assert first == second
    assert [asdict(item) for item in first] == [asdict(item) for item in second]
    assert [repr(item) for item in first] == [repr(item) for item in second]


def test_evaluator_result_contains_decision_facts_only() -> None:
    result = _evaluate()

    assert isinstance(result, StrategyEvaluatorResult)
    assert set(asdict(result)) == {"evaluation", "guard"}
