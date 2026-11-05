# BTC Momentum Baseline V0 — Validation Contract V0

## Status

**PREDECLARED — TIER-1 RAW DIAGNOSTIC CONTRACT**

- Strategy: `btc_momentum_baseline_v0`
- Strategy version: `0.1.0-experimental`
- Strategy specification: `docs/strategies/btc-momentum-baseline-v0.md`
- Strategy approval: PR #242, merge commit `e9269688345dd54730d43a796e63a1c694a0dcd8`
- Validation authority: SF-094 / GitHub #233
- Data authority: SF-088 / GitHub #225
- Historical execution authority: ADR-011
- Research status: diagnostic only
- Execution-valid status: **No**
- Paper/live promotion authority: **No**

This contract is frozen before inspection of BTC strategy-performance results.

The purpose of the first experiment is to answer:

> Can SignalForge produce trustworthy, reproducible diagnostic evidence for the frozen BTC momentum baseline?

It is not an optimization experiment and does not establish deployment readiness.

## Evidence tier

The first run uses the `RAW_DIAGNOSTIC` evidence tier.

Historical effective-dated Delta BTCUSD tick-size/contract metadata is unresolved. Therefore the
experiment must not claim historical tradable-price normalization or execution-valid fills.

Missing historical tick evidence reduces the strength of conclusions. It must not be replaced by
today's tick size or an invented effective-dated schedule.

A later `EXECUTION_VALID` rerun requires historically attributable effective tick/contract rules
and must use a separately identified execution profile/result.

## Eligible protected source evidence

The first diagnostic experiment is bound to the already-verified SF-088 protected source evidence:

- generation: `generation-0001`
- provider/venue: Delta Exchange India
- instrument: BTCUSD perpetual
- canonical instrument: `DELTA:BTCUSD`
- price basis: traded price
- source resolution: 1 minute
- chronology: timezone-aware UTC
- interval: `[2025-10-30T00:00:00Z, 2026-10-30T00:00:00Z)`
- one-minute observations: 525,600
- completed five-minute observations: 105,120
- source evidence audit: PASS
- two-pass semantic coherence: PASS
- historical tick applicability: `UNRESOLVED`
- five-minute close SHA-256:
  `0787429a8203913b08b954c40d8dc57a0bad0be4b367a7d39580cdaf311733b8`
- logical report SHA-256:
  `8632150c1aa75689cb9b3fd933dc3e3d0672ce7eb31c1772b9597d7ce57b7ff6`

This is a diagnostic evidence identity, not a claim that SF-088 Stage B is execution-qualified.

Any different source interval, semantic candle digest or acquisition generation requires a new
experiment identity and explicit validation-contract amendment before performance inspection.

## Research windows

These windows are frozen before strategy-performance inspection.

### Warm-up / pre-roll

`[2025-10-30T00:00:00Z, 2025-10-31T00:00:00Z)`

This contains 288 five-minute intervals and therefore exceeds the strategy requirement of 250
completed five-minute candles before evaluation.

Warm-up candles may initialize indicators but cannot create measured research trades.

### Measured in-sample diagnostic window

`[2025-10-31T00:00:00Z, 2026-07-01T00:00:00Z)`

No parameter tuning is authorized on this period under the baseline strategy identity.

### Measured out-of-sample diagnostic window

`[2026-07-01T00:00:00Z, 2026-10-30T00:00:00Z)`

The OOS period must not be used for parameter selection, threshold adjustment or success-criterion
redefinition.

The split is deliberately simple and chronological. No walk-forward optimization is introduced in
this first baseline.

## Calculation and provenance identity

The first run must record:

- strategy ID: `btc_momentum_baseline_v0`
- strategy version: `0.1.0-experimental`
- deterministic strategy config hash produced by the implemented SF-095 selection/config path
- engine calculation version: `engine-v1`
- historical simulator calculation version: `historical-bar-execution-v1`
- market/session policy identity for continuous 24x7 operation with no compulsory daily exit
- aggregation/canonicalisation version used to derive five-minute completed candles
- source diagnostic evidence identity listed above
- execution assumption profile ID/version
- explicit `execution_valid=false` or equivalent durable provenance marker

The first performance run is not authorized until SF-095 provides the exact deterministic config
hash and executable strategy registration. Once recorded, the hash must not change within this
experiment identity.

## Execution-assumption profiles

Run and report the profiles separately.

### REFERENCE_RAW / 1.0.0

- raw strategy trigger/stop/target levels
- zero additional slippage
- no historical tick normalization
- execution-valid: **No**

### ADVERSE_RAW / 1.0.0

Predeclared sensitivity assumption:

- long entry fill: **10 basis points adverse** relative to the modeled raw entry fill
- STOP exit fill: **10 basis points adverse** relative to the modeled raw stop exit
- TARGET exit fill: **10 basis points adverse** relative to the modeled raw target exit
- no historical tick normalization
- execution-valid: **No**

Ten basis points per fill is a deliberately adverse diagnostic sensitivity assumption. It is not
claimed to estimate Delta's historical realized slippage.

Post-entry strategy economics must continue to use the modeled actual entry fill: risk is actual
modeled fill minus stop, and target is actual modeled fill plus 1.5R.

## Historical tick-size rule

Historical tick-size applicability is unresolved.

Therefore:

- do not apply current Delta tick size retrospectively;
- do not fabricate an effective-dated historical tick schedule;
- do not claim historically tradable trigger/target prices;
- retain off-current-tick historical source observations as evidence rather than repairing them.

This contract permits raw-level diagnostics only.

## Ambiguity and unresolved policy

Reuse ADR-011 without reinterpretation.

Report separately:

- total actionable opportunities;
- determinate outcomes;
- bounded-ambiguous outcomes;
- unresolved outcomes;
- determinate coverage rate.

Only determinate outcomes enter ordinary point estimates.

Ambiguous and unresolved outcomes must remain visible. They may not be silently dropped or
converted to favourable outcomes.

A position that remains open at dataset end is unresolved. Do not fabricate an exit.

## Required metrics

Report at minimum, separately for each measured window and execution profile:

- actionable opportunity count;
- determinate outcome count;
- bounded-ambiguous count;
- unresolved count;
- determinate coverage rate;
- closed determinate trade count;
- win rate;
- average R / expectancy;
- R-based profit factor;
- maximum drawdown in cumulative R;
- trade frequency;
- exit-reason distribution;
- realised-R distribution;
- holding-time distribution;
- ambiguity/unresolved rate.

Where determinate coverage is below 100%, label performance statistics:

**determinate-subset diagnostic metrics**

Do not imply they represent all actionable opportunities.

## Perpetual economics and interpretation limits

Tier-1 results may report gross price-distance R only.

The first diagnostic contract does not include a complete net-economic model:

- fees: not included unless explicitly added as a separate reported sensitivity
- funding: not deducted from gross R
- spread/slippage: represented only by the declared execution profile
- margin/leverage: not part of normalized R
- liquidation: not modeled

Therefore:

- gross R is not net profitability;
- `PASS_DIAGNOSTIC` is not deployment-relevance PASS;
- no PAPER, Demo/Testnet or live-capital promotion may be justified by Tier-1 alone.

Holding-time distribution must remain visible because the strategy has no maximum holding period
and trades may span funding intervals.

## Out-of-sample discipline

The following are prohibited:

- parameter tuning against the OOS period;
- changing the OOS window after viewing results;
- choosing a different evidence generation because results are preferable;
- changing thresholds and retaining the same strategy/config identity;
- redefining PASS after seeing baseline results;
- reporting the best later configuration as though it were this frozen baseline.

Any material strategy/configuration change requires a new experimental identity and new
predeclared validation contract as appropriate.

## Decision outcomes

The first Tier-1 experiment must conclude exactly one of:

### PASS_DIAGNOSTIC

Reproducible raw-level evidence is sufficiently positive to justify further execution-valid
validation.

This does **not** approve PAPER, Demo/Testnet or live capital.

### FAIL_DIAGNOSTIC

The frozen baseline does not show useful evidence of edge under the predeclared diagnostic
profiles/windows.

No "best configuration" is substituted for the failed baseline.

### INCONCLUSIVE_DIAGNOSTIC

Evidence quality, determinate coverage, effective sample size or unresolved economics prevents a
defensible directional conclusion.

An inconclusive result must remain inconclusive rather than being converted to PASS by post-hoc
parameter selection.

## Implementation gate

SF-095 must complete before the first performance run.

At minimum SF-095 must:

- implement and register the approved strategy;
- preserve the exact normative semantics;
- support continuous 24x7/no-forced-exit historical research;
- support an explicit raw diagnostic execution profile without an invented tick schedule;
- record deterministic config and execution-validity provenance;
- preserve existing execution-valid/NSE behavior.

No strategy-performance result may be inspected as part of SF-095 implementation acceptance.

## Promotion boundary

A `PASS_DIAGNOSTIC` result authorizes only the next research question:

> Is the evidence still credible under execution-valid historical rules and materially complete
> perpetual economics?

Execution-valid validation remains blocked until historically attributable tick/contract metadata
exists.

Paper trading remains downstream of credible historical evidence and the separate SF-092
readiness gates.
