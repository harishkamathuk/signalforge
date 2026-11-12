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

Exit codes: **1 INVALID/blocked**, **2 INCONCLUSIVE**. The current implementation does not enable
exit 0 / `INDEPENDENT_VALIDATION_PASS` while the COR interpretation below is
pending. This hold is not a preregistered separate-ledger requirement. A return
of 2 must not be reported as a successful independent methodology validation.

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

## COR #280 — evidence-contract reconciliation

**Status: interpretation pending; no methodology amendment or permission to
publish economics.** Reviewed starting head `531ed562b59e3321f0a560d3f1cef6377afeddfb`.
The working tree and GitHub PR head agreed before changes. The frozen runner is
unchanged from Gate C. No private source or result was accessed.

### Authority and requirements

| Category | Requirement or evidence | Authority |
|---|---|---|
| Accepted before execution | Full grid, no early termination, zero unsupported, verified unchanged source, preserved terminal OPEN/ARMED, deterministic repeatability/provenance | [Accepted methodology §5.1.1](../validation/btc-momentum-baseline-v0-scenario-validation-v0-proposal.md#511-predeclared-completeness-gate), [Gate B](https://github.com/harishkamathuk/signalforge/issues/253#issuecomment-6703184382) |
| Accepted before execution | Continuous IS/OOS lifecycle; source/procedure evidence reuse with explicit operator qualification; two process-isolated attempts/profile | [Methodology §2](../validation/btc-momentum-baseline-v0-scenario-validation-v0-proposal.md#2-frozen-strategy-source-and-sample), [Option A](https://github.com/harishkamathuk/signalforge/issues/253#issuecomment-6727241981), [Gate D R4](https://github.com/harishkamathuk/signalforge/issues/253#issuecomment-6778010311) |
| Existing release authority | Independently check coverage, unsupported, truncation, replay, continuity and terminal reporting before point metrics; local approvals are operator attestations | [Bounded OOS release condition 4](https://github.com/harishkamathuk/signalforge/issues/253#issuecomment-6828627582) |
| Engineering acceptance | Check canonical identities/receipts, methodology fields and relevant saved invariants; disclose any required invariant not independently checkable; separate conditional summary after pass | [#278](https://github.com/harishkamathuk/signalforge/issues/278) |
| Added during implementation | Reconstruct all decisions and every ARMED transition from a separately persisted ledger as a mandatory PASS prerequisite | **No explicit acceptance found. Additional assurance, not a frozen requirement.** |

The architecture/ADR requires causal traces, immutable identities and fail-closed
failure provenance. It does not prescribe a separate persisted per-decision
ledger. Gate C accepted `scenario-result-v1` with aggregate counters and the
existing trace/outcome schema. The original PR's assertion that this extra
ledger was a frozen mandatory gate was too strong and is superseded by this COR.

### Findings disposition

1. **P1 confirmed — mandatory extra assurance:** no cited authority explicitly
   requires the ledger. The unconditional inconclusive rule is an implementation
   hold, not a conclusion compelled by the preregistration. **Owner interpretation
   required before changing the independent-PASS standard:** #278 and the OOS
   decision still require independent checks of required invariants; they do not
   precisely delimit artifact-consistency proof versus full independent causal
   reconstruction. Do not silently treat hashes or runner counters as observations
   of unpersisted decisions.
2. **P1 confirmed — summary incomplete:** `--research-summary` always withholds;
   it is not the requested conditional reporting capability. Existing v1 rows
   support closed R/exit/holding-span and entry/exit timestamps, plus aggregate
   unresolved and blocked counts. Expired/rejected outcomes lack signal/expiry
   timestamps. The cited contracts do not specify entry-, exit- or signal-cohort
   attribution for positions crossing IS/OOS. Full required per-window lifecycle
   reporting cannot be obtained by guessing those missing timestamps. No cohort
   rule, surrogate timestamp or summary bypass is introduced here.
3. **P2 partially confirmed — compatibility:** real-artifact verification remains
   pending the operator, as required; synthetic tests cannot replace it. Routine
   defect confirmed: a REJECTED outcome disabled accepted-entry timestamp and
   one-OPEN checks globally. The correction consumes ordered ENTRY outcomes,
   immediately ends rejected attempts without an accepted fill, and keeps the
   checks active for every accepted entry. New tests feed actual frozen-runner
   mappings from 1,300 fabricated minutes across the registered split, covering
   OPEN/ARMED, expiry, rejected entries, blocked decisions and cross-split closure.
   They neither run nor establish the full historical study.

### Narrow decision packet for owner 00.01

**Recommendation:** interpret the existing gate as independent algorithmic
validation of frozen v1 identity/coverage/replay/lifecycle consistency, combined
with the already accepted source/IS-first operator attestations and explicit
limits. Do not add a mandatory ledger retrospectively. This is clarification of
#278's evidence scope, not an additional research gate or Gate E acceptance.

**Decision requested before implementing PASS/report eligibility:** confirm
whether that bounded evidence scope suffices, or identify the specific accepted
invariant for which independent reconstruction remains mandatory. A refusal or
unknown invariant remains explicitly inconclusive; unchanged hashes alone never
supply missing causal observations. Separately identify an already accepted
per-window attribution rule, or explicitly disposition the v1 fields that cannot
support the required per-window lifecycle summary. Do not repair private evidence
or rerun history to force completion.

The current code retains its fail-closed interpretation hold and the separate
`WITHHELD / INDEPENDENT_VALIDATION_PASS_REQUIRED` summary response until this
material auditability/interpretation issue is settled. It does **not** declare
that v1 can never pass the accepted scientific gate. Confidence is **high** that
no separate ledger was explicitly preregistered; evidence-sufficiency for a full
independent verdict remains ambiguous. #278 stays open; the four-artifact operator
check and conditional report acceptance remain outstanding.

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
