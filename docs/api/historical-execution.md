# Historical Bar Execution

SF-078 implements the first deterministic historical execution vertical defined by
[ADR-011](../architecture/decisions/ADR-011-historical-execution-and-ambiguity-semantics.md).

## Boundary

The historical path is deliberately separate from the event/replay backtester:

```text
Canonical historical 1-minute bars
        ↓
deterministic 5-minute completed candles
        ↓
IndicatorEngine
        ↓
registered Strategy
        ↓
declarative ARMED policy
        ↓
bar-evidence execution mechanics
        ↓
historical outcome evidence
        ↓
coverage-aware R summary
```

The historical executor does **not** construct `MarketEvent`, `ReplayInput`, PAPER/LIVE
`Fill`, PAPER/LIVE `Exit`, `Trade` or `Position` facts.

Those are authoritative runtime/execution concepts. Historical execution instead emits research-only
modeled fill and outcome evidence.

## Shared strategy policy

Live/PAPER and historical execution share:

- strategy `ArmIntent` for raw trigger, stop and validity;
- declarative `ArmedPolicyIntent` for optional pre-entry invalidation and strategy-specific cutoff;
- `StrategyEntryFillView` for the accepted entry fill price used by post-fill economics.

The historical path therefore does not duplicate Strategy V1's signal-low invalidation, 15:05 entry
cutoff or 1.5R target formula.

## Time evidence

A one-minute OHLCV bar proves reachability, not intraminute chronology.

- A gap/open execution may use the canonical bucket start as an exact observed boundary.
- Intrabar trigger/stop/target reach retains the one-minute bucket and
  `INTRABAR_UNKNOWN` timing.
- No synthetic timestamp or OHLC traversal is invented.
- A completed signal candle cannot use any of its constituent one-minute bars as later execution
  evidence.

## Trigger normalization

Historical entry eligibility is evaluated against the accepted **tradable trigger after NSE tick
normalization**. Raw trigger remains strategy intent/provenance only.

This matches live/PAPER trigger mechanics.

## Execution assumptions

Every run requires an explicit `HistoricalExecutionAssumptionProfile`.

SF-078 supports:

- a zero-slippage reference profile;
- fixed non-negative Decimal basis-point assumptions independently for entry, stop exit, target exit
  and compulsory exit.

For a long trade, entry slippage is adverse upward and sell-side exit slippage is adverse downward.
The result is normalized to the applicable effective-dated tick rule.

No ambient execution assumption is permitted.


### Execution provenance

Historical result identity records both:

- the execution-assumption profile semantic identity; and
- the semantic identity of the actual effective-dated `TickSizeSchedule` supplied to the run.

The simulator also emits `simulator_calculation_version`. Any future change to historical execution
semantics must bump that calculation version rather than relying only on repository history.

Historical opportunity identity is deliberately independent of the execution-assumption profile and
tick schedule. The same actionable completed-candle opportunity therefore retains one identity across
zero-slippage and adverse execution-sensitivity runs, while the overall run/result identity changes.

## Ambiguity

Results are classified as:

- `DETERMINATE`;
- `BOUNDED_AMBIGUOUS`;
- `UNRESOLVED`.

Examples of bounded ambiguity include trigger versus invalidation, intrabar entry versus an exit
level, and stop versus target in the same one-minute bar.

The executor never chooses stop-first, target-first, O-H-L-C or O-L-H-C.

## Missing execution evidence

If a required canonical one-minute bucket is absent while a setup is ARMED or a modeled position is
OPEN, the lifecycle becomes `UNRESOLVED / MISSING_EXECUTION_EVIDENCE`.

The initial SF-078 runner records that evidence and terminates the run. It does not reseed indicators
or resume later in the same run.

The runner also terminates after any other `UNRESOLVED` outcome, or after a bounded ambiguity whose
supported branches leave different future lifecycle states (for example EXPIRED versus
OPEN_POSSIBLE). Continuing a single simulation path in that case would require inventing which branch
occurred. A bounded stop-versus-target case may continue because every supported branch is CLOSED.

If no lifecycle is active, the existing DATA-004 historical continuity behavior remains fail-closed.

## Research summary

SF-078 does not introduce position sizing or portfolio capital.

Outcome reporting is therefore R-based. It reports:

- total actionable opportunities;
- determinate, bounded-ambiguous and unresolved counts;
- determinate coverage rate;
- determinate closed trade count;
- determinate-subset win rate;
- determinate-subset expectancy/average R;
- R-based profit factor;
- maximum drawdown in cumulative R.

When coverage is less than 100%, these are explicitly **determinate-subset** statistics rather than
whole-strategy performance claims.

## Current scope

The first simulator is intentionally narrow:

- one NSE instrument;
- long-entry lifecycle family;
- one active setup/position;
- price trigger;
- optional downward pre-entry invalidation;
- strategy-specific entry cutoff;
- stop;
- positive-risk target;
- compulsory session exit;
- canonical one-minute historical evidence.

Portfolio sizing, multi-security simulation, short-side execution, scale-in/out, statutory charges,
brokerage and indicator reseeding after a continuity break remain outside SF-078.
