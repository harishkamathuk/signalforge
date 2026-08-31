"""Typed configuration for the accepted intraday_momentum_v1 evaluator."""

from datetime import time
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from signalforge.config.identity import ConfigIdentity, ConfigStatus, identify_config
from signalforge.domain.provenance import StrategyIdentity


class StrategyV1EvaluationConfig(BaseModel):
    """Immutable Strategy V1 evaluation parameters and frozen comparison semantics."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    strategy_id: Literal["intraday_momentum_v1"] = "intraday_momentum_v1"
    strategy_version: Literal["1.0.0"] = "1.0.0"

    timeframe_minutes: int = Field(default=5, gt=0)
    setup_ema_period: int = Field(default=9, gt=0)
    trend_fast_ema_period: int = Field(default=20, gt=0)
    trend_slow_ema_period: int = Field(default=50, gt=0)
    rsi_period: int = Field(default=14, gt=0)
    rsi_min: Decimal = Decimal("58")
    rsi_max: Decimal = Decimal("65")
    adx_period: int = Field(default=14, gt=0)
    adx_threshold: Decimal = Decimal("22")
    macd_fast_period: int = Field(default=12, gt=0)
    macd_slow_period: int = Field(default=26, gt=0)
    macd_signal_period: int = Field(default=9, gt=0)

    minimum_warmup_candles: int = Field(default=250, ge=0)
    first_signal_time_ist: time = time(9, 20)
    last_signal_time_ist: time = time(15, 0)

    rsi_lower_inclusive: Literal[True] = True
    rsi_upper_inclusive: Literal[True] = True
    adx_strictly_greater: Literal[True] = True
    trend_strictly_greater: Literal[True] = True
    setup_strictly_greater: Literal[True] = True
    macd_diagnostic_only: Literal[True] = True

    @model_validator(mode="after")
    def validate_relationships(self) -> "StrategyV1EvaluationConfig":
        if self.rsi_min > self.rsi_max:
            raise ValueError("RSI minimum must not exceed RSI maximum")
        if self.first_signal_time_ist > self.last_signal_time_ist:
            raise ValueError("first signal time must not be after last signal time")
        if self.trend_fast_ema_period >= self.trend_slow_ema_period:
            raise ValueError("trend fast EMA period must be less than trend slow EMA period")
        if self.macd_fast_period >= self.macd_slow_period:
            raise ValueError("MACD fast period must be less than MACD slow period")
        return self

    @property
    def strategy_identity(self) -> StrategyIdentity:
        return StrategyIdentity(
            strategy_id=self.strategy_id,
            strategy_version=self.strategy_version,
        )

    def semantic_mapping(self) -> dict[str, object]:
        """Return canonical hashable semantic content for config identity."""

        return {
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "timeframe_minutes": self.timeframe_minutes,
            "setup_ema_period": self.setup_ema_period,
            "trend_fast_ema_period": self.trend_fast_ema_period,
            "trend_slow_ema_period": self.trend_slow_ema_period,
            "rsi_period": self.rsi_period,
            "rsi_min": self.rsi_min,
            "rsi_max": self.rsi_max,
            "rsi_lower_inclusive": self.rsi_lower_inclusive,
            "rsi_upper_inclusive": self.rsi_upper_inclusive,
            "adx_period": self.adx_period,
            "adx_threshold": self.adx_threshold,
            "adx_strictly_greater": self.adx_strictly_greater,
            "macd_fast_period": self.macd_fast_period,
            "macd_slow_period": self.macd_slow_period,
            "macd_signal_period": self.macd_signal_period,
            "macd_diagnostic_only": self.macd_diagnostic_only,
            "trend_strictly_greater": self.trend_strictly_greater,
            "setup_strictly_greater": self.setup_strictly_greater,
            "minimum_warmup_candles": self.minimum_warmup_candles,
            "first_signal_time_ist": self.first_signal_time_ist.isoformat(timespec="minutes"),
            "last_signal_time_ist": self.last_signal_time_ist.isoformat(timespec="minutes"),
        }

    def identify(self, *, status: ConfigStatus = ConfigStatus.ACCEPTED) -> ConfigIdentity:
        """Build canonical identity for this Strategy V1 configuration."""

        return identify_config(self.semantic_mapping(), status=status)
