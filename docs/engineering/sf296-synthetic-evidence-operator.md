# SF-296 — prospective synthetic-only guarded v2 evidence operator (implementation candidate)

**Status:** Work in progress under [#296](https://github.com/harishkamathuk/signalforge/issues/296). This guide is **not** execution authority, an accepted operational assurance record, or economic Gate D. Real operator-host synthetic guarded acceptance and 04 exact-head review are required before SF-296 can pass FIN.

## Scope and proof tiers

The new `scripts/sf296_guarded_v2.py` is a **distinct synthetic-only** operator. It does **not** read protected market source, implement a protected mode, use or alter frozen SF-260 launchers, compute cost-adjusted economics, print results, open OOS evidence, or perform Gate D/E/PAPER/live. It generates artificial traded-price bars from the checked-in public example under an explicit synthetic identity, then invokes the existing verified scenario runner, separate source-quality classifier, independent ADR-011 FAIL_CLOSED_V1 strict producer and SF-283 `scenario-result-v2` writer. The full evidence and producer receipts remain in a private directory.

The subsequent read-only path checks **T1** canonical bytes/identities/strict/source/lifecycle consistency and **T2** controlled operator and private custody lineage. T2 is supported by trusted local code revision, genuine scoped parent/worker invocation and exclusive private receipts, **not** by an independent third-party witness or cryptographic attestation. A malicious user with control of both operator code and custody can forge self-consistent data; no saved-byte hash resolves that trust problem. **T3** historical provider/source validity, historical B3, capital/economic evidence and performance are **NOT PROVEN**.

## Proposed operator-host synthetic acceptance

This is a procedure for a **separately authorised** SF-296 synthetic acceptance run at an operator-controlled Linux/WSL machine. It is **not recorded as executed** merely by publishing this file. Use a clean checkout of the exact proposed PR head; verify real user `systemd-run --scope`, `systemctl --user`, `timeout`, `prlimit`, effective cgroup v2 and private filesystem availability before proceeding. The script denies attempts when required guards are unavailable.

Create a new separate private directory, outside Git and all SF-260/protected trees, with `0700` permissions. For example, within a controlled operator shell (do not reuse a failed attempt directory):

```bash
install -d -m 700 "$HOME/signalforge-private/sf296-synthetic"
python scripts/sf296_guarded_v2.py
python scripts/sf296_guarded_v2.py --run-synthetic \
  --root "$HOME/signalforge-private/sf296-synthetic" \
  --profile REFERENCE_RAW --attempt 1
python scripts/sf296_guarded_v2.py --verify \
  --root "$HOME/signalforge-private/sf296-synthetic" \
  --profile REFERENCE_RAW --attempt 1
```

Only after the first attempt has been independently accepted, optionally exercise `ADVERSE_RAW` in its own new attempt directory under the same synthetic root. Each launch is mutually exclusive; the parent owns a private flock and active-scope marker, starts a named real user-systemd scope with bounded resources, checks the effective worker limits, waits for termination, independently verifies the worker's three persisted files, and commits a same-filesystem **no-replace** complete-set directory. The parent writes a separate durable completion acknowledgement and removes the active marker **only after** the commit is verified. The read-only verifier accepts neither staged nor unacknowledged directories. A persistent marker or uncertain stopped scope must be investigated manually; never auto-delete/overwrite or silently retry.

The operator-visible output is a **single bounded JSON object** with `sf293-slice1-evidence-status-v1` and one of `NON_ECONOMIC_EVIDENCE_VERIFIED`, `WITHHELD`, `VALIDATION_BLOCKED`. A synthetic VERIFIED outcome is explicitly `CONTROLLED_SYNTHETIC_T1_T2_NOT_HISTORICAL`. A WITHHELD outcome denotes authentic yet insufficient source/strict assessment; BLOCKED denotes invalid or uncertifiable evidence/custody. Statuses never carry modeled prices, R, P&L, IS/OOS metrics/masks, private filenames, digests, traces or traceback. No inference of economic benefit is permissible. The default no-argument probe returns a non-economic WITHHELD status without reading evidence.

## Exact acceptance and failure evidence required before FIN

The PR must link exact commit and CI checks, plus **non-mocked real systemd operator-host** parent→worker synthetic evidence. Mocked CI tests are component/composition evidence only. Capture private canonical receipts/hashes within approved custody, sanitized stdout/stderr/log/exit-code fixtures, effective scope controls and explicit `EXERCISED_SYNTHETIC` vs `NOT_PROVEN_FUTURE_PROTECTED` mapping. Confirm both independent producer lineage and no unexpected OOS/economic disclosure; test genuine strict known-zero and eligible cases, early-stop WITHHELD, forged-but-hash-consistent artifacts without T2, missing/swapped/corrupt evidence, permission/symlink/lock/TOCTOU failures and **every** write/fsync/rename/ack/crash edge. Do not copy historic resource ceilings as a demonstrated prospective envelope.

No protected-specific admission/source branch exists here. A later approved protected study requires **new independent protected-path admission verification**, complete preregistered ER/G evidence and explicit 00.01 Gate D. Synthetic SF-296 acceptance alone is not an economic study or Gate D/E approval.

**No implementation readiness claim:** Until real scoped-host proof and independent 04 review pass, treat this PR as **not ready to merge**, even if GitHub CI is green.
