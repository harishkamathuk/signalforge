# Research Orchestration and Basic Analytics

SF-070 composes independent SF-069 backtests across one explicit experiment universe. It does not
introduce portfolio capital, ranking, cross-instrument position rules, or alternative strategy
semantics.

## Orchestrator

::: signalforge.research.orchestration.ResearchOrchestrator

Before the first instrument runs, the orchestrator validates that the supplied source mapping
exactly matches the experiment universe and that each source identity matches the corresponding
dataset provenance.

Each instrument then runs independently through `BacktestRunner`. A failure aborts the experiment
and identifies the instrument that failed; SF-070 does not return a partial experiment result.

## Experiment result

::: signalforge.research.orchestration.ExperimentResult

The result contains:

- the canonical ExperimentId;
- deterministic per-instrument BacktestRunResult objects in canonical universe order;
- one typed aggregate trade dataset;
- aggregate descriptive analytics;
- the same core analytics per instrument.

The aggregate trade dataset is ordered by:

1. trade open timestamp;
2. instrument ID;
3. BacktestTradeId.

This ordering is for deterministic dataset representation only.

## Analytics

::: signalforge.research.analytics.ResearchAnalytics

::: signalforge.research.analytics.calculate_analytics

All SF-070 economics are explicitly **gross**. Brokerage, taxes, exchange charges, slippage beyond
the existing paper-fill semantics, and other transaction costs are not deducted.

Finite Decimal sums are accumulated with sufficient local precision to avoid intermediate
rounding. Ratio metrics (win rate, expectancy R and profit factor) use a canonical
28-significant-digit Decimal context, independent of the caller's ambient Decimal context.

### Trade counts

`trade_count` counts every projected trade row, including a trade that remains OPEN at the end of
the requested historical source.

`realised_trade_count` counts only rows with canonical realised P&L/R evidence.

`open_trade_count` counts explicit incomplete OPEN rows. Open rows are not converted into wins,
losses, zero returns, or synthetic exits.

For the first thin vertical, trade frequency is represented by aggregate trade counts,
per-instrument trade counts, and exit-reason distribution. Calendar-normalised frequency metrics
can be added later if experimental evidence requires them.

### Win rate

For realised trades:

```text
win rate = winning realised trades / all realised trades
```

A win has realised P&L > 0. A loss has realised P&L < 0. Realised P&L == 0 is breakeven and remains
in the denominator.

With no realised trades, win rate is undefined and represented as `None`.

### Expectancy / average R

```text
expectancy R = sum(realised R) / realised trade count
```

With no realised trades, expectancy is undefined and represented as `None`.

### Profit factor

Profit factor uses gross realised monetary P&L:

```text
gross profit = sum(positive realised P&L)
gross loss   = absolute value of sum(negative realised P&L)
profit factor = gross profit / gross loss
```

If gross loss is zero, profit factor is undefined and represented as `None`. This includes
zero-trade and all-winning samples. An all-losing sample has profit factor zero.

### Maximum drawdown

SF-070 does **not** construct a portfolio equity curve.

Maximum drawdown is a descriptive R-sequence statistic over independently realised trades ordered
by:

1. exit timestamp;
2. instrument ID;
3. BacktestTradeId.

Starting cumulative R and running peak are both zero:

```text
cumulative R += trade realised R
drawdown R = running peak R - cumulative R
maximum drawdown R = maximum observed drawdown R
```

This gives a deterministic strategy-level adverse-sequence statistic without inventing
cross-instrument capital allocation or simultaneous-position semantics.

### Exit distribution

`exit_reason_counts` records the count of each canonical realised ExitReason.

## Interpretation discipline

SF-070 metrics are descriptive research evidence. They do not establish profitability, approve a
strategy, select securities, or justify parameter changes.

The first vertical deliberately excludes:

- transaction-cost/net-return modelling;
- security ranking;
- portfolio equity/capital allocation;
- point-in-time universe construction;
- parameter sweeps/optimisation;
- ML;
- live/OpenAlgo execution.
