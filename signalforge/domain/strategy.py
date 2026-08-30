"""Typed strategy evaluation results and stable decision reasons."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from signalforge.domain.ids import InstrumentId
from signalforge.domain.time import CandleInterval


class DecisionReason(StrEnum):
    """Stable machine-readable strategy decision reason codes."""

    QUALIFIED = "qualified"
    ACTIONABLE = "actionable"
    QUALIFIED_NOT_ACTIONABLE = "qualified_not_actionable"
    TREND_NOT_MET = "trend_not_met"
    MOMENTUM_NOT_MET = "momentum_not_met"
    SETUP_NOT_MET = "setup_not_met"


@dataclass(frozen=True, slots=True)
class TrendResult:
    """Result of the strategy trend component."""

    passed: bool

    def __post_init__(self) -> None:
        if not isinstance(self.passed, bool):
            raise TypeError("TrendResult passed must be a boolean")


@dataclass(frozen=True, slots=True)
class MomentumResult:
    """Result of the V1 momentum component with diagnostic MACD metadata."""

    passed: bool
    rsi_passed: bool
    adx_passed: bool
    macd_signal_positive: bool | None = None

    def __post_init__(self) -> None:
        for name, value in (
            ("passed", self.passed),
            ("rsi_passed", self.rsi_passed),
            ("adx_passed", self.adx_passed),
        ):
            if not isinstance(value, bool):
                raise TypeError(f"MomentumResult {name} must be a boolean")

        if self.macd_signal_positive is not None and not isinstance(
            self.macd_signal_positive, bool
        ):
            raise TypeError("MomentumResult macd_signal_positive must be a boolean when provided")

        if self.passed != (self.rsi_passed and self.adx_passed):
            raise ValueError("MomentumResult passed must equal RSI AND ADX results")


@dataclass(frozen=True, slots=True)
class SetupResult:
    """Result of the strategy setup component."""

    passed: bool

    def __post_init__(self) -> None:
        if not isinstance(self.passed, bool):
            raise TypeError("SetupResult passed must be a boolean")


@dataclass(frozen=True, slots=True)
class StrategyEvaluation:
    """Immutable strategy decision for one instrument and completed candle."""

    instrument_id: InstrumentId
    interval: CandleInterval
    trend: TrendResult
    momentum: MomentumResult
    setup: SetupResult
    qualified: bool
    actionable: bool
    reasons: tuple[DecisionReason, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.qualified, bool):
            raise TypeError("StrategyEvaluation qualified must be a boolean")
        if not isinstance(self.actionable, bool):
            raise TypeError("StrategyEvaluation actionable must be a boolean")

        expected_qualified = self.trend.passed and self.momentum.passed and self.setup.passed
        if self.qualified != expected_qualified:
            raise ValueError("StrategyEvaluation qualified must equal trend AND momentum AND setup")
        if self.actionable and not self.qualified:
            raise ValueError("StrategyEvaluation actionable requires qualified")

        expected_reasons = _expected_reasons(
            trend=self.trend,
            momentum=self.momentum,
            setup=self.setup,
            qualified=self.qualified,
            actionable=self.actionable,
        )
        if self.reasons != expected_reasons:
            raise ValueError("StrategyEvaluation reasons do not match evaluation state")


def _expected_reasons(
    *,
    trend: TrendResult,
    momentum: MomentumResult,
    setup: SetupResult,
    qualified: bool,
    actionable: bool,
) -> tuple[DecisionReason, ...]:
    if qualified:
        if actionable:
            return (DecisionReason.QUALIFIED, DecisionReason.ACTIONABLE)
        return (DecisionReason.QUALIFIED, DecisionReason.QUALIFIED_NOT_ACTIONABLE)

    reasons: list[DecisionReason] = []
    if not trend.passed:
        reasons.append(DecisionReason.TREND_NOT_MET)
    if not momentum.passed:
        reasons.append(DecisionReason.MOMENTUM_NOT_MET)
    if not setup.passed:
        reasons.append(DecisionReason.SETUP_NOT_MET)
    return tuple(reasons)
