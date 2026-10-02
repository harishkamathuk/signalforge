"""Strict configuration for the experimental RSI mean-reversion reference strategy."""

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator

from signalforge.config.identity import ConfigIdentity, ConfigStatus, identify_config
from signalforge.domain.provenance import StrategyIdentity


class RsiMeanReversionV1Config(BaseModel):
    """Frozen semantics for the experimental RSI mean-reversion architecture fixture."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    strategy_id: Literal["rsi_mean_reversion_v1"] = "rsi_mean_reversion_v1"
    strategy_version: Literal["1.0.0"] = "1.0.0"
    timeframe_minutes: Literal[5] = 5
    rsi_period: Literal[14] = 14
    rsi_threshold: Decimal = Decimal("30")
    rsi_strictly_below: Literal[True] = True
    target_r_multiple: Decimal = Decimal("1.0")
    validity_candles: Literal[1] = 1

    @model_validator(mode="after")
    def validate_frozen_semantics(self) -> "RsiMeanReversionV1Config":
        """Reject parameter drift under the fixed 1.0.0 reference identity."""

        if self.rsi_threshold != Decimal("30"):
            raise ValueError("RSI threshold is fixed at 30 for version 1.0.0")
        if self.target_r_multiple != Decimal("1.0"):
            raise ValueError("Target R multiple is fixed at 1.0 for version 1.0.0")
        return self

    @property
    def strategy_identity(self) -> StrategyIdentity:
        """Return the immutable strategy identity selected by this config."""

        return StrategyIdentity(
            strategy_id=self.strategy_id,
            strategy_version=self.strategy_version,
        )

    def semantic_mapping(self) -> dict[str, object]:
        """Return canonical semantic content used for deterministic config identity."""

        return {
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "timeframe_minutes": self.timeframe_minutes,
            "rsi_period": self.rsi_period,
            "rsi_threshold": self.rsi_threshold,
            "rsi_strictly_below": self.rsi_strictly_below,
            "target_r_multiple": self.target_r_multiple,
            "validity_candles": self.validity_candles,
        }

    def identify(self) -> ConfigIdentity:
        """Build the deterministic experimental configuration identity."""

        # This strategy exists only as an architecture/reference fixture. Its
        # config must not be promoted to ACCEPTED by ordinary construction.
        return identify_config(
            self.semantic_mapping(),
            status=ConfigStatus.EXPERIMENTAL,
        )
