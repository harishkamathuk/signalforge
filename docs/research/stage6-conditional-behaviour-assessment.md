# Stage 6 — Conditional behaviour and evidence-limitations assessment

**Work item:** [#278](https://github.com/harishkamathuk/signalforge/issues/278)  
**Evidence checkpoint:** [#260, one-time persisted-v1 operator validation](https://github.com/harishkamathuk/signalforge/issues/260#issuecomment-6835690400)  
**Authority:** [#253, persisted-v1 evidence scope](https://github.com/harishkamathuk/signalforge/issues/253#issuecomment-6833739363)  
**Validator:** merged PR [#280](https://github.com/harishkamathuk/signalforge/pull/280), operator-reported Git revision `93046b01718b7a9fa573a1b88a7fa2b9e85a8be1`  
**Assessment date:** 2026-11-12  
**Status:** `ARTIFACT_VALIDATION_PASS — NON_ECONOMIC_RESEARCH_REPORT_SUPPORTED — MANDATORY_ECONOMIC_REPORT_INCONCLUSIVE`

## Purpose and evidence boundary

This document assesses **which scientific findings can legitimately be reported** from the existing frozen BTC scenario study. It is not the final quantitative performance report, a fresh audit of source bytes, a new methodological approval, or Gate E acceptance. Its initial version contains no observed historical activity counts beyond the previously released completeness figures; the event counts remain to be extracted from the existing sanitized report under operator control.

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

The merged [Stage 6 validator guide](../engineering/stage6-released-validation.md) and `signalforge.research.stage6_validation.conditional_summary` already support these **non-economic** fields separately for each profile/attempt. Numerical values must be read from `research_summary.attempts` in the existing sanitized private report; none are inferred here.

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

## Mandatory research measures still unavailable

The original [scenario validation contract §§5–7](../validation/btc-momentum-baseline-v0-scenario-validation-v0-proposal.md) requires separate IS/OOS lifecycle and conditional performance reporting. No approved universal attribution rule assigns cross-window trades by signal, entry or exit, and v1 does not preserve every signal or expiry timestamp. Do **not** infer a missing timestamp or silently select a cohort rule after outcomes exist.

Accordingly, the current report marks the affected IS/OOS cohort metrics `UNAVAILABLE`, including win rate, average R/expectancy, R profit factor, cumulative-R drawdown, trade frequency, realised-R distribution, holding-span and exit-reason distributions and unsupported lifecycle/cohort counts. Strict-ambiguity overlaps and per-window missing/corrupt-source counts are also not available in the saved report in the required form. REFERENCE/ADVERSE **economic** differences cannot be established on a consistent required IS/OOS basis.

Even where individual saved closed outcomes contain R, price or holding-span fields, that fact **does not authorise** substituting a full-window economic aggregate for mandatory IS/OOS comparisons. Event counts are not trade cohorts. `UNAVAILABLE` does not satisfy a mandatory reporting requirement. Therefore the research summary remains `INCONCLUSIVE`, notwithstanding the bounded artifact-validation PASS.

## Next allowed step — extract supported counts once, without rerunning validation

Read **only** the existing sanitized report's `research_summary.attempts` data locally. Verify that its SHA still equals the preserved checkpoint SHA before inspecting counts. Extract just per-profile/attempt `windows.IS/OOS.decision_coverage`, `accepted_entry_events`, `exit_events`, `blocked_decision_intervals`, `cross_window_closed_lifecycles` and `dataset_end_unresolved`. Show both attempts, retaining the exact time bases and evidence tiers. Do not read raw `released/` artifacts, invoke the validator again or print economic statistics.

After the operator supplies **only** those approved non-economic counts, add an evidence-bound numeric results section through review; do not manufacture counts from prior metadata. Do not relax research-reporting eligibility. This document may become the reviewed, version-controlled permanent assessment after its documentation PR passes normal review and is merged.

## Outstanding work and disposition

- Preserve #278 **OPEN** until mandatory research-reporting obligations receive an honest, accepted disposition; the current document is not closure evidence.
- Preserve the existing private report unchanged and [#260 checkpoint](https://github.com/harishkamathuk/signalforge/issues/260#issuecomment-6835690400) as the permanent operator-reported artifact-validation evidence.
- Prepare only the scientifically supported conditional behavioural findings; no invented per-window attribution or full-window economic substitutes.
- Do not rerun the historical experiment, introduce new approvals, retune the strategy, alter frozen data or claim Gate E acceptance.

**Current scientific conclusion:** the four scenario artifacts are validated under the approved persisted-v1 evidence scope and allow limited, explicitly time-based conditional activity findings. The mandatory IS/OOS economic research question remains **unanswered** from currently supported evidence.
