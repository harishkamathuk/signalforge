from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal, localcontext

from signalforge.domain.exits import ExitReason
from signalforge.domain.ids import (
    BacktestRunId,
    BacktestTradeId,
    ExitId,
    ExperimentId,
    FillId,
    InstrumentId,
    SignalId,
    TradeId,
)
from signalforge.domain.money import Price, Quantity
from signalforge.domain.trades import TradeState
from signalforge.research.analytics import calculate_analytics
from signalforge.research.backtest import BacktestTradeResult

BASE = datetime(2026, 1, 2, 10, 0, tzinfo=UTC)


def _trade(
    index: int,
    *,
    pnl: str | None,
    realised_r: str | None,
    instrument: str = "NSE:AAA",
    exit_reason: ExitReason | None = None,
) -> BacktestTradeResult:
    instrument_id = InstrumentId(instrument)
    closed = pnl is not None
    if closed and exit_reason is None:
        exit_reason = ExitReason.TARGET if Decimal(pnl) >= 0 else ExitReason.STOP
    return BacktestTradeResult(
        experiment_id=ExperimentId("experiment"),
        backtest_run_id=BacktestRunId(f"run-{instrument}-{index}"),
        backtest_trade_id=BacktestTradeId(f"research-trade-{instrument}-{index}"),
        trade_id=TradeId(f"trade-{instrument}-{index}"),
        entry_fill_id=FillId(f"fill-{instrument}-{index}"),
        signal_id=SignalId(f"signal-{instrument}-{index}"),
        instrument_id=instrument_id,
        entry_price=Price(Decimal("100")),
        stop_price=Price(Decimal("99")),
        raw_target_price=Price(Decimal("101.5")),
        tradable_target_price=Price(Decimal("101.5")),
        risk_per_share=Price(Decimal("1")),
        quantity=Quantity(10),
        opened_at=BASE + timedelta(minutes=index),
        state=TradeState.CLOSED if closed else TradeState.OPEN,
        exit_id=ExitId(f"exit-{instrument}-{index}") if closed else None,
        exit_reason=exit_reason,
        exit_price=Price(Decimal("101")) if closed else None,
        exited_at=BASE + timedelta(minutes=100 + index) if closed else None,
        realised_pnl=Decimal(pnl) if pnl is not None else None,
        realised_r=Decimal(realised_r) if realised_r is not None else None,
    )


def test_zero_trade_analytics_are_explicitly_undefined_where_required() -> None:
    result = calculate_analytics(())

    assert result.trade_count == 0
    assert result.realised_trade_count == 0
    assert result.open_trade_count == 0
    assert result.win_rate is None
    assert result.expectancy_r is None
    assert result.profit_factor is None
    assert result.gross_profit == Decimal("0")
    assert result.gross_loss == Decimal("0")
    assert result.gross_pnl == Decimal("0")
    assert result.max_drawdown_r == Decimal("0")
    assert result.economics_basis == "gross"


def test_all_win_profit_factor_is_undefined_without_gross_losses() -> None:
    result = calculate_analytics(
        (
            _trade(1, pnl="10", realised_r="1"),
            _trade(2, pnl="20", realised_r="2"),
        )
    )

    assert result.wins == 2
    assert result.losses == 0
    assert result.win_rate == Decimal("1")
    assert result.expectancy_r == Decimal("1.5")
    assert result.profit_factor is None
    assert result.gross_profit == Decimal("30")
    assert result.gross_loss == Decimal("0")
    assert result.max_drawdown_r == Decimal("0")


def test_all_loss_profit_factor_is_zero_and_drawdown_accumulates_r() -> None:
    result = calculate_analytics(
        (
            _trade(1, pnl="-10", realised_r="-1"),
            _trade(2, pnl="-5", realised_r="-0.5"),
        )
    )

    assert result.wins == 0
    assert result.losses == 2
    assert result.win_rate == Decimal("0")
    assert result.expectancy_r == Decimal("-0.75")
    assert result.profit_factor == Decimal("0")
    assert result.gross_profit == Decimal("0")
    assert result.gross_loss == Decimal("15")
    assert result.max_drawdown_r == Decimal("1.5")


def test_mixed_metrics_include_breakeven_in_realised_trade_denominator() -> None:
    result = calculate_analytics(
        (
            _trade(1, pnl="20", realised_r="2"),
            _trade(2, pnl="-10", realised_r="-1"),
            _trade(3, pnl="0", realised_r="0", exit_reason=ExitReason.FORCED_SESSION_EXIT),
            _trade(4, pnl=None, realised_r=None),
        )
    )

    assert result.trade_count == 4
    assert result.realised_trade_count == 3
    assert result.open_trade_count == 1
    assert result.wins == 1
    assert result.losses == 1
    assert result.breakeven == 1
    assert result.win_rate == Decimal(1) / Decimal(3)
    assert result.expectancy_r == Decimal(1) / Decimal(3)
    assert result.profit_factor == Decimal("2")
    assert result.gross_pnl == Decimal("10")
    assert result.exit_reason_counts == (
        ("forced_session_exit", 1),
        ("stop", 1),
        ("target", 1),
    )


def test_analytics_are_independent_of_ambient_decimal_precision() -> None:
    trades = (
        _trade(1, pnl="2", realised_r="0.6666666666666666666666666667"),
        _trade(2, pnl="2", realised_r="0.6666666666666666666666666667"),
    )

    baseline = calculate_analytics(trades)
    with localcontext() as context:
        context.prec = 6
        constrained = calculate_analytics(trades)

    assert constrained == baseline
    assert constrained.expectancy_r == Decimal(
        "0.6666666666666666666666666667"
    )


def test_exact_sums_preserve_small_values_across_wide_exponent_spans() -> None:
    result = calculate_analytics(
        (
            _trade(1, pnl="1E+70", realised_r="1E+70"),
            _trade(2, pnl="1", realised_r="1"),
        )
    )

    exact_total = Decimal("1" + ("0" * 69) + "1")
    assert result.gross_profit == exact_total
    assert result.gross_pnl == exact_total


def test_drawdown_preserves_small_tail_after_wide_exponent_cancellation() -> None:
    result = calculate_analytics(
        (
            _trade(1, pnl="1", realised_r="1E+70"),
            _trade(2, pnl="-1", realised_r="-1E+70"),
            _trade(3, pnl="-1", realised_r="-1"),
        )
    )

    exact_drawdown = Decimal("1" + ("0" * 69) + "1")
    assert result.max_drawdown_r == exact_drawdown


def test_max_drawdown_uses_exit_time_then_instrument_then_research_trade_id() -> None:
    first = _trade(1, pnl="10", realised_r="1", instrument="NSE:BBB")
    second = _trade(2, pnl="-5", realised_r="-0.5", instrument="NSE:AAA")
    third = _trade(3, pnl="-10", realised_r="-1", instrument="NSE:CCC")

    result = calculate_analytics((third, first, second))

    assert result.max_drawdown_r == Decimal("1.5")
