from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from signalforge.config.strategy_v1 import StrategyV1EvaluationConfig
from signalforge.domain.ids import InstrumentId
from signalforge.domain.indicators import IndicatorSnapshot
from signalforge.domain.market import CandleQuality, CompletedCandle
from signalforge.domain.money import Price
from signalforge.domain.time import IST, CandleInterval
from signalforge.runtime.eligibility import (
    EvaluationGuardReason,
    MarketDataFeedState,
    evaluate_guard,
)
from signalforge.runtime.indicators import IndicatorContinuity

INSTRUMENT = InstrumentId("NSE:TEST")


def _interval(*, end_hour: int = 10, end_minute: int = 0, minutes: int = 5) -> CandleInterval:
    end = datetime(2026, 8, 31, end_hour, end_minute, tzinfo=IST)
    return CandleInterval(start=end - timedelta(minutes=minutes), end=end)


def _candle(
    *,
    interval: CandleInterval | None = None,
    quality: CandleQuality = CandleQuality.VALID,
    instrument_id: InstrumentId = INSTRUMENT,
) -> CompletedCandle:
    interval = interval or _interval()
    if quality is CandleQuality.MISSING:
        return CompletedCandle(
            instrument_id=instrument_id,
            interval=interval,
            quality=quality,
            open=None,
            high=None,
            low=None,
            close=None,
            volume=None,
            source="test",
            source_event_count=0,
        )
    return CompletedCandle(
        instrument_id=instrument_id,
        interval=interval,
        quality=quality,
        open=Price(Decimal("100")),
        high=Price(Decimal("102")),
        low=Price(Decimal("99")),
        close=Price(Decimal("101")),
        volume=100,
        source="test",
        source_event_count=4,
    )


def _snapshot(
    *,
    interval: CandleInterval | None = None,
    ready: bool = True,
    instrument_id: InstrumentId = INSTRUMENT,
) -> IndicatorSnapshot:
    interval = interval or _interval()
    values = {
        "ema9": Decimal("100"),
        "ema20": Decimal("99"),
        "ema50": Decimal("98"),
        "rsi14": Decimal("60"),
        "adx14": Decimal("25"),
        "macd_line": Decimal("1"),
        "macd_signal": Decimal("0.5"),
        "macd_histogram": Decimal("0.5"),
    }
    if not ready:
        values["ema50"] = None
    return IndicatorSnapshot(
        instrument_id=instrument_id,
        interval=interval,
        ready=ready,
        calculation_version="test",
        **values,
    )


def _evaluate(
    *,
    candle: CompletedCandle | None = None,
    snapshot: IndicatorSnapshot | None = None,
    warmup: int = 250,
    continuity: IndicatorContinuity = IndicatorContinuity.HEALTHY,
    feed_state: MarketDataFeedState | None = MarketDataFeedState.HEALTHY,
    config: StrategyV1EvaluationConfig | None = None,
):
    candle = candle or _candle()
    snapshot = snapshot or _snapshot(interval=candle.interval, instrument_id=candle.instrument_id)
    return evaluate_guard(
        candle,
        snapshot,
        config or StrategyV1EvaluationConfig(),
        completed_regular_session_candles=warmup,
        continuity=continuity,
        feed_state=feed_state,
    )


def test_fully_valid_context_is_eligible_and_actionable() -> None:
    result = _evaluate()

    assert result.eligible is True
    assert result.actionable is True
    assert result.reasons == ()


@pytest.mark.parametrize(
    ("warmup", "eligible"),
    [(249, False), (250, True)],
)
def test_warmup_boundary_is_exact(warmup: int, eligible: bool) -> None:
    result = _evaluate(warmup=warmup)

    assert result.eligible is eligible
    assert (EvaluationGuardReason.INSUFFICIENT_WARMUP in result.reasons) is (not eligible)


@pytest.mark.parametrize(
    ("hour", "minute", "actionable"),
    [(9, 19, False), (9, 20, True), (15, 0, True), (15, 1, False)],
)
def test_signal_window_uses_completed_candle_end_time(
    hour: int,
    minute: int,
    actionable: bool,
) -> None:
    interval = _interval(end_hour=hour, end_minute=minute)
    candle = _candle(interval=interval)
    result = _evaluate(candle=candle)

    assert result.eligible is True
    assert result.actionable is actionable
    assert (EvaluationGuardReason.OUTSIDE_SIGNAL_WINDOW in result.reasons) is (not actionable)


def test_invalid_candle_quality_is_ineligible() -> None:
    candle = _candle(quality=CandleQuality.STALE)
    result = _evaluate(candle=candle)

    assert result.eligible is False
    assert result.actionable is False
    assert EvaluationGuardReason.INVALID_CANDLE_QUALITY in result.reasons


def test_indicators_not_ready_is_ineligible() -> None:
    candle = _candle()
    snapshot = _snapshot(interval=candle.interval, ready=False)
    result = _evaluate(candle=candle, snapshot=snapshot)

    assert result.eligible is False
    assert EvaluationGuardReason.INDICATORS_NOT_READY in result.reasons


def test_broken_continuity_is_ineligible() -> None:
    result = _evaluate(continuity=IndicatorContinuity.BROKEN)

    assert result.eligible is False
    assert EvaluationGuardReason.CONTINUITY_BROKEN in result.reasons


def test_non_healthy_feed_is_not_actionable_but_remains_evaluable() -> None:
    result = _evaluate(feed_state=MarketDataFeedState.STALE)

    assert result.eligible is True
    assert result.actionable is False
    assert result.reasons == (EvaluationGuardReason.FEED_NOT_HEALTHY,)


def test_absent_feed_context_does_not_suppress_actionability() -> None:
    result = _evaluate(feed_state=None)

    assert result.eligible is True
    assert result.actionable is True


def test_non_canonical_timeframe_is_ineligible() -> None:
    interval = _interval(minutes=10)
    candle = _candle(interval=interval)
    result = _evaluate(candle=candle)

    assert result.eligible is False
    assert EvaluationGuardReason.NON_CANONICAL_TIMEFRAME in result.reasons


def test_identity_mismatch_fails_fast() -> None:
    candle = _candle()
    snapshot = _snapshot(interval=candle.interval, instrument_id=InstrumentId("NSE:OTHER"))

    with pytest.raises(ValueError, match="instruments must match"):
        _evaluate(candle=candle, snapshot=snapshot)


def test_interval_mismatch_fails_fast() -> None:
    candle = _candle()
    snapshot = _snapshot(interval=_interval(end_hour=10, end_minute=5))

    with pytest.raises(ValueError, match="intervals must match"):
        _evaluate(candle=candle, snapshot=snapshot)


@pytest.mark.parametrize("warmup", [True, Decimal("250"), -1])
def test_invalid_warmup_count_is_rejected(warmup: object) -> None:
    candle = _candle()
    snapshot = _snapshot(interval=candle.interval)

    expected = TypeError if warmup is True or isinstance(warmup, Decimal) else ValueError
    with pytest.raises(expected):
        evaluate_guard(
            candle,
            snapshot,
            StrategyV1EvaluationConfig(),
            completed_regular_session_candles=warmup,  # type: ignore[arg-type]
            continuity=IndicatorContinuity.HEALTHY,
            feed_state=MarketDataFeedState.HEALTHY,
        )


def test_reason_order_is_deterministic() -> None:
    interval = _interval(end_hour=9, end_minute=19, minutes=10)
    candle = _candle(interval=interval, quality=CandleQuality.STALE)
    snapshot = _snapshot(interval=interval, ready=False)
    result = _evaluate(
        candle=candle,
        snapshot=snapshot,
        warmup=249,
        continuity=IndicatorContinuity.BROKEN,
        feed_state=MarketDataFeedState.DISCONNECTED,
    )

    assert result.reasons == (
        EvaluationGuardReason.NON_CANONICAL_TIMEFRAME,
        EvaluationGuardReason.INVALID_CANDLE_QUALITY,
        EvaluationGuardReason.INDICATORS_NOT_READY,
        EvaluationGuardReason.CONTINUITY_BROKEN,
        EvaluationGuardReason.INSUFFICIENT_WARMUP,
        EvaluationGuardReason.OUTSIDE_SIGNAL_WINDOW,
        EvaluationGuardReason.FEED_NOT_HEALTHY,
    )
