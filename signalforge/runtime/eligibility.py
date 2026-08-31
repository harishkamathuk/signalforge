"""Eligibility and actionability guards for Strategy V1 evaluation."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from signalforge.config.strategy_v1 import StrategyV1EvaluationConfig
from signalforge.domain.indicators import IndicatorSnapshot
from signalforge.domain.market import CandleQuality, CompletedCandle
from signalforge.domain.time import IST
from signalforge.runtime.indicators import IndicatorContinuity


class MarketDataFeedState(StrEnum):
    """Accepted ADR-005 market-data feed states relevant to new signals."""

    STARTING = "starting"
    HEALTHY = "healthy"
    STALE = "stale"
    DISCONNECTED = "disconnected"
    RECOVERING = "recovering"
    FAILED = "failed"


class EvaluationGuardReason(StrEnum):
    """Stable machine-readable reasons an evaluation is not actionable."""

    NON_CANONICAL_TIMEFRAME = "non_canonical_timeframe"
    INVALID_CANDLE_QUALITY = "invalid_candle_quality"
    INDICATORS_NOT_READY = "indicators_not_ready"
    CONTINUITY_BROKEN = "continuity_broken"
    INSUFFICIENT_WARMUP = "insufficient_warmup"
    OUTSIDE_SIGNAL_WINDOW = "outside_signal_window"
    FEED_NOT_HEALTHY = "feed_not_healthy"


_ELIGIBILITY_REASONS = frozenset(
    {
        EvaluationGuardReason.NON_CANONICAL_TIMEFRAME,
        EvaluationGuardReason.INVALID_CANDLE_QUALITY,
        EvaluationGuardReason.INDICATORS_NOT_READY,
        EvaluationGuardReason.CONTINUITY_BROKEN,
        EvaluationGuardReason.INSUFFICIENT_WARMUP,
    }
)


@dataclass(frozen=True, slots=True)
class EvaluationGuardResult:
    """Deterministic eligibility/actionability decision for one completed candle."""

    eligible: bool
    actionable: bool
    reasons: tuple[EvaluationGuardReason, ...]

    def __post_init__(self) -> None:
        if self.actionable and not self.eligible:
            raise ValueError("Actionable evaluation must also be eligible")
        expected_eligible = not any(reason in _ELIGIBILITY_REASONS for reason in self.reasons)
        if self.eligible != expected_eligible:
            raise ValueError("Eligibility does not match guard reasons")
        if self.actionable != (self.eligible and not self.reasons):
            raise ValueError("Actionability does not match guard reasons")


def evaluate_guard(
    candle: CompletedCandle,
    snapshot: IndicatorSnapshot,
    config: StrategyV1EvaluationConfig,
    *,
    completed_regular_session_candles: int,
    continuity: IndicatorContinuity,
    feed_state: MarketDataFeedState | None = None,
) -> EvaluationGuardResult:
    """Evaluate Strategy V1 non-qualification eligibility/actionability constraints."""

    if candle.instrument_id != snapshot.instrument_id:
        raise ValueError("Candle and IndicatorSnapshot instruments must match")
    if candle.interval != snapshot.interval:
        raise ValueError("Candle and IndicatorSnapshot intervals must match")
    if isinstance(completed_regular_session_candles, bool) or not isinstance(
        completed_regular_session_candles, int
    ):
        raise TypeError("completed_regular_session_candles must be an integer")
    if completed_regular_session_candles < 0:
        raise ValueError("completed_regular_session_candles must not be negative")

    reasons: list[EvaluationGuardReason] = []

    interval_seconds = (candle.interval.end - candle.interval.start).total_seconds()
    if interval_seconds != config.timeframe_minutes * 60:
        reasons.append(EvaluationGuardReason.NON_CANONICAL_TIMEFRAME)
    if candle.quality is not CandleQuality.VALID:
        reasons.append(EvaluationGuardReason.INVALID_CANDLE_QUALITY)
    if not snapshot.ready:
        reasons.append(EvaluationGuardReason.INDICATORS_NOT_READY)
    if continuity is not IndicatorContinuity.HEALTHY:
        reasons.append(EvaluationGuardReason.CONTINUITY_BROKEN)
    if completed_regular_session_candles < config.minimum_warmup_candles:
        reasons.append(EvaluationGuardReason.INSUFFICIENT_WARMUP)

    evaluation_time = candle.interval.end.astimezone(IST).time().replace(tzinfo=None)
    if not (config.first_signal_time_ist <= evaluation_time <= config.last_signal_time_ist):
        reasons.append(EvaluationGuardReason.OUTSIDE_SIGNAL_WINDOW)
    if feed_state is not None and feed_state is not MarketDataFeedState.HEALTHY:
        reasons.append(EvaluationGuardReason.FEED_NOT_HEALTHY)

    reason_tuple = tuple(reasons)
    eligible = not any(reason in _ELIGIBILITY_REASONS for reason in reason_tuple)
    actionable = eligible and not reason_tuple
    return EvaluationGuardResult(
        eligible=eligible,
        actionable=actionable,
        reasons=reason_tuple,
    )
