# Stage 6 — Conditional behaviour and evidence-limitations assessment

**Work item:** [#278](https://github.com/harishkamathuk/signalforge/issues/278)  
**Evidence checkpoint:** [#260, one-time persisted-v1 operator validation](https://github.com/harishkamathuk/signalforge/issues/260#issuecomment-6835690400)  
**Authority:** [#253, persisted-v1 evidence scope](https://github.com/harishkamathuk/signalforge/issues/253#issuecomment-6833739363)  
**Validator:** merged PR [#280](https://github.com/harishkamathuk/signalforge/pull/280), operator-reported Git revision `93046b01718b7a9fa573a1b88a7fa2b9e85a8be1`  
**Assessment date:** 2026-11-12  
**Status:** `ARTIFACT_VALIDATION_PASS — NON_ECONOMIC_RESEARCH_REPORT_SUPPORTED — MANDATORY_ECONOMIC_REPORT_INCONCLUSIVE`

## Purpose and evidence boundary

This document assesses **which scientific findings can legitimately be reported** from the existing frozen BTC scenario study. It is not the final quantitative performance report, a fresh audit of source bytes, a new methodological approval, or Gate E acceptance. It includes operator-extracted, report-hash-verified non-economic event counts from the already preserved sanitized report. These are descriptive scenario outputs, not IS/OOS trading-performance cohorts.

The only protected-study report referenced is the **existing**, privately retained, one-time combined validation result. SHA-256:

`4bb682e01eeed829eb7d148f2807ee80b651e5e74e4b3eedbd9df5be92b279b5`

Do not commit, copy, overwrite, regenerate or publicly paste the report or protected raw artifacts. A report SHA documents its identity, not independently witnessed provenance.

The source SF-088 remains `UNQUALIFIED_HISTORICAL_METADATA`, model outcomes are `SCENARIO_CONDITIONED`, and `execution_valid=false`. No observed historical fills, profitability, executable economics or PAPER/live suitability is established. SF-096 remains `INCONCLUSIVE_DIAGNOSTIC`.

## What the existing evidence establishes

The operator reported exactly **one** supported combined validation invocation on 2026-11-12T20:51:31Z, with report mode 0600 and CLI exit 2:

| Scope | Recorded result | Evidence tier |
|---|---|---|
| Overall persisted-v1 artifact validation | `INDEPENDENT_VALIDATION_PASS` | Bounded independent saved-artifact checks plus accepted runner/operator evidence |
| REFERENCE_RAW attempts 1 and 2 | Both PASS; identity PASS; byte repeatability PASS | Validated saved identity/repeatability |
| ADVERSE_RAW attempts 1 and 2 | Both PASS; identity PASS; byte repeatability PASS | Validated saved identity/repeatability |
| Measured IS decision grid, each attempt | 69,984/69,984 | Runner-reported coverage checked against persisted counters |
| Measured OOS decision grid, each attempt | 34,848/34,848 | Runner-reported coverage checked against persisted counters |
| Unsupported decisions | Zero per attempt | Runner-reported field checked against the frozen gate |
| Research summary | `INCONCLUSIVE`; `MANDATORY_WINDOW_METRICS_UNAVAILABLE` | Separate reporting-sufficiency verdict |
| Point metrics | `point_metrics_allowed=false` | Explicit withheld reporting gate |

The validated v1 fields and custody identities are not a full causal reconstruction of every decision or ARMED transition. Source integrity and IS-first procedure reuse the previously authorised operator-qualified evidence; they were not independently reaudited from protected source during this assessment. The combined CLI exit 2 reflects incomplete requested research reporting, **not** a four-artifact validation failure.

## Reportable conditional activity — event-time basis, not trade cohorts

The merged [Stage 6 validator guide](../engineering/stage6-released-validation.md) and `signalforge.research.stage6_validation.conditional_summary` already support these **non-economic** fields separately for each profile/attempt. The numeric counts below were read by the WSL operator from `research_summary.attempts` in the original sanitized private report after verifying its recorded SHA-256. No raw historical result files were opened for this assessment.

| Measure | Permissible time basis | Interpretation |
|---|---|---|
| Accepted entry events, IS/OOS | Persisted 1m entry bucket in half-open UTC window | Number of modeled accepted ENTRY events occurring in each window; **not** IS/OOS trade cohorts |
| Exit events, IS/OOS | Persisted 1m exit bucket in half-open UTC window | Number of modeled exits occurring in each window; **not** an exit-cohort performance metric |
| Blocked actionable decision intervals, IS/OOS | Persisted completed-decision interval start in half-open UTC window | Counts of actionable decisions blocked by an active position/setup |
| Closed lifecycles crossing the split | Persisted entry before split and exit at/after split | Boundary-spanning closed positions; no allocation of outcome or R to either window |
| Dataset-end OPEN and ARMED | Frozen measured-end boundary | Unresolved conditional lifecycle counts, never force-closed |
| IS/OOS decision coverage | Frozen runner-observed counters | Methodological coverage; not a profitability statistic |

A bucket exactly at the IS/OOS split belongs to OOS for entry/exit event counts. A decision interval ending at the split has an IS interval start. These are explicitly declared **event timestamps**, not a retroactive signal-, entry- or exit-cohort convention for trade performance.

For reproducibility display both fixed attempts per profile. If the canonical bytes remain equal within each profile, one **predeclared** attempt (for example attempt 1) may stand for its profile's *descriptive* result; do not add repeated attempts together as independent activity, select the best result or average them as distinct experiments. The two RAW profiles remain separate scenario execution assumptions.

## Operator-extracted numerical findings (non-economic)

**Provenance:** On 2026-11-12 the operator locally checked SHA-256 `4bb682e01eeed829eb7d148f2807ee80b651e5e74e4b3eedbd9df5be92b279b5` on the existing sanitized report and supplied the following permitted counts from `research_summary.attempts`. The figures below are **operator-reported sanitized output**, not fresh independently witnessed source bytes or an additional validation run. Decision coverage is runner-reported and checked by the bounded validator.

| Profile | Attempt | IS decisions | IS entry events | IS exit events | IS blocked intervals | OOS decisions | OOS entry events | OOS exit events | OOS blocked intervals |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| REFERENCE_RAW | 1 | 69,984/69,984 | 730 | 730 | 1,616 | 34,848/34,848 | 296 | 296 | 843 |
| REFERENCE_RAW | 2 | 69,984/69,984 | 730 | 730 | 1,616 | 34,848/34,848 | 296 | 296 | 843 |
| ADVERSE_RAW | 1 | 69,984/69,984 | 655 | 655 | 1,988 | 34,848/34,848 | 275 | 275 | 980 |
| ADVERSE_RAW | 2 | 69,984/69,984 | 655 | 655 | 1,988 | 34,848/34,848 | 275 | 275 | 980 |

Every attempt also reports **zero** closed lifecycles crossing the IS/OOS split, **zero** unresolved dataset-end `OPEN`, and **zero** unresolved dataset-end `ARMED`. These are observed saved-result counts under the frozen scenario; they do not prove that all missing signal/expiry attribution fields can be reconstructed.

**Descriptive sensitivity, comparing one matching result per fixed profile (attempt 1 for each):**

- REFERENCE_RAW records **75 more IS accepted entry events** (730 vs 655) and **21 more OOS accepted entry events** (296 vs 275) than ADVERSE_RAW. Counts of exit events differ by the same amounts.
- ADVERSE_RAW records **372 more IS blocked decision intervals** (1,988 vs 1,616) and **137 more OOS blocked intervals** (980 vs 843) than REFERENCE_RAW.
- Across the two measured periods together, REFERENCE_RAW has **1,026** accepted entry events versus **930** for ADVERSE_RAW; ADVERSE_RAW has **2,968** blocked intervals versus **2,459** for REFERENCE_RAW. These totals sum supported **event counts**, **not** trades assigned to a cohort, return, drawdown or profitability.
- The attempt-2 figures exactly match attempt 1 within each profile, consistent with the independently verified canonical byte equality. Attempts are **not** doubled in the profile comparisons.

These figures describe differences in conditional modeled activity under the two registered execution profiles. They are **not** evidence that REFERENCE_RAW makes more money or that ADVERSE_RAW loses money. The zero cross-window closed-lifecycle count does **not** supply absent signal/expiry timestamps, an approved cohort attribution rule, or other mandatory reporting fields.

## Mandatory research measures still unavailable

The original [scenario validation contract §§5–7](../validation/btc-momentum-baseline-v0-scenario-validation-v0-proposal.md) requires separate IS/OOS lifecycle and conditional performance reporting. No approved universal attribution rule assigns cross-window trades by signal, entry or exit, and v1 does not preserve every signal or expiry timestamp. Do **not** infer a missing timestamp or silently select a cohort rule after outcomes exist.

Accordingly, the current report marks the affected IS/OOS cohort metrics `UNAVAILABLE`, including win rate, average R/expectancy, R profit factor, cumulative-R drawdown, trade frequency, realised-R distribution, holding-span and exit-reason distributions and unsupported lifecycle/cohort counts. Strict-ambiguity overlaps and per-window missing/corrupt-source counts are also not available in the saved report in the required form. REFERENCE/ADVERSE **economic** differences cannot be established on a consistent required IS/OOS basis.

Even where individual saved closed outcomes contain R, price or holding-span fields, that fact **does not authorise** substituting a full-window economic aggregate for mandatory IS/OOS comparisons. Event counts are not trade cohorts. `UNAVAILABLE` does not satisfy a mandatory reporting requirement. Therefore the research summary remains `INCONCLUSIVE`, notwithstanding the bounded artifact-validation PASS.

## Evidence retention and future research boundary

The **read-only extraction is complete**. Its permitted counts are recorded above; do not rerun the validator, reparse protected results or create another private report. The source sanitized report remains private and unchanged; its SHA identifies the supporting evidence. Numeric presentation and interpretation in this documentation PR still require normal adversarial review, documentation checks and merge evidence.

Further required IS/OOS cohort economics cannot be obtained merely by reformatting these event counts. Any change to the scientific question or window attribution would require explicit separate methodological authority; it is not assumed here.

## Outstanding work and disposition

- Preserve #278 **OPEN** until mandatory research-reporting obligations receive an honest, accepted disposition; the current document is not closure evidence.
- Preserve the existing private report unchanged and [#260 checkpoint](https://github.com/harishkamathuk/signalforge/issues/260#issuecomment-6835690400) as the permanent operator-reported artifact-validation evidence.
- Prepare only the scientifically supported conditional behavioural findings; no invented per-window attribution or full-window economic substitutes.
- Do not rerun the historical experiment, introduce new approvals, retune the strategy, alter frozen data or claim Gate E acceptance.

**Current scientific conclusion:** the four scenario artifacts are validated under the approved persisted-v1 evidence scope and allow limited, explicitly time-based conditional activity findings. The mandatory IS/OOS economic research question remains **unanswered** from currently supported evidence.
