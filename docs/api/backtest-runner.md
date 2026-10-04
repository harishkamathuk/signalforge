# Per-Instrument Backtest Runner

SF-069 exposes deterministic historical backtesting as a research application boundary over the
existing replay runtime.

The backtest runner does not implement strategy logic. It resolves the configured registered
strategy, accepts the existing canonical `ReplaySource` protocol, constructs the canonical
`ReplayRuntime`, consumes inputs through `ReplaySessionClock`, and projects observed lifecycle
facts into typed research results.

`InMemoryReplaySource` remains the fixture/small-dataset implementation. The runner does not
require it, so future Parquet-backed or partitioned historical sources can implement the same
`ReplaySource` contract without changing backtest semantics.

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

## Provenance and streaming validation

Before replay begins, the runner verifies:

- the instrument belongs to the experiment universe;
- execution and dataset provenance exist for that instrument;
- strategy resolution still matches the experiment's strategy/config identity;
- the replay source instrument matches the requested instrument;
- the replay source identity matches the experiment dataset source.

During streaming consumption, every canonical replay input is validated against the requested
instrument and dataset range before it reaches business logic. The consumed input count must also
match `ReplaySourceIdentity.event_count`.

A research `source_id` must identify the **exact bounded canonical replay stream** represented by
that source. It must not merely identify a mutable file, Parquet container, table, or broader
unfiltered dataset. This invariant keeps `RunIdentity` tied to the exact historical inputs that
were replayed.

## Historical runtime facts

Historical research supplies `IndicatorContinuity.HEALTHY` for the current canonical-history
contract, but deliberately supplies `feed_state=None`. Live broker/feed health is an operational
runtime concept and is not fabricated for historical data. If historical continuity/data-quality
semantics later become richer, they should enter through an explicit historical-data contract
rather than masquerading as live feed state.

## Non-goals

SF-069 does not implement universe orchestration, analytics, transaction-cost modelling,
optimisation, portfolio interaction, OpenAlgo/live data or alternative strategy semantics.
