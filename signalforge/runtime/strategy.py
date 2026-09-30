"""Typed strategy boundary consumed by shared runtime orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from signalforge.config.identity import ConfigIdentity
from signalforge.domain.ids import InstrumentId
from signalforge.domain.indicators import IndicatorSnapshot
from signalforge.domain.market import CompletedCandle
from signalforge.domain.provenance import StrategyIdentity
from signalforge.domain.time import CandleInterval
from signalforge.runtime.eligibility import MarketDataFeedState
from signalforge.runtime.indicators import IndicatorContinuity


@dataclass(frozen=True, slots=True)
class StrategyRuntimeFacts:
    """Read-only runtime facts supplied alongside a completed candle."""

    completed_regular_session_candles: int
    continuity: IndicatorContinuity
    feed_state: MarketDataFeedState | None = None


@dataclass(frozen=True, slots=True)
class CompletedCandleStrategyContext:
    """Read-only completed-candle state visible to a strategy."""

    candle: CompletedCandle
    indicators: IndicatorSnapshot
    completed_regular_session_candles: int
    continuity: IndicatorContinuity
    feed_state: MarketDataFeedState | None = None


class StrategyDecision(Protocol):
    """Minimal decision surface consumed by shared lifecycle/runtime code."""

    @property
    def instrument_id(self) -> InstrumentId: ...

    @property
    def interval(self) -> CandleInterval: ...

    @property
    def qualified(self) -> bool: ...

    @property
    def actionable(self) -> bool: ...

    @property
    def reasons(self) -> tuple[str, ...]: ...


class Strategy(Protocol):
    """Stable strategy boundary for completed-candle evaluation."""

    @property
    def identity(self) -> StrategyIdentity: ...

    @property
    def config_identity(self) -> ConfigIdentity: ...

    def evaluate_completed_candle(
        self,
        context: CompletedCandleStrategyContext,
    ) -> StrategyDecision: ...
