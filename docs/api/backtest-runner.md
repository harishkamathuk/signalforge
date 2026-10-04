# Per-Instrument Backtest Runner

SF-069 exposes deterministic historical backtesting as a research application boundary over the
existing replay runtime.

The backtest runner does not implement strategy logic. It resolves the configured registered
strategy, constructs the canonical `ReplayRuntime`, consumes inputs through
`ReplaySessionClock`, and projects observed lifecycle facts into typed research results.

## Runner

::: signalforge.research.backtest.BacktestRunner

## Run result

::: signalforge.research.backtest.BacktestRunResult

The run result preserves:

- `RunIdentity` and canonical replay source identity;
- strategy/config provenance;
- evaluation, signal, trade, exit and rejection counts;
- final lifecycle state;
- one typed result row per observed logical trade.

## Trade rows

::: signalforge.research.backtest.BacktestTradeResult

Trade rows copy the canonical runtime economics:

- deterministic Trade/Fill/Signal identities;
- actual entry fill;
- stop;
- raw and tradable targets;
- risk per share;
- quantity;
- open/closed state;
- exit reason/fill/time when closed;
- realised P&L and realised R when closed.

An OPEN trade at the end of the requested source remains explicitly OPEN with no fabricated exit
or realised result.

## Entry rejection rows

::: signalforge.research.backtest.BacktestEntryRejection

Canonical filled entries rejected by position mechanics remain explicit research outcomes rather
than being silently dropped.

## Provenance validation

Before replay begins, the runner verifies:

- the instrument belongs to the experiment universe;
- execution and dataset provenance exist for that instrument;
- strategy resolution still matches the experiment's strategy/config identity;
- all supplied market events belong to the requested instrument and dataset range;
- the content-derived replay `source_id` matches the experiment dataset source.

## Non-goals

SF-069 does not implement universe orchestration, analytics, transaction-cost modelling,
optimisation, portfolio interaction, OpenAlgo/live data or alternative strategy semantics.
