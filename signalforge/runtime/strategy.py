"""Typed strategy boundary consumed by shared runtime orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from signalforge.config.identity import ConfigIdentity
from signalforge.domain.armed import ArmedSetupState, ExpiryReason
from signalforge.domain.ids import InstrumentId, SignalId
from signalforge.domain.indicators import IndicatorRequirements, IndicatorSnapshot
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
    """Strategy-owned pre-fill arming facts accepted by generic lifecycle mechanics."""

    raw_trigger: Price
    stop_price: Price
    valid_until: datetime

    def __post_init__(self) -> None:
        if self.raw_trigger.value <= 0 or self.stop_price.value <= 0:
            raise ValueError("ArmIntent prices must be strictly positive")


class PriceBarrierDirection(StrEnum):
    """Direction in which a declarative price barrier becomes satisfied."""

    AT_OR_ABOVE = "at_or_above"
    AT_OR_BELOW = "at_or_below"


@dataclass(frozen=True, slots=True)
class PriceBarrierIntent:
    """One typed strategy-owned pre-entry invalidation barrier."""

    price: Price
    direction: PriceBarrierDirection
    expiry_reason: ExpiryReason

    def __post_init__(self) -> None:
        if self.price.value <= 0:
            raise ValueError("PriceBarrierIntent price must be strictly positive")


@dataclass(frozen=True, slots=True)
class ArmedPolicyIntent:
    """Declarative strategy-owned policy evaluated by shared ARMED mechanics."""

    pre_entry_invalidation: PriceBarrierIntent | None = None
    strategy_entry_cutoff_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.strategy_entry_cutoff_at is not None:
            from signalforge.domain.time import require_aware

            require_aware(self.strategy_entry_cutoff_at)


@dataclass(frozen=True, slots=True)
class StrategyEntryFillView:
    """Minimal economic entry-fill fact visible to strategy post-fill policy."""

    fill_price: Price

    def __post_init__(self) -> None:
        if self.fill_price.value <= 0:
            raise ValueError("StrategyEntryFillView fill_price must be strictly positive")


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
class ArmedSetupView:
    """Read-only strategy view of accepted ARMED lifecycle facts."""

    signal_id: SignalId
    raw_trigger: Price
    tradable_trigger: Price
    stop_price: Price
    armed_at: datetime
    valid_until: datetime
    state: ArmedSetupState


@dataclass(frozen=True, slots=True)
class PositionEconomics:
    """Strategy-owned post-fill raw economic intent.

    Tradable-price normalization remains a shared runtime responsibility.
    The raw target may be omitted only for non-positive long risk, which
    generic position mechanics reject before opening a Trade.
    """

    stop_price: Price
    raw_target_price: Price | None

    def __post_init__(self) -> None:
        if self.stop_price.value <= 0:
            raise ValueError("PositionEconomics stop must be strictly positive")
        if self.raw_target_price is not None and self.raw_target_price.value <= 0:
            raise ValueError("PositionEconomics raw target must be strictly positive")


class Strategy(Protocol):
    """Stable strategy boundary for completed-candle and lifecycle policy."""

    @property
    def identity(self) -> StrategyIdentity: ...

    @property
    def config_identity(self) -> ConfigIdentity: ...

    @property
    def indicator_requirements(self) -> IndicatorRequirements: ...

    def evaluate_completed_candle(
        self,
        context: CompletedCandleStrategyContext,
    ) -> StrategyDecision: ...

    def arm_intent(
        self,
        candle: CompletedCandle,
        decision: StrategyDecision,
    ) -> ArmIntent: ...

    def armed_policy(
        self,
        signal: Signal,
        setup: ArmedSetupView,
    ) -> ArmedPolicyIntent: ...

    def post_fill_economics(
        self,
        fill: StrategyEntryFillView,
        setup: ArmedSetupView,
    ) -> PositionEconomics: ...


def evaluate_armed_market_event(
    policy: ArmedPolicyIntent,
    setup: ArmedSetupView,
    event: MarketEvent,
) -> ArmedEventDecision:
    """Evaluate one ordered live/PAPER event against declarative ARMED policy."""

    observed_at = event.exchange_timestamp
    cutoff = policy.strategy_entry_cutoff_at
    if cutoff is not None and observed_at >= cutoff:
        return ArmedEventDecision(
            ArmedEventAction.EXPIRE,
            at=cutoff,
            expiry_reason=ExpiryReason.ENTRY_CUTOFF_REACHED,
        )
    if observed_at >= setup.valid_until:
        return ArmedEventDecision(
            ArmedEventAction.EXPIRE,
            at=setup.valid_until,
            expiry_reason=ExpiryReason.VALIDITY_WINDOW_END,
        )
    if event.price.value >= setup.tradable_trigger.value:
        return ArmedEventDecision(ArmedEventAction.TRIGGER, at=observed_at)
    invalidation = policy.pre_entry_invalidation
    if invalidation is not None:
        matched = (
            invalidation.direction is PriceBarrierDirection.AT_OR_BELOW
            and event.price.value <= invalidation.price.value
        ) or (
            invalidation.direction is PriceBarrierDirection.AT_OR_ABOVE
            and event.price.value >= invalidation.price.value
        )
        if matched:
            return ArmedEventDecision(
                ArmedEventAction.EXPIRE,
                at=observed_at,
                expiry_reason=invalidation.expiry_reason,
            )
    return ArmedEventDecision(ArmedEventAction.NO_ACTION)


def evaluate_armed_time(
    policy: ArmedPolicyIntent,
    setup: ArmedSetupView,
    at: datetime,
) -> ArmedEventDecision:
    """Evaluate known time boundaries against declarative ARMED policy."""

    cutoff = policy.strategy_entry_cutoff_at
    if cutoff is not None and cutoff <= setup.valid_until and at >= cutoff:
        return ArmedEventDecision(
            ArmedEventAction.EXPIRE,
            at=cutoff,
            expiry_reason=ExpiryReason.ENTRY_CUTOFF_REACHED,
        )
    if at >= setup.valid_until:
        return ArmedEventDecision(
            ArmedEventAction.EXPIRE,
            at=setup.valid_until,
            expiry_reason=ExpiryReason.VALIDITY_WINDOW_END,
        )
    return ArmedEventDecision(ArmedEventAction.NO_ACTION)


def evaluate_armed_completed_candle(
    policy: ArmedPolicyIntent,
    setup: ArmedSetupView,
    candle: CompletedCandle,
) -> ArmedEventDecision:
    """Expire one active setup at its accepted completed-candle boundary."""

    if candle.interval.start != setup.armed_at or candle.interval.end != setup.valid_until:
        raise ValueError("CompletedCandle must be the active setup's following candle")
    cutoff = policy.strategy_entry_cutoff_at
    if cutoff is not None and setup.valid_until >= cutoff:
        return ArmedEventDecision(
            ArmedEventAction.EXPIRE,
            at=cutoff,
            expiry_reason=ExpiryReason.ENTRY_CUTOFF_REACHED,
        )
    return ArmedEventDecision(
        ArmedEventAction.EXPIRE,
        at=setup.valid_until,
        expiry_reason=ExpiryReason.VALIDITY_WINDOW_END,
    )
