"""Strategy V1 adapter for the shared strategy and lifecycle-policy contracts."""

from __future__ import annotations

from datetime import datetime, time, timedelta
from decimal import Decimal

from signalforge.config.identity import ConfigIdentity
from signalforge.config.strategy_v1 import StrategyV1EvaluationConfig
from signalforge.domain.armed import ExpiryReason
from signalforge.domain.execution import Fill
from signalforge.domain.market import CompletedCandle, MarketEvent
from signalforge.domain.money import Price
from signalforge.domain.provenance import StrategyIdentity
from signalforge.domain.signals import Signal
from signalforge.domain.time import IST
from signalforge.runtime.strategy import (
    ArmedEventAction,
    ArmedEventDecision,
    ArmedSetupView,
    ArmIntent,
    CompletedCandleStrategyContext,
    PositionEconomics,
    StrategyDecision,
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
        self._evaluator = StrategyEvaluator(config)

    @property
    def identity(self) -> StrategyIdentity:
        return self.config.strategy_identity

    @property
    def config_identity(self) -> ConfigIdentity:
        return self._config_identity

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

    def evaluate_armed_market_event(
        self,
        signal: Signal,
        setup: ArmedSetupView,
        event: MarketEvent,
    ) -> ArmedEventDecision:
        cutoff = self._entry_cutoff(signal.interval.end)
        observed_at = event.exchange_timestamp
        if observed_at >= cutoff:
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
        if event.price.value <= setup.stop_price.value:
            return ArmedEventDecision(
                ArmedEventAction.EXPIRE,
                at=observed_at,
                expiry_reason=ExpiryReason.SIGNAL_LOW_BREACH,
            )
        return ArmedEventDecision(ArmedEventAction.NO_ACTION)

    def evaluate_armed_completed_candle(
        self,
        signal: Signal,
        setup: ArmedSetupView,
        candle: CompletedCandle,
    ) -> ArmedEventDecision:
        if candle.interval.start != setup.armed_at or candle.interval.end != setup.valid_until:
            raise ValueError("CompletedCandle must be the active setup's following candle")
        cutoff = self._entry_cutoff(signal.interval.end)
        if setup.valid_until >= cutoff:
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

    def evaluate_armed_time(
        self,
        signal: Signal,
        setup: ArmedSetupView,
        at: datetime,
    ) -> ArmedEventDecision:
        cutoff = self._entry_cutoff(signal.interval.end)
        if cutoff <= setup.valid_until and at >= cutoff:
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

    def post_fill_economics(
        self,
        fill: Fill,
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
