"""Frozen typed BTC baseline configuration; parameters cannot drift from approval."""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator

from signalforge.config.identity import ConfigIdentity, ConfigStatus, identify_config
from signalforge.domain.provenance import StrategyIdentity


class BtcMomentumBaselineV0Config(BaseModel):
    """The accepted experimental baseline, with no free parameter optimisation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    strategy_id: Literal["btc_momentum_baseline_v0"] = "btc_momentum_baseline_v0"
    strategy_version: Literal["0.1.0-experimental"] = "0.1.0-experimental"
    timeframe_minutes: Literal[5] = 5
    minimum_warmup_candles: Literal[250] = 250
    setup_ema_period: Literal[9] = 9
    trend_fast_ema_period: Literal[20] = 20
    trend_slow_ema_period: Literal[50] = 50
    rsi_period: Literal[14] = 14
    rsi_min: Decimal = Decimal("58")
    rsi_max: Decimal = Decimal("65")
    adx_period: Literal[14] = 14
    adx_threshold: Decimal = Decimal("22")
    macd_fast_period: Literal[12] = 12
    macd_slow_period: Literal[26] = 26
    macd_signal_period: Literal[9] = 9

    @model_validator(mode="after")
    def enforce_approved_decimal_thresholds(self) -> BtcMomentumBaselineV0Config:
        if (
            self.rsi_min != Decimal("58")
            or self.rsi_max != Decimal("65")
            or self.adx_threshold != Decimal("22")
        ):
            raise ValueError("Frozen BTC threshold parameters cannot be changed")
        return self

    @property
    def strategy_identity(self) -> StrategyIdentity:
        return StrategyIdentity(self.strategy_id, self.strategy_version)

    def identify(self) -> ConfigIdentity:
        """Hash exact typed policy, retaining experimental governance classification."""
        return identify_config(self.model_dump(mode="python"), status=ConfigStatus.EXPERIMENTAL)
