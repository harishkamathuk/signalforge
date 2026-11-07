# SF-258 — Opt-in hypothetical BTC path runner (Stage 5 implementation)

The `signalforge.research.scenario_execution` module implements **one**
explicitly selected research-only scenario, `BTC_OHLC_PATH_V1 /
0.1.0-proposal`. This is an assumption-conditioned counterfactual calculator,
**not a historical execution simulator**. The specification authority is
the merged [SF-254 architecture](../architecture/execution-scenario-modelling-contract-proposal.md),
[SF-255 research methodology](../validation/btc-momentum-baseline-v0-scenario-validation-v0-proposal.md),
and the parent #253 Gate B decision.

## Strict isolation

`ScenarioResearchRunner.run(ScenarioResearchRequest)` is a distinct Python
entry point. It has no broker adapter, no PAPER/live dispatch, no strict CLI
flag and no persistence into authoritative Fill, Position or Trade tables.
`HistoricalBarExecutionRunner`, `FAIL_CLOSED_V1`, `BOUNDED_FLAT_V1` and
NSE execution-valid paths are unchanged. There is **no implicit fallback**
between strict and hypothetical scenario lanes.

Each request must explicitly provide `ScenarioMode.SCENARIO_RESEARCH`,
`ScenarioAssumptionSet.btc_ohlc_path_v1()`, an audited
`RawDiagnosticSource` (or a *synthetic-only* test source), a frozen BTC
strategy selection, the frozen RAW profile, the completed-five-minute
indicator engine version, a provenance revision, UTC frozen research
boundaries, and a finite `ScenarioResourcePolicy`. Synthetic-only strategy
fixture variants also require an explicit identity-bearing
`synthetic_fixture_identity` beginning with `synthetic-`; protected
requests prohibit this test-only field. It rejects unavailable
source evidence, mismatched instruments, strict-mode profile combinations
and unregistered rule or budget variants.

The five registered, **explicitly versioned** subpolicy IDs are:

| Field | ID | Version |
|---|---|---|
| price path | `OPEN_HIGH_LOW_CLOSE` | `1.0.0-proposal` |
| ties | `REJECT_SAME_LEVEL_TIE_V1` | `1.0.0-proposal` |
| gaps | `OBSERVED_OPEN_FIRST_V1` | `1.0.0-proposal` |
| time boundary | `FIVE_MINUTE_EXPIRY_AFTER_FINAL_CLOSE_V1` | `1.0.0-proposal` |
| fill | `RAW_PROFILE_AFTER_BASE_V1` | `1.0.0-proposal` |

## Hypothetical event handling

On each observed one-minute OHLC bar, the **assumed** path visits Open,
High, Low and Close in that order, monotonically traversing intervening
levels. Intermediate crossing order is tagged `ASSUMED` in the trace;
the observed Open is tagged separately. No fractional timestamp, fictitious
tick, market trade, or actual exchange fill is created.

The scenario consumes the existing typed strategy `arm_intent()`,
`armed_policy()` and `post_fill_economics()` interfaces. Entry base is
the first reachable trigger, or the **observed Open** for a gap. RAW
entry-profile slippage applies **once** to that base. The strategy derives
the target from the resulting modeled entry. The first subsequent reachable
stop or target on the assumed path is the modeled close. The conditional R
and bucket-based holding span are not observed profitability or elapsed
sub-minute holding time.

The critical BTC completed-candle boundary is ordered:

1. Process the final constituent one-minute candle through Close.
2. Expire an unfilled prior ARMED setup at its five-minute validity end.
3. Evaluate the newly completed five-minute decision and arm if eligible
   and no OPEN state conflicts.
4. Process the *next* one-minute candle beginning at its observed Open.

This differs from a possible strict-runner boundary ordering; strict code
and original SF-096 evidence **must not be edited or reinterpreted** under
this work item. The scenario carries OPEN state across UTC midnight and
preserves OPEN/ARMED at dataset end without inventing an exit.

A true order-changing same-level tie, in-minute cutoff without defined
precedence, malformed input, unsupported economics, or exhausted resource
budget fails closed. No other OHLC traversal is automatically substituted.

## Identity, storage and interpretation

The input-only `ScenarioExecutionManifest` includes source and content
hash, audited diagnostic identity, derived five-minute close digest,
strategy/config, all five policy versions and their semantic hash, RAW
profile, continuous session, measured boundaries, versioned finite
budgets, calculation and repository revision. Its domain-separated
`scenario_run_id` excludes all *produced* state and result evidence.
The separate `scenario_result_id` is derived after processing.

`ScenarioResearchResult.write_new(path)` exclusively creates a new JSON
file, refusing an existing destination. No default write occurs during
`run()`, and the protected source generation is never modified.

Each outcome carries `SCENARIO_CONDITIONED`; every result carries
`execution_valid=false`. Method validity is **not** performance validity.
Scenario-conditioned point statistics are allowed only after all 69,984
IS and 34,848 OOS frozen measured decision candles are observed, full
source and deterministic checks pass, and the measured unsupported count
is zero. Partial, synthetic or budget-limited calculations remain
`SCENARIO_METHOD_INCONCLUSIVE`, with no unconditional win rate, net
profit or PAPER/live decision.

## Synthetic regression

`tests/unit/research/test_scenario_execution.py` exercises the
registered identities, source gating, assumed entry/stop/target chronology,
single active position, BTC five-minute expiry/new-signal boundary,
profile sensitivity, budget exhaustion, deterministic run/result bytes,
non-overwriting output, and strict namespace isolation. It uses generated
one-minute bars and synthetic strategy decisions only; it never opens
SF-088 or SF-096 protected market archives.

Future Stage 6 historical experiments require a **separate** approval
after Stage 5 code review, CI and FIN. The market-data SF-098 and
possible-worlds #251 workstreams remain independent.
