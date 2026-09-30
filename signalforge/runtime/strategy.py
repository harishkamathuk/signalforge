"""Typed strategy boundary consumed by shared runtime orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from signalforge.config.identity import ConfigIdentity
from signalforge.domain.armed import ArmedSetup, ExpiryReason
from signalforge.domain.execution import Fill
from signalforge.domain.ids import InstrumentId
from signalforge.domain.indicators import IndicatorSnapshot
from signalforge.domain.market import CompletedCandle, MarketEvent
from signalforge.domain.money import Price
from signalforge.domain.provenance import StrategyIdentity
from signalforge.domain.signals import Signal
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


@dataclass(frozen=True, slots=True)
class ArmIntent:
    """Strategy-owned pre-fill policy accepted by generic ARMED lifecycle mechanics."""

    raw_trigger: Price
    stop_price: Price
    valid_until: datetime

    def __post_init__(self) -> None:
        if self.raw_trigger.value <= 0 or self.stop_price.value <= 0:
            raise ValueError("ArmIntent prices must be strictly positive")


class ArmedEventAction(StrEnum):
    NO_ACTION = "no_action"
    TRIGGER = "trigger"
    EXPIRE = "expire"


@dataclass(frozen=True, slots=True)
class ArmedEventDecision:
    """Typed strategy response to an event while a setup is ARMED."""

    action: ArmedEventAction
    at: datetime | None = None
    expiry_reason: ExpiryReason | None = None

    def __post_init__(self) -> None:
        if self.action is ArmedEventAction.NO_ACTION:
            if self.at is not None or self.expiry_reason is not None:
                raise ValueError("NO_ACTION cannot include terminal metadata")
        elif self.action is ArmedEventAction.TRIGGER:
            if self.at is None or self.expiry_reason is not None:
                raise ValueError("TRIGGER requires at and no expiry reason")
        elif self.action is ArmedEventAction.EXPIRE:
            if self.at is None or self.expiry_reason is None:
                raise ValueError("EXPIRE requires at and expiry reason")


@dataclass(frozen=True, slots=True)
class PositionEconomics:
    """Strategy-owned post-fill economic intent.

    Targets may be omitted only when the supplied stop produces non-positive
    long risk; generic position mechanics reject that Fill before opening.
    """

    stop_price: Price
    raw_target_price: Price | None
    tradable_target_price: Price | None

    def __post_init__(self) -> None:
        if self.stop_price.value <= 0:
            raise ValueError("PositionEconomics stop must be strictly positive")
        if (self.raw_target_price is None) != (self.tradable_target_price is None):
            raise ValueError("PositionEconomics targets must both be present or both absent")
        if self.raw_target_price is not None:
            if self.raw_target_price.value <= 0 or self.tradable_target_price is None:
                raise ValueError("PositionEconomics targets must be strictly positive")
            if self.tradable_target_price.value < self.raw_target_price.value:
                raise ValueError("Tradable target must not be below raw target")


class Strategy(Protocol):
    """Stable strategy boundary for completed-candle and lifecycle policy."""

    @property
    def identity(self) -> StrategyIdentity: ...

    @property
    def config_identity(self) -> ConfigIdentity: ...

    def evaluate_completed_candle(
        self,
        context: CompletedCandleStrategyContext,
    ) -> StrategyDecision: ...

    def arm_intent(
        self,
        candle: CompletedCandle,
        decision: StrategyDecision,
    ) -> ArmIntent: ...

    def evaluate_armed_market_event(
        self,
        signal: Signal,
        setup: ArmedSetup,
        event: MarketEvent,
    ) -> ArmedEventDecision: ...

    def evaluate_armed_completed_candle(
        self,
        signal: Signal,
        setup: ArmedSetup,
        candle: CompletedCandle,
    ) -> ArmedEventDecision: ...

    def evaluate_armed_time(
        self,
        signal: Signal,
        setup: ArmedSetup,
        at: datetime,
    ) -> ArmedEventDecision: ...

    def post_fill_economics(
        self,
        fill: Fill,
        setup: ArmedSetup,
        tick_size: Price,
    ) -> PositionEconomics: ...
