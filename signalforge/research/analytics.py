"""Deterministic gross research analytics over independent realised backtest trades."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from decimal import Decimal, localcontext
from typing import Literal

from signalforge.research.backtest import BacktestTradeResult


@dataclass(frozen=True, slots=True)
class ResearchAnalytics:
    """Descriptive gross metrics for a deterministic collection of research trades."""

    trade_count: int
    realised_trade_count: int
    open_trade_count: int
    wins: int
    losses: int
    breakeven: int
    win_rate: Decimal | None
    expectancy_r: Decimal | None
    profit_factor: Decimal | None
    gross_profit: Decimal
    gross_loss: Decimal
    gross_pnl: Decimal
    max_drawdown_r: Decimal
    exit_reason_counts: tuple[tuple[str, int], ...]
    economics_basis: Literal["gross"] = "gross"


def calculate_analytics(trades: tuple[BacktestTradeResult, ...]) -> ResearchAnalytics:
    """Calculate exact gross metrics without implying portfolio or net-return semantics."""

    realised = tuple(
        sorted(
            (trade for trade in trades if trade.realised_pnl is not None),
            key=_realised_order_key,
        )
    )
    open_trade_count = len(trades) - len(realised)

    pnls = tuple(_require_realised_pnl(trade) for trade in realised)
    rs = tuple(_require_realised_r(trade) for trade in realised)
    wins = sum(value > 0 for value in pnls)
    losses = sum(value < 0 for value in pnls)
    breakeven = sum(value == 0 for value in pnls)

    realised_count = len(realised)
    win_rate = (
        None
        if realised_count == 0
        else _ratio(Decimal(wins), Decimal(realised_count))
    )
    expectancy_r = (
        None
        if realised_count == 0
        else _ratio(_exact_sum(rs), Decimal(realised_count))
    )

    gross_profit = _exact_sum(tuple(value for value in pnls if value > 0))
    gross_loss = -_exact_sum(tuple(value for value in pnls if value < 0))
    profit_factor = (
        None
        if gross_loss == 0
        else _ratio(gross_profit, gross_loss)
    )

    exit_reasons: Counter[str] = Counter()
    for trade in realised:
        if trade.exit_reason is None:
            raise ValueError("Realised research trade is missing exit reason")
        exit_reasons[trade.exit_reason.value] += 1

    return ResearchAnalytics(
        trade_count=len(trades),
        realised_trade_count=realised_count,
        open_trade_count=open_trade_count,
        wins=wins,
        losses=losses,
        breakeven=breakeven,
        win_rate=win_rate,
        expectancy_r=expectancy_r,
        profit_factor=profit_factor,
        gross_profit=gross_profit,
        gross_loss=gross_loss,
        gross_pnl=_exact_sum(pnls),
        max_drawdown_r=_maximum_drawdown_r(rs),
        exit_reason_counts=tuple(sorted(exit_reasons.items())),
    )


def _realised_order_key(trade: BacktestTradeResult) -> tuple[object, str, str]:
    if trade.exited_at is None:
        raise ValueError("Realised research trade is missing exit timestamp")
    return (
        trade.exited_at,
        str(trade.instrument_id),
        str(trade.backtest_trade_id),
    )


def _require_realised_pnl(trade: BacktestTradeResult) -> Decimal:
    if trade.realised_pnl is None:
        raise ValueError("Expected realised P&L for completed research trade")
    return trade.realised_pnl


def _require_realised_r(trade: BacktestTradeResult) -> Decimal:
    if trade.realised_r is None:
        raise ValueError("Expected realised R for completed research trade")
    return trade.realised_r


def _maximum_drawdown_r(rs: tuple[Decimal, ...]) -> Decimal:
    if not rs:
        return Decimal("0")
    with localcontext() as context:
        context.prec = _exact_accumulation_precision(rs)
        cumulative = Decimal("0")
        peak = Decimal("0")
        maximum = Decimal("0")
        for realised_r in rs:
            cumulative += realised_r
            if cumulative > peak:
                peak = cumulative
            drawdown = peak - cumulative
            if drawdown > maximum:
                maximum = drawdown
        return maximum



_ANALYTICS_RATIO_PRECISION = 28


def _exact_sum(values: tuple[Decimal, ...]) -> Decimal:
    """Sum finite Decimal inputs without ambient-context intermediate rounding."""

    if not values:
        return Decimal("0")
    with localcontext() as context:
        context.prec = _exact_accumulation_precision(values)
        return sum(values, Decimal("0"))


def _exact_accumulation_precision(values: tuple[Decimal, ...]) -> int:
    """Return precision sufficient for exact finite Decimal accumulation."""

    if not values:
        return _ANALYTICS_RATIO_PRECISION
    if any(not value.is_finite() for value in values):
        raise ValueError("Research analytics require finite Decimal inputs")

    highest_adjusted = max(value.adjusted() for value in values if value != 0)
    lowest_exponent = min(value.as_tuple().exponent for value in values)
    exponent_span_digits = highest_adjusted - lowest_exponent + 1
    addition_carry_guard = len(str(len(values))) + 1
    return max(
        _ANALYTICS_RATIO_PRECISION * 2,
        exponent_span_digits + addition_carry_guard,
    )


def _ratio(numerator: Decimal, denominator: Decimal) -> Decimal:
    """Return one canonical 28-significant-digit research ratio."""

    with localcontext() as context:
        context.prec = _ANALYTICS_RATIO_PRECISION
        return numerator / denominator
