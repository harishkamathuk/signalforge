"""Frozen typed BTC baseline configuration; parameters cannot drift from approval."""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict

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
    rsi_min: Literal[Decimal("58")] = Decimal("58")
    rsi_max: Literal[Decimal("65")] = Decimal("65")
    adx_period: Literal[14] = 14
    adx_threshold: Literal[Decimal("22")] = Decimal("22")
    macd_fast_period: Literal[12] = 12
    macd_slow_period: Literal[26] = 26
    macd_signal_period: Literal[9] = 9

    @property
    def strategy_identity(self) -> StrategyIdentity:
        return StrategyIdentity(self.strategy_id, self.strategy_version)

    def identify(self) -> ConfigIdentity:
        """Hash exact typed policy, retaining experimental governance classification."""
        return identify_config(self.model_dump(mode="python"), status=ConfigStatus.EXPERIMENTAL)
