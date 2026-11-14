# SF-260 — 90-day sealed v1 IS-first non-economic QA adapter

**Status:** engineering-only implementation for independent 04 review. **DO NOT
inspect protected historical v1 bytes until a distinct 00.01 inspection
approval after 04 accepts this implementation.** Owner implementation contract:
[#253 comment 6883237655](https://github.com/harishkamathuk/signalforge/issues/253#issuecomment-6883237655).
Research evidence matrix:
[#260 comment 6883058939](https://github.com/harishkamathuk/signalforge/issues/260#issuecomment-6883058939).

## Purpose and exclusions

`scripts/stage6_90d_v1_is_first_qa.py` validates the **existing** four
`SF260_90D_AUDITED_V1` `scenario-result-v1` files without creating any new
historical research outputs. It does not execute scenarios, produce independent
ADR-011 strict classifications, inspect or release OOS economics, publish
profitability, or create v2 artifacts. All v1 bytes, result IDs, frozen
canonical manifests, strategy configuration and four Gate D attempt slots
remain immutable.

The original Stage 6 `stage6_result_custody.py::is_qa` and
`stage6_validate_released.py` are **full-year-specific**. They are not
approved as 90-day IS completeness or OOS-release proof.

## Read boundary

The adapter has two deliberately distinct entry modes:

1. `--synthetic-test-only`: accepts only canonical synthetic-origin manifests
   with explicit `synthetic-` fixture and source diagnostic identities.
   This is the **only mode authorised by the current implementation decision**.
2. Protected mode is **default-deny**. It requires a separate existing 0600
   owner inspection approval record (decision
   `SF260_V1_IS_QA_PROTECTED_READ_ACCEPT`), exact frozen revision,
   source derivation and prereg IDs, and a real parent #253 owner-comment URL
   different from the implementation-authorisation comment. An offline CLI
   can check shape but **cannot authenticate the actual GitHub decision**;
   the operator and 04 must independently verify it before invocation.
   No such post-04 inspection approval has been granted by the implementation
   contract. Do not create a purported approval record without that decision.

Only after separate inspection authority does the adapter authenticate all
four private result sizes/SHA-256 and matching 0600 worker receipts, the
0700 directories, no active marker or partial/failure artifact, and exact
canonical prereg manifest identities. All four byte fingerprints are
authenticated *before* any combined result is decoded. The real historical
fingerprints are frozen in the code, and the two independent attempts must
be identical within profile. Reject missing/renamed/rehashed/partial inputs.

The canonical reader reuses accepted `stage6_result_custody._parse_result`:
its complete canonical type-tagged envelope is decoded inside this bounded
local process (12 MiB cap per result). A wholly streaming lifecycle verifier
would require a larger new parser. No decoded result, trade record, OOS
array, modeled price/R, arbitrary key/value, path, exception text or traceback
may reach stdout/stderr. The allowlisted return is a fixed non-economic
status schema only. The reader validates only supported chronology and
saved-field consistency; this does *not* independently rerun the strategy,
reconstruct 5m bars, prove observed price paths, or qualify real execution.

A legitimate protected-result read must be coordinated independently by 04
following a distinct 00.01 decision; this document is not that authority.

## Supported findings and evidence tiers

- File structure/byte fingerprints, canonical hash identities, frozen run
  mapping and custody: independently recomputed from persisted bytes,
  subject to operator-tier source and approval attestation.
- IS 17,280/OOS 8,640 counters, zero `unsupported`, replay flag, failure,
  terminal/method status: **authenticated runner self-reports** cross-checked
  against fixed contracts, not row-by-row replay or independent strict proof.
- Outcomes/traces/blocked-action counts, timestamp order and supported
  lifecycle constraints: independent **saved-field consistency**, not
  verification of economics or source-specific fills.
- The v1 result contains no independently generated, cryptographically bound
  ADR-011 complete strict 1m eligibility and assessment proof.
  `B3_INDEPENDENT_STRICT_COVERAGE=NOT_ESTABLISHED` is unconditional.
- `economics=WITHHELD`, `oos=SEALED`, `gate_e=NOT_APPROVED`
  are unconditional regardless of other PASS labels.

Never interpret a `SCENARIO_METHOD_VALID` persisted field as independent
source strict acceptance. Incomplete counters may produce `INCONCLUSIVE`
while retaining all release restrictions; malformed evidence or inconsistent
self-claims fails closed.

## Synthetic-only operator example

```bash
python scripts/stage6_90d_v1_is_first_qa.py \
  --results-root /tmp/private-synthetic-90d-qa \
  --synthetic-test-only
```

The root must be a private 0700 directory of four synthetic, separately
private 0700 attempt directories. Each includes original-shaped 0600
`canonical-result.json` and `worker-receipt.json`. This is *not* an
instruction to run on any historical root. The unit/integration suite
constructs these fixtures in temporary private directories.

If authentication or semantics fail, the process returns exit code 2 and
only the fixed generic message
`{"status":"VALIDATION_BLOCKED","economics":"WITHHELD","oos":"SEALED"}`.
No output artifact is written. Inputs are always read-only.

## Review and staged authorisation

1. 02: one scoped PR, synthetic adversarial tests, real CLI-entry integration,
   static and exact-head CI. **NO MERGE under IMP.**
2. 04: independent `REV` against the new exact PR head, with emphasis on
   confidential extraction, malformed bytes, canonical identity, mode
   separation, counters/lifecycle and anti-leak tests.
3. If 04 ACCEPTS, 00.01 must separately authorise precisely scoped protected
   v1 non-economic inspection before any operator uses protected mode.
4. Even after a successful approved inspection, B3 strict independent 1m
   coverage and the prospective future v2 policy remain separate. No OOS
   economic release, Gate E, PAPER/live or capital authority is implied.
