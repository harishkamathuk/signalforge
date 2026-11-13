# SF-283 prospective scenario reportability (future-only)

**Contract:** `scenario-result-v2` / `sf283-contained-gross-r-v1`.
**Authority:** [00.01 D1–D6](https://github.com/harishkamathuk/signalforge/issues/253#issuecomment-6851893449) and [bounded IMP](https://github.com/harishkamathuk/signalforge/issues/253#issuecomment-6852035899).
**Research review:** [04 targeted findings](https://github.com/harishkamathuk/signalforge/issues/283#issuecomment-6851479318).
**Scope:** prospective saved-byte-only research reporting. Frozen Stage 6 and `scenario-result-v1` serialization, identifiers and accepted methodology remain unchanged.

## Persistent artifacts and identities

The existing scenario runner still computes v1 result mappings and `scenario-result-v1` result IDs without the new fields. Its future-only `write_reportable_new(...)` emits an *additional* canonical envelope:

- `manifest`: existing canonical `scenario-manifest-v1`, whose `scenario_run_id` is domain-separated `scenario-run-v1` identity.
- `result`: `schema_version=scenario-result-v2`, `report_contract=sf283-contained-gross-r-v1`, original v1 result fields plus per-outcome future-only fields and the exact two `companion_sha256` entries.
- `scenario_result_id`: domain-separated `scenario-result-v2` content hash of that result mapping.

`signalforge.research.scenario_report_evidence` provides explicit source-grid classification and a strict-reference classification *serialization boundary*. Strict classifications must come from an independent strict diagnostic source; the scenario runner cannot infer them from assumed O-H-L-C paths. The v2 writer binds the companions' byte hashes; the reporter recomputes those SHA-256 values and validates their `scenario_run_id` and `scenario_result_v1_id` before any metrics.

The companion schemas are `scenario-source-quality-v1` and `scenario-strict-reference-v1`. Both declare `producer_id`, `assessment`, counting unit and IS/OOS windows. `NOT_ASSESSED` is not an assessed zero and blocks reporting. Missing, conflicting or unbound diagnostics block the entire mandatory economic report.

**Persistence:** All three outputs are created exclusively; prior evidence cannot be overwritten. No database, v1 migration, run replay or change to strategy semantics is involved.

## D1. Window ownership, cohort accounting

For a completed five-minute decision, `is_start < signal_end <= oos_start` assigns IS and `oos_start < signal_end <= measured_end` assigns OOS. Signal ending exactly at split is IS.

For modeled one-minute entry/exit *bucket starts*, `[is_start, oos_start)` is IS and `[oos_start, measured_end)` is OOS. The minute beginning at split belongs to OOS. These rules intentionally differ because they classify different event types.

Every valid CLOSED opportunity is exactly one of `IS_CONTAINED`, `OOS_CONTAINED`, or `CROSS_WINDOW`; all-CLOSED count reconciles to the sum. A signal ending at split and filling afterward is CROSS_WINDOW even if entry and exit share OOS. CROSS_WINDOW values are preserved diagnostically but **excluded** from both primary economic cohorts. Report explicit cross-window exclusions and the distinct rejected/expired/OPEN/ARMED populations. Excluded trades mean the contained OOS cohort is not automatically an unbiased OOS estimate.

## D2–D4. Metrics and modeled order

Eligible contained CLOSED trades only, finite signed scenario-conditioned **gross modeled R**, no inferred fees/funding/tax/net P&L:

| Metric | Exact prospective contract |
|---|---|
| Win rate | count(R > 0) / N; breakeven included in denominator |
| Expectancy | exact sum(R) / N |
| R profit factor | sum(positive R) / absolute sum(negative R) |
| Cumulative-R maximum drawdown | initial R and peak 0; maximum peak minus later cumulative R, modeled closes ordered by unique persisted 1m exit bucket |
| Frequency | N / expected completed five-minute decisions × 1,000; numerator, expected and observed counts included |
| R distribution | sorted exact finite Decimal multiset |
| Holding-span distribution | sorted inclusive observed one-minute bucket spans, **not** elapsed intraminute duration |
| Exit distribution | counts for allowed modeled CLOSED STOP/TARGET reasons |

**Saved action/economic reconciliation:** The prospective saved-byte reader validates
the persisted `trace` (minute bucket, ordered crossing action, opening/assumed
ordering and modeled base) against the saved lifecycle. Each modeled ENTRY is
matched with a filled OPEN/CLOSED opportunity or the attempted entry of a
REJECTED one. Filled entry and exit prices must reconcile with the trace
crossing level under the saved RAW profile slippage (including observed-open
gaps); STOP/TARGET matches the corresponding CLOSED exit bucket/reason;
PRE_ENTRY_INVALIDATION matches the EXPIRED terminal bucket. Non-event
`ASSUMED_SEGMENT` records remain explicitly hypothetical, never observed
provider event times. `event_count` must equal the number of crossing actions
and `attempted_trace_count` must equal the full saved trace length. A fully
rehashed contradictory trace or counter withholds the entire report. This
establishes *consistency of saved evidence*, not independent verification of
assumed OHLC prices against unavailable bars.

**Expiry diagnostics:** For each signal cohort the report includes
`expiry_reasons_by_signal_window` with `VALIDITY_WINDOW_END`,
`STRATEGY_CUTOFF` and `PRE_ENTRY_INVALIDATION` counts (including zero).
A separate `expiry_reasons_by_terminal_event_window` report classifies
their persisted UTC terminal boundary into half-open IS/OOS intervals; an
expiry exactly at `measured_end` is explicitly `AT_MEASURED_END`, not
silently assigned to OOS. These are distinct signal-decision and terminal
boundary counting units, not modeled entry/exit events.

No CLOSED trades makes win rate/expectancy/PF `UNDEFINED:NO_CLOSED_TRADES`; nonempty cohort without negative R makes PF `UNDEFINED:NO_LOSING_R`. Empty otherwise complete cohort has drawdown `0 R` with `EMPTY_COHORT`, zero frequency if expected decisions >0, empty valid distributions. A zero expected-grid denominator yields `UNDEFINED:NO_MEASURED_DECISIONS`. Ratio output uses deterministic Decimal precision 28. Missing mandatory data yields whole-report `WITHHELD`, not point metrics with a guessed zero.

D3 **bounded uniqueness proof (current runner):** `ScenarioResearchRunner.run`
holds one `work.active` opportunity. `_walk_bar` processes that setup before
the completed five-minute decision; `_step` records a CLOSED outcome and
clears `work.active`, then returns without rearming during that one-minute
bar. `_arm` runs only after a later completed five-minute candle is processed,
so the next opportunity's earliest modeled action is in a subsequent one-minute
bucket. Consequently two distinct CLOSED opportunities cannot share one exit
1m bucket under the frozen runner. S13 tests two distinct real-runner closes
and separately rehashes an invented equal-bucket saved result to demonstrate
fail-closed rejection. No ordinal is necessary; if the runner's lifecycle
changes, this D3 argument must be revisited rather than inventing a tie-breaker.
This is not an assertion about observed intraminute chronology.

## D5. Source/strict evidence

Source-quality units: canonical **one-minute source bucket**; mutually exclusive primary classifications `VALID/MISSING/CORRUPT/REPAIRED/SUBSTITUTED`. Per-window primary counts must sum to the expected one-minute interval grid.
Each companion also saves an interval-indexed compact disposition sequence
(`V/M/C/R/S`), in canonical 1m grid order; the saved-byte reader recomputes
and reconciles all category counts rather than trusting summary claims. An unlocatable corrupt raw row cannot be silently assigned to a source bucket: its assessment is `NOT_ASSESSED` until independently resolved. Any missing/corrupt/repaired/substituted measured source invalidates performance eligibility.

Five-minute expected/observed decision counts are separate from one-minute source counts. Strict-reference ambiguity is a distinct independently produced classification over canonical one-minute interval IDs; each window reports a canonical 1m assessed-interval mask, explicitly assessed eligible count,
unique ambiguous keys and denominator. The saved reader rejects inconsistent masks,
duplicate/out-of-window ambiguity keys and ambiguity outside the assessed set. Scenario assumed trace is not proof of observed intraminute sequence. Both companions are independently hash-bound by the result and must be present.

## D6. Versioning and safety

Existing `ScenarioOutcome.mapping()`, `ScenarioResearchResult.mapping()`, `ScenarioResearchResult.result_id` and `write_new()` continue to produce the original v1 bytes and hashes. New v2 outcome fields are emitted **only** through `prospective_mapping()` and `write_reportable_new()`. The future v2 report is never used to reclassify Stage 6.

No protected historical execution, data qualification, SF-096/SF-098 reinterpretation, PAPER/live readiness, net profitability or Gate E approval is conveyed.

## Read-only CLI

After independently producing exact source and strict companions and creating a future v2 canonical result, invoke:

```bash
python scripts/scenario_report_saved.py \
  --result /private/prospective/result-v2.json \
  --source-companion /private/prospective/source-quality.json \
  --strict-companion /private/prospective/strict-reference.json
```

The CLI reads **only these three serialized files**, recomputes their bindings, and prints a complete structured research report to stdout. It does not access runtime bars, source archives, frozen custody, broker systems or a strategy. To compare separate qualified REFERENCE and ADVERSE models, supply all three additional
`--other-result`, `--other-source-companion`, and
`--other-strict-companion` arguments. The CLI requires matching non-fill
scenario provenance, distinct recognized profile identities, individual reporting
eligibility, and prints `REFERENCE_RAW - ADVERSE_RAW` without pooling repeats.
The default one-profile report includes `OOS - IS` conditional differences with
typed undefined propagation.

Exit status `0` is a structurally complete conditional report; exit `2` prints sanitized `WITHHELD`, with no partial metrics or exception/path leakage. Operator control of sensitive output is still required; the CLI does not make protected publication permissible.

**Do not run the above example against protected/historical data without separate owner authorization.**

## Synthetic acceptance and engineering gates

S01–S16 are implemented under `tests/unit/research/test_scenario_execution.py`, including real synthetic runner → two independently saved companions → v2 canonical result → saved-byte-only reconstruction, replay identity, cohort attribution, zero denominators, independently produced strict synthetic diagnostics, invalid source WITHHELD and incompatible saved-data negatives.

S06 must represent `STRATEGY_CUTOFF`, `VALIDITY_WINDOW_END` and `PRE_ENTRY_INVALIDATION` from actual runner outcomes, without modifying the old v1 validator's allowlist.

S15 also uses a supported trade-rich **real-runner** synthetic fixture with
four modeled closes (IS `+1.5R, -1R`; OOS `-1R, -1R`). After canonical
serialization and discarding the retained result, the saved-only reader must
match an independently handwritten expected table for win rate, negative
expectancy, finite profit factor including a zero-winning cohort, modeled
drawdown, exit/R/holding distributions, source/strict 1m evidence, 5m frequency,
lifecycle counts and OOS–IS differences. S16 mutates the trace and counters
while recomputing every affected canonical hash to prove whole-report
withholding on contradictory persisted events. S06 verifies all three
expiry-reason cohorts and their separately classified terminal boundaries.

04 independently reviews research definitions and test oracles. Normal PR DoD requires Ruff, strict mypy, MkDocs, pytest and adversarial/third-party review; this implementation is **not** merge-eligible merely because code was committed.
