"""Experimental RSI mean-reversion reference strategy for architecture validation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from signalforge.config.identity import ConfigIdentity
from signalforge.config.rsi_mean_reversion_v1 import RsiMeanReversionV1Config
from signalforge.domain.ids import InstrumentId
from signalforge.domain.indicators import IndicatorRequirements, RsiRequirement
from signalforge.domain.market import CompletedCandle
from signalforge.domain.money import Price
from signalforge.domain.provenance import StrategyIdentity
from signalforge.domain.signals import Signal
from signalforge.domain.time import CandleInterval
from signalforge.runtime.strategy import (
    ArmedPolicyIntent,
    ArmedSetupView,
    ArmIntent,
    CompletedCandleStrategyContext,
    PositionEconomics,
    StrategyDecision,
    StrategyEntryFillView,
)

_RSI_REASON_UNAVAILABLE = "rsi_unavailable"
_RSI_REASON_NOT_BELOW_THRESHOLD = "rsi_not_below_threshold"
_RSI_REASON_QUALIFIED = "rsi_below_threshold"


@dataclass(frozen=True, slots=True)
class RsiMeanReversionDecision:
    """Completed-candle decision emitted by the experimental reference strategy."""

    instrument_id: InstrumentId
    interval: CandleInterval
    qualified: bool
    actionable: bool
    reasons: tuple[str, ...]
    rsi14: Decimal | None

    def __post_init__(self) -> None:
        if self.actionable and not self.qualified:
            raise ValueError("Actionable RSI mean-reversion decision must be qualified")
        if not self.reasons:
            raise ValueError("RSI mean-reversion decision requires at least one reason")


class RsiMeanReversionV1Strategy:
    """Experimental RSI(14) < 30 reference strategy behind the shared Strategy API."""

    def __init__(self, config: RsiMeanReversionV1Config) -> None:
        self.config = config
        self._config_identity = config.identify()
        self._indicator_requirements = IndicatorRequirements.of(
            RsiRequirement(config.rsi_period)
        )

    @property
    def identity(self) -> StrategyIdentity:
        """Return the reference strategy identity."""

        return self.config.strategy_identity

    @property
    def config_identity(self) -> ConfigIdentity:
        """Return deterministic experimental configuration identity."""

        return self._config_identity

    @property
    def indicator_requirements(self) -> IndicatorRequirements:
        """Declare RSI(14) as the strategy's only indicator requirement."""

        return self._indicator_requirements

    def evaluate_completed_candle(
        self,
        context: CompletedCandleStrategyContext,
    ) -> RsiMeanReversionDecision:
        """Qualify only completed candles whose canonical RSI(14) is strictly below 30."""

        rsi = context.indicators.rsi(self.config.rsi_period)
        if rsi is None:
            return RsiMeanReversionDecision(
                context.candle.instrument_id,
                context.candle.interval,
                qualified=False,
                actionable=False,
                reasons=(_RSI_REASON_UNAVAILABLE,),
                rsi14=None,
            )
        if rsi >= self.config.rsi_threshold:
            return RsiMeanReversionDecision(
                context.candle.instrument_id,
                context.candle.interval,
                qualified=False,
                actionable=False,
                reasons=(_RSI_REASON_NOT_BELOW_THRESHOLD,),
                rsi14=rsi,
            )
        return RsiMeanReversionDecision(
            context.candle.instrument_id,
            context.candle.interval,
            qualified=True,
            actionable=True,
            reasons=(_RSI_REASON_QUALIFIED,),
            rsi14=rsi,
        )

    def arm_intent(
        self,
        candle: CompletedCandle,
        decision: StrategyDecision,
    ) -> ArmIntent:
        """Return signal-close entry, signal-low stop, and one-candle validity."""

        if not decision.actionable:
            raise ValueError("RSI mean-reversion arm intent requires an actionable decision")
        if candle.close is None or candle.low is None:
            raise ValueError("RSI mean-reversion actionable candle requires close and low")
        return ArmIntent(
            raw_trigger=candle.close,
            stop_price=candle.low,
            valid_until=candle.interval.end
            + timedelta(minutes=self.config.timeframe_minutes),
        )

    def armed_policy(
        self,
        signal: Signal,
        setup: ArmedSetupView,
    ) -> ArmedPolicyIntent:
        """Return the reference strategy's declarative ARMED policy."""

        del signal, setup
        return ArmedPolicyIntent()

    def post_fill_economics(
        self,
        fill: StrategyEntryFillView,
        setup: ArmedSetupView,
    ) -> PositionEconomics:
        """Return signal-low stop and raw 1.0R target from the authoritative fill."""

        stop_price = setup.stop_price
        risk_value = fill.fill_price.value - stop_price.value
        if risk_value <= 0:
            return PositionEconomics(
                stop_price=stop_price,
                raw_target_price=None,
            )
        raw_target = Price(
            fill.fill_price.value + self.config.target_r_multiple * risk_value
        )
        return PositionEconomics(
            stop_price=stop_price,
            raw_target_price=raw_target,
        )
