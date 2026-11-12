# Stage 6 released-result validation (SF-278)

This read-only workflow validates the four already released artifacts authorised
by [parent #253](https://github.com/harishkamathuk/signalforge/issues/253#issuecomment-6828627582).
[Issue #278](https://github.com/harishkamathuk/signalforge/issues/278) and
[the #260 runner checkpoint](https://github.com/harishkamathuk/signalforge/issues/260#issuecomment-6830925552)
distinguish runner-reported validity from independent methodology verification.
Later explicit parent decisions govern the older proposal-status headers in the
[accepted methodology](../validation/btc-momentum-baseline-v0-scenario-validation-v0-proposal.md).

The tool never invokes a runner, loads historical source, modifies custody,
creates approvals, releases OOS or changes frozen semantics. Development and
tests use fabricated inputs only. No private artifacts were inspected during
implementation. Operator verification on the four approved released artifacts
remains pending code review. Gate E remains a separate owner decision.

## Operator command after code review

Use an installed SignalForge environment from the reviewed checkout. All input
paths are explicit; there are no private-directory defaults. Supply the existing
four approval records in **REFERENCE 1, REFERENCE 2, ADVERSE 1, ADVERSE 2** order.
The placeholders below must name existing records; do not create replacements.

Use the single combined invocation under [One-time operator invocation](#one-time-operator-invocation-after-code-review) below; do not run a separate preliminary validation.

`CUSTODY_ROOT` is the existing 0700 custody directory. The script reads only
`released/{reference_raw,adverse_raw}-attempt-{1,2}.json`, the corresponding
`receipts/` and `is-qa/` records, and the four explicit OOS records. It does not
open `sealed/`, original manifests, historical launch outputs or SF-088 data.
Every input file requires 0600 permissions; symlink ancestors are rejected.
The released directory must contain exactly the four approved names.

Omit `--output` for JSON on stdout. An explicit output directory must already
exist with mode 0700, outside Git, protected source trees and the custody root.
The report is exclusively created with mode 0600: existing files and symlinks
are never overwritten. Do not redirect stdout over existing evidence. Preserve
the original output when a repeat command reports a collision.

Exit codes: **0 bounded artifact PASS** (validation-only invocation),
**1 INVALID/blocked**, **2 INCONCLUSIVE validation or incomplete requested
research summary**. In combined mode a report may have
`status=INDEPENDENT_VALIDATION_PASS`, `research_summary.status=INCONCLUSIVE`
and exit 2. These are separate scopes, not conflicting verdicts.

## What is verified

- Existing custody canonical parser and domain-separated run/result identities.
- Exact released-byte SHA, approved run ID, reconstructed original input-manifest
  SHA and frozen preregistration; the approved run hash binds the full source,
  config, scenario, profile, session, windows, revision and finite budget mapping.
- Seal receipt identities/size, IS-QA linkage and exact approved IS-QA SHA,
  authentic-decision URL and previously operator-reported local OOS-record SHA.
  Offline local records do **not** authenticate GitHub authorship or prove past
  procedure; the operator must authenticate the actual decision.
- Both attempt SHA values within each profile, with distinct profile identities;
  every attempt is reported, including failures. No attempt selection occurs.
- 69,984 IS / 34,848 OOS runner counters, zero unsupported, replay flag, method
  status and absence of failure/truncation provenance. Counter checks are
  explicitly separate from independent grid verification.
- Saved evidence consistency: attempted/retained counts, finite evidence limits,
  unique opportunities, allowed state/reason pairs, UTC minute bounds, ordered
  entry/exit traces, one OPEN position, blocked-decision causal IDs/time bounds,
  inclusive 1m holding bucket spans and terminal-state agreement. The complete
  history is checked across IS/OOS without resetting at the split or midnight.
  Final OPEN and ARMED states are permitted and carry no fabricated exit/R.
- Failure histories may be withheld by the existing runner while attempted
  counts survive. This is inconclusive evidence, not automatically corruption.
  Source-invalid failures and contradictory saved histories are invalid.

The report contains rule IDs, coverage diagnostics, validator Git revision and
three code fingerprints, source/manifest/run/result/receipt fingerprints and
explicit classifications. It never copies failure messages, opportunity IDs,
prices, trace rows, private paths or point statistics. Serialization is sorted
and timestamp-free; identical inputs and validator checkout produce identical
output. SHA values depend on the established 28-digit canonical decimal context,
which is isolated from ambient caller precision.

## Accepted persisted-v1 evidence scope

The [owner decision #6833739363](https://github.com/harishkamathuk/signalforge/issues/253#issuecomment-6833739363)
and [implementation handback #6833745159](https://github.com/harishkamathuk/signalforge/issues/278#issuecomment-6833745159)
resolve the earlier COR interpretation hold. No retrospective per-decision or
ARMED ledger is required. The earlier claim that v1 cannot pass is superseded.
The accepted [completeness gates §5.1.1](../validation/btc-momentum-baseline-v0-scenario-validation-v0-proposal.md#511-predeclared-completeness-gate)
and mandatory per-window reporting obligations remain unchanged.

The command emits `INDEPENDENT_VALIDATION_PASS` only when **all four** canonical
identities, frozen bindings, source labels, replay pairs, counters, failures and
applicable saved lifecycle checks pass. A matching SHA alone is insufficient.
Missing mandatory persisted fields, impossible counter types/bounds, contradictory
runner VALID assertions or saved states are INVALID. Truthfully reported incomplete
coverage, unsupported cases or budget stops remain INCONCLUSIVE. Rejected entry
attempts never disable validation of later accepted entries. Terminal OPEN/ARMED
remains valid unresolved evidence; it is never force-closed.

Every attempt separates four evidence tiers:

| Tier | Scope |
|---|---|
| Independently checked persisted evidence | Canonical identity/custody/fingerprints, field consistency, saved lifecycle/terminal invariants and repeated result-byte equality |
| Frozen runner assertions | Full-grid evaluation counters, replay flag, unsupported and failure assertions, checked against the frozen gates |
| Previously authorised operator evidence | Original source integrity/no substitution and IS-first procedure reused under Gate D R4, the release decision and the new evidence-scope decision; not a new source audit |
| Not reconstructed | Individual historical decisions and complete unpersisted ARMED causality; hashes do not invent these observations |

`PASS` in an attempt's checks is not by itself a four-artifact independent PASS.
Synthetic mode is conspicuously `SYNTHETIC_TEST_ONLY`, with no real preregistration.
No actual private-artifact result is asserted by development tests.

## Supported conditional summary and remaining mandatory gaps

`--research-summary` includes a separate sanitized summary only after the entire
four-artifact set passes. Any identity/replay/gate failure withholds **all** summary
counts, rather than selectively publishing passing attempts. All four attempt
summaries remain separately labelled; repeat attempts are never summed together.

The supported non-economic findings are:

- IS/OOS expected decision counts and explicitly runner-reported observed counts;
- accepted entry events by their persisted one-minute **entry bucket**;
- exit events by their persisted one-minute **exit bucket**;
- blocked decisions by their persisted **decision interval start**;
- dataset-end OPEN/ARMED counts at the frozen measured end;
- count of closed lifecycles whose persisted entry and exit straddle the split,
  **without allocating their outcome/R to either window**.

Event counts use the registered half-open UTC bounds. An event bucket exactly at
the split is OOS; a decision interval ending at the split has an IS interval start,
consistent with the runner's completed-candle counter ordering. These are explicit
**event time bases, not trade cohorts**. No signal timestamp is inferred for a
rejected attempt and no ARMED entry/exit is fabricated.

Every mandatory cohort-based win rate, expectancy, profit factor, cumulative-R
drawdown, trade frequency, R/holding-span/exit distribution and lifecycle count
without a supported window basis is `UNAVAILABLE`, with a reason distinguishing
missing signal/expiry times, unpersisted per-window corrupt-source/strict-overlap
labels and the lack of an approved
cross-window cohort rule. REFERENCE/ADVERSE and IS/OOS economic comparisons remain
UNAVAILABLE. No substitute full-window economic aggregate is emitted.

Consequently artifact PASS does **not** complete the research report:
`research_summary.status=INCONCLUSIVE`, `point_metrics_allowed=false`. The exact
remaining gap is mandatory per-window lifecycle/performance attribution and any
required per-window corrupt-source/strict-overlap fields not persisted in v1. This implementation neither
chooses a post-hoc cohort rule nor presents UNAVAILABLE as a satisfied obligation.
Gate E and issue completion remain separate.

## One-time operator invocation after code review

Set the six variables below to the **existing** custody root,
four original OOS records and an existing 0700 report directory outside custody,
Git and protected source trees. Paths are operator-specific: do not invent new
approval records or copy private inputs. From the reviewed installed checkout:

```bash
: "${CUSTODY_ROOT:?Set the existing custody root}"
: "${REFERENCE_1_OOS_RECORD:?Set the original REFERENCE attempt-1 OOS record}"
: "${REFERENCE_2_OOS_RECORD:?Set the original REFERENCE attempt-2 OOS record}"
: "${ADVERSE_1_OOS_RECORD:?Set the original ADVERSE attempt-1 OOS record}"
: "${ADVERSE_2_OOS_RECORD:?Set the original ADVERSE attempt-2 OOS record}"
: "${REPORT_DIRECTORY:?Set an existing private report directory outside custody}"
if python scripts/stage6_validate_released.py \
  --root "$CUSTODY_ROOT" \
  --oos-records "$REFERENCE_1_OOS_RECORD" "$REFERENCE_2_OOS_RECORD" \
                "$ADVERSE_1_OOS_RECORD" "$ADVERSE_2_OOS_RECORD" \
  --research-summary \
  --output "$REPORT_DIRECTORY/stage6-persisted-v1-report.json"
then
  stage6_report_exit=0
else
  stage6_report_exit=$?
fi
if [ "$stage6_report_exit" -eq 0 ] || [ "$stage6_report_exit" -eq 2 ]; then
  sha256sum "$REPORT_DIRECTORY/stage6-persisted-v1-report.json"
fi
```

This invokes the validator **once**, reads the four results once each and creates
one exclusive 0600 combined report. Expected exit 2 for an incomplete requested
summary is preserved even if artifact validation passes. On exit 1 retain the
incident/report; a collision never overwrites an older report and must not be
represented as a new run. Record the actual artifact verdict, summary verdict,
validator head/code fingerprints and newly created report SHA in #260, with
operator-attested provenance. No operator invocation occurred in development.

All conclusions remain `SCENARIO_CONDITIONED`, `execution_valid=false`,
`UNQUALIFIED_HISTORICAL_METADATA`. SF-096 remains `INCONCLUSIVE_DIAGNOSTIC`.
Nothing here certifies actual fills, net profitability or PAPER/live readiness.

## Synthetic checks

```bash
pytest -q tests/unit/test_stage6_released_validation.py \
  tests/unit/test_stage6_result_custody.py
```

`--synthetic-test-only` accepts conspicuous synthetic source/strategy identities
and synthetic OOS approval records only. It cannot accept the protected source
or imply a real preregistration. Tests fabricate full-window counters and small
lifecycle histories; they do not claim to simulate the entire historical window.
