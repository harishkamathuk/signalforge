"""Experimental BTC perpetual momentum strategy, independent of NSE session time."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from signalforge.config.btc_momentum_baseline_v0 import BtcMomentumBaselineV0Config
from signalforge.config.identity import ConfigIdentity
from signalforge.domain.armed import ExpiryReason
from signalforge.domain.ids import InstrumentId
from signalforge.domain.indicators import (
    AdxRequirement,
    EmaRequirement,
    IndicatorRequirements,
    MacdRequirement,
    RsiRequirement,
)
from signalforge.domain.market import CandleQuality, CompletedCandle
from signalforge.domain.money import Price
from signalforge.domain.provenance import StrategyIdentity
from signalforge.domain.signals import Signal
from signalforge.domain.time import CandleInterval
from signalforge.runtime.eligibility import MarketDataFeedState
from signalforge.runtime.indicators import IndicatorContinuity
from signalforge.runtime.strategy import (
    ArmedPolicyIntent,
    ArmedSetupView,
    ArmIntent,
    CompletedCandleStrategyContext,
    PositionEconomics,
    PriceBarrierDirection,
    PriceBarrierIntent,
    StrategyDecision,
    StrategyEntryFillView,
)


@dataclass(frozen=True, slots=True)
class BtcMomentumBaselineDecision:
    """Explicit independent qualification and readiness rejection evidence."""

    instrument_id: InstrumentId
    interval: CandleInterval
    qualified: bool
    actionable: bool
    reasons: tuple[str, ...]
    macd_signal_positive: bool | None

    def __post_init__(self) -> None:
        if self.actionable and not self.qualified:
            raise ValueError("Actionable BTC decision must be qualified")


class BtcMomentumBaselineV0Strategy:
    """Approved long-only 5m momentum baseline, no daily session boundary."""

    def __init__(self, config: BtcMomentumBaselineV0Config) -> None:
        self.config = config
        self._identity = config.identify()
        self._requirements = IndicatorRequirements.of(
            EmaRequirement(9),
            EmaRequirement(20),
            EmaRequirement(50),
            RsiRequirement(14),
            AdxRequirement(14),
            MacdRequirement(12, 26, 9),
        )

    @property
    def identity(self) -> StrategyIdentity:
        return self.config.strategy_identity

    @property
    def config_identity(self) -> ConfigIdentity:
        return self._identity

    @property
    def indicator_requirements(self) -> IndicatorRequirements:
        return self._requirements

    def evaluate_completed_candle(
        self, context: CompletedCandleStrategyContext
    ) -> BtcMomentumBaselineDecision:
        candle = context.candle
        indicator = context.indicators
        if candle.instrument_id != indicator.instrument_id or candle.interval != indicator.interval:
            raise ValueError("BTC candle and indicator evidence must refer to the same interval")
        reasons: list[str] = []
        if candle.interval.end - candle.interval.start != timedelta(minutes=5):
            reasons.append("non_canonical_timeframe")
        if candle.quality is not CandleQuality.VALID:
            reasons.append("invalid_candle_quality")
        if not indicator.ready:
            reasons.append("indicators_not_ready")
        if context.continuity is not IndicatorContinuity.HEALTHY:
            reasons.append("continuity_broken")
        if context.completed_regular_session_candles < 250:
            reasons.append("insufficient_warmup")
        if context.feed_state is not None and context.feed_state is not MarketDataFeedState.HEALTHY:
            reasons.append("feed_not_healthy")
        if (
            indicator.ema20 is None
            or indicator.ema50 is None
            or not indicator.ema20 > indicator.ema50
        ):
            reasons.append("trend_not_met")
        if (
            candle.close is None
            or indicator.ema9 is None
            or not candle.close.value > indicator.ema9
        ):
            reasons.append("setup_not_met")
        if indicator.rsi14 is None or not Decimal("58") <= indicator.rsi14 <= Decimal("65"):
            reasons.append("rsi_not_met")
        if indicator.adx14 is None or not indicator.adx14 > Decimal("22"):
            reasons.append("adx_not_met")
        qualification_reasons = {"trend_not_met", "setup_not_met", "rsi_not_met", "adx_not_met"}
        qualified = not any(reason in qualification_reasons for reason in reasons)
        actionable = qualified and not reasons
        if actionable:
            reasons.append("qualified")
            reasons.append("actionable")
        elif qualified:
            reasons.append("qualified_not_actionable")
        return BtcMomentumBaselineDecision(
            candle.instrument_id,
            candle.interval,
            qualified,
            actionable,
            tuple(reasons),
            None if indicator.macd_signal is None else indicator.macd_signal > 0,
        )

    def arm_intent(self, candle: CompletedCandle, decision: StrategyDecision) -> ArmIntent:
        if not decision.actionable or candle.close is None or candle.low is None:
            raise ValueError("BTC arming requires an actionable complete signal candle")
        return ArmIntent(
            raw_trigger=Price(candle.close.value * Decimal("1.001")),
            stop_price=candle.low,
            valid_until=candle.interval.end + timedelta(minutes=5),
        )

    def armed_policy(self, signal: Signal, setup: ArmedSetupView) -> ArmedPolicyIntent:
        del signal
        return ArmedPolicyIntent(
            pre_entry_invalidation=PriceBarrierIntent(
                price=setup.stop_price,
                direction=PriceBarrierDirection.AT_OR_BELOW,
                expiry_reason=ExpiryReason.SIGNAL_LOW_BREACH,
            )
        )

    def post_fill_economics(
        self, fill: StrategyEntryFillView, setup: ArmedSetupView
    ) -> PositionEconomics:
        risk = fill.fill_price.value - setup.stop_price.value
        return PositionEconomics(
            stop_price=setup.stop_price,
            raw_target_price=(
                Price(fill.fill_price.value + Decimal("1.5") * risk)
                if risk > 0 else None
            ),
        )
