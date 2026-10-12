"""Strategy V1 adapter for the shared strategy and lifecycle-policy contracts."""

from __future__ import annotations

from datetime import datetime, time, timedelta
from decimal import Decimal

from signalforge.config.identity import ConfigIdentity
from signalforge.config.strategy_v1 import StrategyV1EvaluationConfig
from signalforge.domain.armed import ExpiryReason
from signalforge.domain.indicators import (
    AdxRequirement,
    EmaRequirement,
    IndicatorRequirements,
    MacdRequirement,
    RsiRequirement,
)
from signalforge.domain.market import CompletedCandle
from signalforge.domain.money import Price
from signalforge.domain.provenance import StrategyIdentity
from signalforge.domain.signals import Signal
from signalforge.domain.time import IST
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
from signalforge.runtime.strategy_evaluator import StrategyEvaluationContext, StrategyEvaluator

_ENTRY_OFFSET = Decimal("1.001")
_TARGET_R_MULTIPLE = Decimal("1.5")
_ENTRY_CUTOFF = time(15, 5)


class IntradayMomentumV1Strategy:
    """Accepted intraday_momentum_v1 policy behind the shared strategy boundary."""

    def __init__(self, config: StrategyV1EvaluationConfig) -> None:
        self.config = config
        self._config_identity = config.identify()
        self._indicator_requirements = IndicatorRequirements.of(
            EmaRequirement(config.setup_ema_period),
            EmaRequirement(config.trend_fast_ema_period),
            EmaRequirement(config.trend_slow_ema_period),
            RsiRequirement(config.rsi_period),
            AdxRequirement(config.adx_period),
            MacdRequirement(
                config.macd_fast_period,
                config.macd_slow_period,
                config.macd_signal_period,
            ),
        )
        self._evaluator = StrategyEvaluator(config)

    @property
    def identity(self) -> StrategyIdentity:
        return self.config.strategy_identity

    @property
    def config_identity(self) -> ConfigIdentity:
        return self._config_identity

    @property
    def indicator_requirements(self) -> IndicatorRequirements:
        """Return Strategy V1's canonical indicator requirements."""

        return self._indicator_requirements

    def evaluate_completed_candle(
        self,
        context: CompletedCandleStrategyContext,
    ) -> StrategyDecision:
        return self._evaluator.evaluate(
            context.candle,
            context.indicators,
            StrategyEvaluationContext(
                completed_regular_session_candles=context.completed_regular_session_candles,
                continuity=context.continuity,
                feed_state=context.feed_state,
            ),
        )

    def arm_intent(
        self,
        candle: CompletedCandle,
        decision: StrategyDecision,
    ) -> ArmIntent:
        if not decision.actionable:
            raise ValueError("Strategy V1 arm intent requires an actionable decision")
        if candle.close is None or candle.low is None:
            raise ValueError("Strategy V1 actionable candle requires close and low")
        return ArmIntent(
            raw_trigger=Price(candle.close.value * _ENTRY_OFFSET),
            stop_price=candle.low,
            valid_until=candle.interval.end + timedelta(minutes=5),
        )

    def armed_policy(
        self,
        signal: Signal,
        setup: ArmedSetupView,
    ) -> ArmedPolicyIntent:
        """Return declarative pre-entry invalidation and cutoff policy."""

        return ArmedPolicyIntent(
            pre_entry_invalidation=PriceBarrierIntent(
                price=setup.stop_price,
                direction=PriceBarrierDirection.AT_OR_BELOW,
                expiry_reason=ExpiryReason.SIGNAL_LOW_BREACH,
            ),
            strategy_entry_cutoff_at=self._entry_cutoff(signal.interval.end),
        )

    def post_fill_economics(
        self,
        fill: StrategyEntryFillView,
        setup: ArmedSetupView,
    ) -> PositionEconomics:
        stop_price = setup.stop_price
        risk_value = fill.fill_price.value - stop_price.value
        if risk_value <= 0:
            return PositionEconomics(
                stop_price=stop_price,
                raw_target_price=None,
            )
        raw_target = Price(fill.fill_price.value + _TARGET_R_MULTIPLE * risk_value)
        return PositionEconomics(
            stop_price=stop_price,
            raw_target_price=raw_target,
        )

    @staticmethod
    def _entry_cutoff(signal_time: datetime) -> datetime:
        local = signal_time.astimezone(IST)
        return datetime.combine(local.date(), _ENTRY_CUTOFF, tzinfo=IST)
