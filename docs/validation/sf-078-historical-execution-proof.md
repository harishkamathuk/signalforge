# SF-078 — Historical Execution Validation

## Purpose

This record captures the implementation evidence for SF-078 against ADR-008, ADR-010 and ADR-011.

It is not a strategy-performance result. All historical execution tests use deterministic synthetic
fixtures whose purpose is contract validation only.

## Shared strategy contract

SF-078 replaces strategy-owned ARMED event/time callbacks with one declarative policy:

- `ArmIntent` retains raw trigger, stop and validity;
- `ArmedPolicyIntent` declares optional price invalidation and strategy-specific cutoff;
- shared runtime mechanics evaluate that policy for live/PAPER;
- historical execution consumes the same policy;
- `StrategyEntryFillView` exposes only accepted fill price to post-fill strategy economics.

The shared long-entry policy validator rejects unsupported barrier direction and invalidation at or
above the tradable trigger in both live/PAPER and historical modes.

No persistence schema change is required: recovered Signal + ArmedSetup facts contain the accepted
state from which the registered Strategy deterministically projects its policy.

## Three-strategy-shape proof

### Shape 1 — intraday_momentum_v1 / 1.0.0

Existing semantic-matrix and lifecycle tests preserve:

- signal close × 1.001 raw trigger;
- signal-low stop and pre-entry invalidation;
- immediately-following-candle validity;
- 15:05 IST strategy cutoff;
- 1.5R target from accepted fill;
- live/PAPER trigger/expiry ordering.

### Shape 2 — rsi_mean_reversion_v1 / 1.0.0

Existing semantic-matrix and reference-policy tests preserve:

- signal-close raw trigger;
- signal-low post-entry stop;
- no price-based pre-entry invalidation;
- no earlier strategy cutoff;
- one-following-candle validity;
- 1.0R target from accepted fill.

### Shape 3 — test-only delayed breakout

`tests/unit/research/test_historical_execution.py` exercises a non-production shape with:

- signal close × 1.002 raw trigger;
- independent signal-low stop;
- a separate downward invalidation barrier above the stop and below tradable trigger;
- two-following-candle validity;
- 14:55 strategy cutoff;
- 2.0R target from modeled entry fill.

The fixture is registered only in the test registry and is not added to the production strategy
registry.


### Same-runner contract proof

Both real registered strategies are also executed through
`HistoricalBarExecutionRunner` against the canonical repository historical fixture. That fixture is
not designed to force either strategy into a trade, so trade-shape semantics remain proven by the
shared cross-strategy semantic matrix rather than by weakening accepted strategy parameters.

Together this proves:

- both production/reference registered strategies traverse the same historical runner API;
- their distinct ARMED and post-fill semantics are preserved by shared declarative-contract tests;
- the third test-only delayed-breakout shape exercises the full historical lifecycle with materially
  different trigger/invalidation/validity/cutoff/target structure.

## Provenance identity

The independent review identified and corrected two provenance gaps before merge:

- actionable opportunity identity is now derived from dataset + strategy/config + engine evaluation
  identity and remains stable when only execution assumptions or tick schedules change;
- the overall historical result records both an explicit simulator calculation version and the
  semantic identity of the supplied effective-dated TickSizeSchedule.

This allows SF-080 execution-sensitivity runs to align the same opportunity across zero/adverse
profiles while still producing distinct reproducible result identities.

## Historical execution evidence

The historical runner is separate from the ReplaySource/MarketEvent backtester.

It emits research-only evidence:

- `HistoricalBarReachabilityEvidence`;
- `HistoricalModeledFill`;
- `HistoricalExecutionOutcome`;
- `HistoricalExecutionSummary`;
- `HistoricalExecutionRunResult`.

It does not create `MarketEvent`, `ReplayInput`, PAPER/LIVE `Fill`, PAPER/LIVE `Exit`,
runtime `Trade`, or runtime `Position` facts.

## Golden cases

Deterministic tests cover:

- raw trigger reachable while tick-normalized tradable trigger is not;
- signal-candle constituent minutes cannot trigger post-signal execution;
- intrabar trigger timing remains unknown rather than receiving a fabricated timestamp;
- exact gap entry at bar open;
- later same-bar invalidation cannot precede an exact bar-open entry;
- trigger versus pre-entry invalidation;
- trigger versus stop;
- trigger versus target;
- stop versus target;
- multiple competing actions;
- exact validity-boundary precedence;
- trigger versus strategy cutoff inside a one-minute bucket;
- stop gap-through;
- target gap-through;
- compulsory 15:15 exit;
- attempted entry at the 15:15 boundary;
- missing canonical minute while ARMED;
- missing canonical minute while OPEN;
- non-positive-risk modeled entry rejection;
- unsupported post-fill policy;
- second actionable signal while the single-security lifecycle remains active;
- zero-slippage deterministic execution;
- adverse fixed-bps execution and tick normalization;
- target economics derived from the modeled fill;
- deterministic result identity;
- retained per-bar reachability evidence.

## Ambiguity continuation

A single-path historical run stops after:

- any `UNRESOLVED` lifecycle; or
- bounded ambiguity where supported branches leave different future lifecycle states, such as
  EXPIRED versus OPEN_POSSIBLE.

This prevents later research decisions from depending on an invented branch.

A bounded stop-versus-target outcome may continue because both supported branches close the position;
the economic outcome remains ambiguous and is excluded from determinate-subset point estimates.

## Analytics

Historical summaries are R-based and do not introduce position sizing or portfolio capital.

They report:

- actionable opportunity count;
- determinate / bounded-ambiguous / unresolved counts;
- determinate coverage rate;
- determinate closed trade count;
- determinate-subset win rate;
- determinate-subset expectancy / average R;
- R-based determinate-subset profit factor;
- cumulative-R maximum drawdown.

Ambiguous and unresolved outcomes remain in the evidence and never enter determinate-subset point
estimates.

## Deferred

SF-078 does not add:

- real provider data;
- portfolio/multi-security simulation;
- position-sizing semantics;
- short-side execution;
- brokerage/statutory charges;
- parameter optimisation;
- indicator reseeding after continuity breaks.
