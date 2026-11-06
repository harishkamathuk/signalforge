# BTC Momentum Baseline V0 — Scenario-Conditioned Validation Contract Proposal

## Status

**PROPOSED — SPECIFICATION ONLY — NOT APPROVED FOR EXECUTION**

- Owner: 04 — Backtesting & Validation
- Work item: SF-255 / GitHub #255
- Parent decision: SF-253 / #253
- Architecture sibling: SF-254 / #254
- Strategy: `btc_momentum_baseline_v0 / 0.1.0-experimental`
- Frozen strict validation authority: `docs/validation/btc-momentum-baseline-v0-validation-v0.md`
- Historical ambiguity authority: ADR-011
- Proposed architecture vocabulary: PR #256 / SF-254
- Historical source authority remains SF-088 / #225
- Execution-valid status: **No**
- PAPER / Demo / Testnet / live authority: **No**

This document defines a proposed research methodology for a future **scenario-conditioned**
historical study. It does not select an intraminute path, implement a scenario simulator, run
protected evidence, inspect performance, replace SF-096, or authorize any future experiment.

The original SF-096 strict and `BOUNDED_FLAT_V1` evidence remains immutable and
`INCONCLUSIVE_DIAGNOSTIC`.

## 1. Research question and evidence boundary

The proposed future study may answer only this conditional question:

> Under a predeclared, versioned and deterministic historical execution scenario assumption,
> how does the frozen BTC momentum strategy behave on the frozen source and fixed IS/OOS windows?

It must **not** answer:

> What trades actually occurred historically?

or:

> Is the strategy historically profitable or execution-valid?

A scenario is an explicit *if-then model*. The assumed event order is not observed chronology.

### Required evidence taxonomy

The future report must distinguish the following categories exactly unless #254/#253 approves
a replacement vocabulary:

| Label | Meaning | Permitted interpretation |
|---|---|---|
| `OBSERVED_SOURCE` | Canonical provider OHLCV / UTC source facts and audited source identity | Historical source fact |
| `STRICT_INFERABLE` | Lifecycle result invariant under accepted strict ADR-011 semantics | Evidence-inferable historical conclusion |
| `STRICT_AMBIGUOUS` | More than one source-compatible lifecycle remains | Historical ambiguity; no chosen trade |
| `SCENARIO_CONDITIONED` | Result produced only because a declared scenario assumption chooses a deterministic hypothetical ordering | Conditional model result only |
| `SCENARIO_UNSUPPORTED` | The registered scenario cannot resolve a required event or violates its own contract | Explicit model failure / no silent fallback |
| `SOURCE_UNQUALIFIED` | Historical tick, contract or other source qualification remains unresolved | Limits execution-valid claims |

No `SCENARIO_CONDITIONED` output may be relabelled `DETERMINATE`, `observed fill`,
`historical trade`, `execution-valid`, or equivalent.

## 2. Frozen strategy, source and sample

A future scenario study must reuse the frozen strategy without modification:

- strategy: `btc_momentum_baseline_v0`
- version: `0.1.0-experimental`
- long-only;
- completed five-minute decision candles;
- existing EMA/RSI/ADX/MACD requirements;
- raw trigger `signal_close × 1.001`;
- immediately-following-five-minute validity;
- signal-low pre-entry invalidation;
- stop at signal low;
- post-fill target `entry + 1.5R`;
- one ARMED or one OPEN lifecycle;
- continuous UTC 24x7 policy;
- STOP/TARGET exits only;
- no daily forced exit or maximum hold.

No scenario may alter any strategy-owned rule to make the model easier to complete.

### Frozen source identity

Unless a separately approved source amendment occurs before preregistration, the candidate study
must remain bound to the same SF-088 protected `generation-0001` source evidence and diagnostic
dataset identity used by SF-096.

Any future qualified Delta public trade-tape evidence from SF-098 / #252 must be treated as a
**separate evidence input decision**. It may justify cancelling, redesigning or superseding the
scenario study, but it must not be silently substituted after scenario performance has been seen.

### Frozen sample windows

The proposed scenario contract retains the SF-094 windows:

- warm-up/pre-roll: `[2025-10-30T00:00:00Z, 2025-10-31T00:00:00Z)`
- IS: `[2025-10-31T00:00:00Z, 2026-07-01T00:00:00Z)`
- OOS: `[2026-07-01T00:00:00Z, 2026-10-30T00:00:00Z)`

The lifecycle must remain continuous across the IS/OOS boundary. No reset is permitted.

OOS must remain sealed from scenario selection and assumption tuning.

## 3. Preregistration requirements

No historical scenario performance may be executed until a future experiment record freezes all
of the following.

### 3.1 Scenario identity

The exact named/versioned `ScenarioAssumptionSet` must be accepted before results. At minimum its
canonical semantic mapping must include:

- scenario ID and version;
- price-path rule ID/version;
- event-tie policy ID/version;
- gap policy ID/version;
- time-boundary/cutoff policy ID/version;
- fill-application policy ID/version;
- all numeric parameters, if any;
- canonical semantic hash.

A friendly label alone is insufficient.

The actual path rule remains **UNAPPROVED** under this proposal. Examples such as O-H-L-C or
O-L-H-C are alternatives for Gate B consideration, not selected rules.

### 3.2 Calculation identity

Freeze:

- strategy ID/version/config hash;
- source diagnostic ID;
- diagnostic dataset content identity;
- aggregation/canonicalisation identity;
- indicator engine calculation version;
- scenario simulator calculation/version;
- scenario assumption semantic hash;
- market/session identity;
- execution-assumption profile semantic ID;
- measured windows/pre-roll;
- repository revision used for execution;
- `execution_valid=false`.

Any change to one of these items creates a different experiment identity.

### 3.3 Scenario set and sensitivity

The first future experiment should use the **smallest explicitly approved assumption set**.

A single deterministic scenario is preferred for the first increment if Gate B approves it.

If Gate B instead approves multiple fixed scenarios, all scenarios must be registered **before**
any performance output is inspected. No additional path may be added after seeing IS or OOS merely
because the result is attractive or disappointing.

Scenario selection may not depend on:

- OOS performance;
- observed win rate/expectancy/drawdown;
- which model completes more trades;
- which model resolves SF-096 more favourably;
- discretionary inspection of ambiguous cases.

## 4. Execution profiles and economics

The scenario study may reuse the existing raw diagnostic execution profiles only if Gate B confirms
their semantic compatibility:

1. `REFERENCE_RAW / 1.0.0`
2. `ADVERSE_RAW / 1.0.0`

They remain **assumption profiles**, not historical fills.

Historical tick applicability remains `UNRESOLVED`; do not use today's Delta tick retrospectively.

Scenario results must not include net-profitability claims because the frozen baseline does not model:

- fees;
- funding;
- bid/ask spread as a complete historical series;
- margin/leverage;
- liquidation;
- partial fills;
- queue priority.

If any of those are later introduced, they require separately versioned assumptions and a new
preregistered study identity.

## 5. Permissible scenario outputs

For each predeclared scenario/profile/window, report separately:

### 5.1 Coverage and model-completeness evidence

- expected decision candles;
- observed/evaluated decision candles;
- scenario-complete opportunities;
- `SCENARIO_UNSUPPORTED` opportunities;
- strict-ambiguous source opportunities encountered;
- dataset-end conditional OPEN/ARMED count;
- missing/corrupt source count;
- model termination boundary if any;
- coverage rate;
- completeness status.

A completed script does not itself establish a complete experiment.

### 5.2 Conditional lifecycle evidence

Report:

- scenario-conditioned actionable opportunities;
- blocked non-actionable signals;
- scenario-conditioned entries;
- scenario-conditioned closed trades;
- conditional STOP count;
- conditional TARGET count;
- conditional expiry/no-entry count;
- conditional OPEN/ARMED at dataset end;
- strict-reference ambiguity classification for the same source intervals where applicable.

Every scenario trade must carry a model label. A report must not print a table headed simply
"historical trades" where the rows are scenario-conditioned.

### 5.3 Conditional performance metrics

Only if the scenario/window passes the declared completeness gate may the report calculate:

- scenario-conditioned win rate;
- scenario-conditioned average R / expectancy;
- scenario-conditioned R profit factor;
- scenario-conditioned cumulative-R maximum drawdown;
- scenario-conditioned trade frequency;
- scenario-conditioned realised-R distribution;
- scenario-conditioned holding-time distribution;
- scenario-conditioned exit distribution.

Each metric must be named or grouped so that the scenario dependency is visible.

Do not combine scenario-conditioned trades with strict determinate trades into a single
"unconditional" performance denominator.

## 6. Comparison and sensitivity rules

### 6.1 Strict reference remains separate

The future scenario report must preserve the original SF-096 disposition as a separate reference:

`INCONCLUSIVE_DIAGNOSTIC`

Scenario results do not revise that result and must not reuse SF-096's
`PASS_DIAGNOSTIC / FAIL_DIAGNOSTIC / INCONCLUSIVE_DIAGNOSTIC` labels.

### 6.2 Multiple scenarios

If more than one scenario is preregistered, report each separately.

Permitted comparison:

- opportunity-count differences;
- lifecycle-state differences;
- metric differences;
- strict ambiguity intervals affected;
- assumptions that cause the divergence.

Not permitted:

- averaging scenarios into one pseudo-historical win rate;
- weighting scenarios without an independently justified probability model;
- selecting the best or worst model after results;
- claiming the scenario spread is a statistical confidence interval;
- using model agreement as proof that one path was historically observed.

### 6.3 Sensitivity interpretation

A scenario comparison may support statements such as:

> Under both preregistered execution assumptions, the sign of the conditional IS expectancy was the same.

It may not support:

> Historical expectancy was X.

unless separate historically authoritative execution evidence establishes that claim.

## 7. Proposed future-study decision labels

These labels are **proposed for Gate B review** and are deliberately separate from SF-096.

### `SCENARIO_METHOD_VALID`

Use only when all of the following are satisfied:

- preregistration completed before performance inspection;
- source/provenance gates pass;
- deterministic repeatability passes;
- declared coverage/completeness thresholds pass;
- no unapproved assumption substitution occurred;
- required IS/OOS reporting is complete;
- all material scenario dependence is disclosed;
- the study's predeclared research question can be answered under the selected assumption set.

This label means **the scenario study methodology executed successfully**. It does not mean the
strategy is profitable, execution-valid or suitable for PAPER/live use.

### `SCENARIO_METHOD_INVALID`

Use when a declared methodological or reproducibility gate is violated, including:

- preregistration breach;
- deterministic rerun mismatch;
- source identity mismatch;
- unapproved model change;
- OOS leakage;
- result/output provenance corruption.

This label is a **research-process failure**, not a statement that the strategy loses money.

### `SCENARIO_METHOD_INCONCLUSIVE`

Use when the study remains methodologically valid but cannot answer its conditional research
question because of insufficient coverage, unsupported lifecycle cases, unresolved model
semantics, source gaps, or another predeclared stop condition.

### Strategy-performance interpretation is separate

These three labels classify whether the **study method/evidence is valid enough to interpret**, not whether the strategy passed or failed. Do not encode positive/negative conditional performance into them.

If the parent later wants an economic interpretation label, that must be separately preregistered
with explicit numeric/economic criteria and must remain scenario-conditioned. No such threshold is
approved here.

## 8. Stop criteria

The future scenario run must stop or mark the affected scope `SCENARIO_UNSUPPORTED` when:

- the selected scenario has no accepted ordering for a required event tie;
- a timed cutoff/expiry cannot be placed relative to hypothetical price visits without an approved rule;
- gap/fill semantics are not defined by the accepted assumption set;
- source quality is missing/corrupt;
- post-fill economics are invalid;
- resource budgets are exhausted;
- the scenario runner encounters an unsupported strategy shape;
- output would require inventing a provider timestamp/tick;
- the source identity or strategy/config differs from preregistration;
- protected output identity conflicts with an existing result.

No implicit fallback to `FAIL_CLOSED_V1`, `BOUNDED_FLAT_V1`, another scenario, or a favourable
path may be used to finish the study.

## 9. OOS and anti-selection safeguards

Before any scenario performance execution:

1. Freeze the exact scenario assumption set and profile list.
2. Freeze the frozen SF-094 IS/OOS windows unchanged.
3. Record all scenario identities and semantic hashes in GitHub.
4. Record the repository revision and source/dataset identities.
5. Do not inspect OOS scenario metrics until the declared IS workflow and data-quality gates are complete.
6. Do not tune strategy parameters, scenario ordering, slippage or model policies using OOS.
7. Do not remove a scenario because its result is unattractive.
8. Do not add a scenario after observing another model's result unless the original study is closed and a new separately identified preregistered study is created.

The first scenario study is a methodology exercise, not an optimization sweep.

## 10. Provider trade-tape interaction

SF-098 / #252 remains independent.

Before authorizing a future scenario experiment, check the current SF-098 disposition.

If materially better historical trade-level evidence becomes available and is qualified:

- do not silently mix it into this scenario identity;
- assess whether the scenario study is still useful;
- prefer historically stronger evidence for strict chronology where appropriate;
- create a separately identifiable source/experiment contract if the provider evidence changes;
- preserve any already preregistered scenario study as cancelled/superseded if it has not run.

If trade-tape evidence becomes available **after** scenario results exist, compare it only under a
separately approved validation question. Do not retrospectively tune the scenario path to match it.

## 11. Audit and reproducibility checklist

A future sanitized report must allow an independent reviewer to verify:

### Authority

- parent decision / experiment authorization;
- accepted #254 architecture/ADR revision;
- accepted #255 validation revision;
- 01 strategy-owner disposition;
- exact Git revision.

### Inputs

- source generation and source diagnostic ID;
- dataset/content hash;
- provider/venue/instrument/price basis;
- source interval and 1m/5m counts;
- warm-up, IS and OOS bounds;
- strategy ID/version/config hash;
- execution profile IDs/versions;
- scenario assumption ID/version/full canonical mapping/hash;
- simulator and indicator calculation versions;
- market/session identity;
- `execution_valid=false`.

### Reproducibility

- at least two identical executions per declared scenario/profile;
- equal semantic mappings/result IDs;
- equal sanitized result identities;
- protected result-byte equality where protected serialization is part of the approved implementation;
- no overwritten protected prior evidence.

### Reporting

- strict/source/scenario labels visibly separated;
- coverage and unsupported counts;
- conditional opportunity and lifecycle counts;
- conditional metrics only when completeness gates pass;
- IS/OOS separated;
- assumptions and limitations repeated in conclusions;
- no account/PAPER/live claims;
- no raw protected data in GitHub or Drive.

## 12. Independent review requirement

Before any future experiment is authorized:

- architecture and validation contracts must be cross-reviewed for terminology and provenance consistency;
- strategy owner 01 must return one of the parent-defined semantic dispositions;
- parent #253 must explicitly approve Gate B;
- no material model choice may remain implied.

After any future experiment:

- an independent/adversarial review must inspect preregistration compliance, source identity,
  repeatability, coverage, metric labelling and OOS discipline;
- review must distinguish observed facts from scenario-conditioned claims;
- unresolved findings must be corrected or the study remain `SCENARIO_METHOD_INCONCLUSIVE` /
  `SCENARIO_METHOD_INVALID` as applicable.

Author-performed checks alone are not independent approval.

## 13. Cross-contract reconciliation with SF-254

This proposal accepts the following **candidate shared vocabulary** from SF-254 for review:

- `OBSERVED_SOURCE`
- `STRICT_INFERABLE`
- `STRICT_AMBIGUOUS`
- `SCENARIO_CONDITIONED`
- `SCENARIO_UNSUPPORTED`
- `SOURCE_UNQUALIFIED`
- explicit scenario assumption semantic hash;
- separate strict and scenario output/result namespaces;
- no scenario fallback in strict execution;
- `execution_valid=false`.

This validation proposal does **not** approve SF-254's material model choices.

The following remain Gate B decisions:

1. exact first price path rule;
2. single scenario versus fixed preregistered scenario set;
3. monotone interpolation meaning, if any;
4. event-tie precedence;
5. gap handling;
6. cutoff/expiry ordering;
7. scenario fill application interaction with raw profiles;
8. exact completeness thresholds, if stricter than full declared grid;
9. any economic interpretation thresholds;
10. final accepted result/status names.

If #254 changes the taxonomy or typed assumption boundary before acceptance, this document must be
reconciled before Gate B.

## 14. Explicit non-goals

This proposal does not authorize:

- a real historical scenario run;
- any simulator or CLI implementation;
- an implementation issue;
- a chosen OHLC path;
- OOS performance inspection;
- strategy tuning;
- execution-valid historical fills;
- net profitability claims;
- changes to SF-096 evidence;
- #251 possible-world implementation;
- interruption of SF-098;
- PAPER, Demo/Testnet or live trading.

## 15. Gate B exit criteria

SF-255 is ready for parent acceptance only when:

- this proposed validation methodology has been adversarially reviewed;
- #254 terminology/provenance is reconciled;
- the actual scenario assumption set and unsupported cases are explicit;
- the 01 strategy-owner disposition is recorded;
- source-controlled architecture/ADR and validation contract revisions are identified;
- parent #253 explicitly accepts the material assumptions and Gate B.

Until then, this file is a **proposal only** and no historical scenario performance may be executed.
