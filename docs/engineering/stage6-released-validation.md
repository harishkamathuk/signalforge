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

```bash
python scripts/stage6_validate_released.py \
  --root "$CUSTODY_ROOT" \
  --oos-records "$REFERENCE_1_OOS_RECORD" "$REFERENCE_2_OOS_RECORD" \
                "$ADVERSE_1_OOS_RECORD" "$ADVERSE_2_OOS_RECORD" \
  --output "$REPORT_DIRECTORY/stage6-validation.json"
sha256sum "$REPORT_DIRECTORY/stage6-validation.json"
```

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

Exit codes: **1 INVALID/blocked**, **2 INCONCLUSIVE**. There is currently no path
to exit 0 / `INDEPENDENT_VALIDATION_PASS` using only the v1 evidence. A return of
2 is a recorded limitation, not successful independent methodology validation.

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

## Evidence limitations and research-summary gate

`scenario-result-v1` records **aggregate decision counters**, not the individual
104,832 completed decision observations. Its path traces also lack opportunity
IDs and ARMED creation/expiry records. Outcome identities do not recover the
missing causal history. Consequently the saved artifact alone cannot prove full
per-decision grid coverage or all ARMED transitions/continuity. Repeated identical
bytes and `replay_verified=true` do not independently prove those missing facts.
Rejected entries additionally lack links from ENTRY traces to rejected outcomes.
The original source integrity and IS-first procedure remain reused operator
attestations, as permitted by the parent, rather than a new protected-byte audit.

A result may therefore have `RUNNER_REPORTED_VALID` and PASS on all independently
checkable saved-evidence rules while the overall result remains **INCONCLUSIVE**.
This deliberately follows #278's instruction to disclose required invariants
that cannot be independently checked. It does not impose terminal-flat semantics
or invalidate the historical runner merely for having an incomplete audit schema.

`--research-summary` is a separate sanitized summary-gate response. It returns
`WITHHELD / INDEPENDENT_VALIDATION_PASS_REQUIRED`, with the validation report,
and contains no point metrics. **Conditional economic summary calculation and
REFERENCE/ADVERSE × IS/OOS metric differences remain unimplemented/blocked by
this evidence gap.** This PR must not be described as completing that acceptance
criterion. Do not add an override or retrofit private artifacts. A separately
reviewed evidence disposition is needed before any independent PASS and point
summary can be supported; this work authorises neither a historical rerun nor a
new evidence schema.

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
