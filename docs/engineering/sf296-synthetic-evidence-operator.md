# SF-296 — prospective synthetic-only guarded v2 evidence operator (implementation candidate)

**Status (20 November 2026):** SF-296 Slice 1 completed a user-reported guarded synthetic WSL run and separate saved-byte verification at pre-COR commit `b1458f29bf131701ceaab27dddb631d668cadfbe`; both returned `NON_ECONOMIC_EVIDENCE_VERIFIED` / exit 0. Read-only private custody modes/presence were also reported. The subsequent F1 lifecycle-verifier correction was independently accepted by 04 at `57ef49bd13f12ee30aff3ccef44b4aa9ecb31017`, with exact-head CI SUCCESS. See [host execution](https://github.com/harishkamathuk/signalforge/issues/296#issuecomment-6900531038), [custody](https://github.com/harishkamathuk/signalforge/issues/296#issuecomment-6901443088) and [04 ACCEPT](https://github.com/harishkamathuk/signalforge/issues/296#issuecomment-7038430083). This guide is not economic Gate D authority or proof of historical source validity. Later documentation-only revisions do not retroactively change the reviewed implementation.

## Scope and proof tiers

The new `scripts/sf296_guarded_v2.py` is a **distinct synthetic-only** operator. It does **not** read protected market source, implement a protected mode, use or alter frozen SF-260 launchers, compute cost-adjusted economics, print results, open OOS evidence, or perform Gate D/E/PAPER/live. It generates artificial traded-price bars from the checked-in public example under an explicit synthetic identity, then invokes the existing verified scenario runner, separate source-quality classifier, independent ADR-011 FAIL_CLOSED_V1 strict producer and SF-283 `scenario-result-v2` writer. The full evidence and producer receipts remain in a private directory.

The subsequent read-only path checks **T1** canonical bytes/identities/strict/source/lifecycle consistency and **T2** controlled operator and private custody lineage under the **trusted single-user local-host model** adopted in [#296](https://github.com/harishkamathuk/signalforge/issues/296). T2 is supported by the known local Git revision, actual guarded parent/worker/producers and private receipts; it is **not** independent cryptographic or privileged attestation. Deliberate coordinated modification of all authority records or verifier code by the trusted operator is expressly OUT OF SCOPE; accidental corruption, mismatched receipts, incomplete commits and unauthorized launch paths must fail closed. **T3** historical provider/source validity, historical B3, capital/economic evidence and performance are **NOT PROVEN**.

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

**Acceptance record:** Owner-reported guarded scoped-host execution and independent persisted verification passed on the pre-COR revision, and 04 accepted the bounded F1 correction at the reviewed head. Final merge eligibility still requires current-head CI, review-thread reconciliation and the repository DoD; do not treat host reports as direct independent telemetry or authorise protected economics.


## Proportionate engineering and commit semantics (owner decision, 15 November 2026)

**SignalForge needs enough governance to protect trading correctness, not so much governance that it prevents us from building the software.** This hobby research system prioritizes deterministic strategy decisions, valid source and cost evidence, reproducible tests, safe execution and durable results. It does not require same-owner malicious-forgery prevention, a remote attestation witness, extra security services or fictional threat scenarios. Routine engineering defects are resolved with tests and review; escalate actual capital/execution correctness, durable-state guarantees and destructive contract changes, not every test design decision.

The exclusive private staging set is fsynced before a single same-filesystem no-replace directory promotion. The parent directory is fsynced, then the parent writes and fsyncs a completion acknowledgement and fsyncs the directory. **Only after those required steps succeed** is commit confirmed. The active marker is removed afterwards as housekeeping; failure to fsync its removal cannot invalidate an already confirmed commit. A marker still present after a crash blocks saved-byte verification and requires manual investigation; an acknowledgement absent or not yet durable cannot be used to claim successful completion. Restart behaviour after storage failure is fail closed, not automatic repair or replay. Completion visibility alone is not proof of historical economic validity.

Two former `xfail` examples were superseded by scoped acceptance decisions: deliberate coordinated owner rewriting of *all* trusted records is out of scope; ordinary unilateral receipt forgery must fail. A failed marker cleanup fsync after the durable commit is not a failed commit; injected earlier write, fsync, rename and acknowledgement failures still must BLOCK.


### WSL scope-controller finding and bounded correction (15 November 2026)

Operator-supplied preflight on WSL Ubuntu / user systemd 255 showed `app.slice` with no `cgroup.subtree_control`, so transient scopes under the default slice lacked `memory.max`, `memory.swap.max` and `pids.max` despite successful launch. A **separate harmless transient scope** using `--slice=sf296-test.slice` showed correctly enforced `MemoryMax=3221225472`, `MemorySwapMax=0` and `TasksMax=64`. The operator therefore now specifies **`--slice=sf296.slice`** with its existing `--user --scope --collect` invocation; it leaves all resource limits and worker-side effective-control checks unchanged. This is a minimal local systemd configuration choice, not a relaxation of safeguards. **The real guarded synthetic workload was subsequently executed by the owner under the corrected dedicated-slice operator (pre-COR head), with success and separate verification reported to issue #296.** Direct transient actual-worker cgroup/RLIMIT snapshots and peak use were NOT CAPTURED. The independent 04 reviewer ruled this telemetry limitation nonblocking under the approved single-user synthetic scope. No root/systemd permanent configuration edits are required.

## Phase C preflight and controlled host procedure (prepared 15 November 2026; subsequent operator-reported run recorded above)

**Execution gate:** Run the read-only preflight first in the intended native Linux/WSL distro. This section records the reviewed script and an operator plan, NOT measured host evidence or permission to ignore a failed prerequisite. Do not start `--run-synthetic` until the preflight outcome is reviewed. Never run these steps against protected sources, SF-260 roots or Windows-mounted /mnt/c custody. The same user owns the clean checkout, guard scope and private synthetic root.

### 1. Read-only operator preflight — no workload launch

In the target WSL/Linux terminal, from the **exact PR-head checkout** (`cd` to the existing repository first):

```bash
set -o pipefail
printf 'repo=%s\n' "$PWD"
git rev-parse --show-toplevel
git rev-parse HEAD
git status --porcelain
ps -p 1 -o comm=
systemd --version | head -n 1
systemctl --user show-environment >/dev/null && echo USER_SYSTEMD_BUS_OK
for tool in systemd-run systemctl timeout prlimit python3 findmnt stat; do
  command -v "$tool" || echo "MISSING: $tool"
done
test -f /sys/fs/cgroup/cgroup.controllers && echo CGROUP_V2_PRESENT
cat /proc/self/cgroup
findmnt -no FSTYPE,TARGET -T "$PWD"
python3 --version
```

Require the exact **separately authorised and recorded** PR-head revision for any new execution; compare `git rev-parse HEAD` against that external record, not a hard-coded hash embedded in this guide (which changes when the guide is updated), **empty** `git status --porcelain`, a real Linux-native checkout, PID 1 systemd, functional `systemctl --user`, installed `systemd-run`, `timeout`, `prlimit`, cgroup v2 and the same Python environment used for validated repository dependencies. `findmnt` must show a suitable native Linux filesystem for both staging and final custody; do not use DrvFs or a network mount. Inspect the private synthetic root's owner, `0700` permissions and available space before a launch. Never paste private receipts/hashes or whole private directory listings into public GitHub comments.

### 2. Reviewed exact script envelope

`scripts/sf296_guarded_v2.py` requests `systemd-run --user --scope --quiet --collect --unit=sf296-<profile>-a<attempt>-<parent PID>.scope`; cgroup properties `MemoryMax=3221225472` (3 GiB), `MemorySwapMax=0`, `TasksMax=64`; `timeout --signal=TERM --kill-after=5s 1200s`; and `prlimit --as=4294967296:4294967296 --fsize=536870912:536870912 --cpu=1200:1200`. Parent waits up to 1245 seconds. Worker checks effective `memory.max`, `memory.swap.max`, `pids.max` and RLIMIT_AS, RLIMIT_FSIZE, RLIMIT_CPU. The numbers are *configuration ceilings*, not proof of sufficient memory for the 1300-bar synthetic fixture or of actual runtime consumption. Record observed host resource peak and stop state privately.

The synthetic request constructs 1,300 artificial 1-minute bars from the checked-in public example with constant `100/100.05/99.95/100` OHLC, explicitly synthetic source identity, `scenario-synthetic` grid, the existing `btc_momentum_baseline_v0` selection and isolated `REFERENCE_RAW`/`ADVERSE_RAW` profiles. The entry point has only `--run-synthetic`, `--verify` and internal-worker modes; no protected data argument is admitted.

**Known compatibility watch:** `_inactive()` requires `systemctl --user show UNIT` to succeed with `ActiveState=inactive` and `SubState=dead|failed`. With `--collect`, some user-systemd configurations remove a transient scope before this query; this is correctly treated as unconfirmed, so the run may BLOCK and retain its active marker. A failed `systemctl` query is **not** positive evidence of inactivity. Diagnose the actual installed systemd behaviour with separate harmless unit preflight before consuming a synthetic attempt; do not weaken the stop invariant or delete a marker to make a run pass.

### 3. Failure behaviour / stop rules

- Invalid command/missing required tools/dirty checkout/private-root violations: one fixed `VALIDATION_BLOCKED` JSON response, exit 1, no synthetic source access; `--help` is not an admitted path. Default no-argument probe is `WITHHELD` exit 2 in a clean checkout.
- Guarded worker failure, timeout, RLIMIT/cgroup failure or scope-stop uncertainty: BLOCKED; any staging remains private, and uncertain active marker is retained. Do not rerun or manually erase it. Any failed attempt requires a *new* authorised attempt after diagnosis, not a retry into the existing directory.
- Parent readback/fsync/rename/ack error before confirmed durable commit: BLOCKED; staged or unacknowledged set is never VERIFIED. Commit uses same-filesystem Linux `renameat2(RENAME_NOREPLACE)`, with root-directory fsync. After confirmed complete-set + ack durability, a cleanup fsync error does not undo successful commit.
- Public stdout is exactly one status JSON line; stderr should be empty; worker subprocess output is redirected to `os.devnull`. This deliberately limits diagnostics: keep host systemd metadata and private receipts in operator custody rather than publishing internal bytes.

### 4. Controlled operator run — ONLY AFTER APPROVED PREFLIGHT

The already-reviewed guide's basic command is retained. Use a new 0700 private root outside the repository and all legacy sources, using a *native Linux filesystem*. The following is a template, not a command executed by ChatGPT:

```bash
# From the verified clean exact-head checkout, after successful preflight.
umask 077
install -d -m 700 "$HOME/signalforge-private/sf296-synthetic"
python3 scripts/sf296_guarded_v2.py
python3 scripts/sf296_guarded_v2.py --run-synthetic \
  --root "$HOME/signalforge-private/sf296-synthetic" \
  --profile REFERENCE_RAW --attempt 1
python3 scripts/sf296_guarded_v2.py --verify \
  --root "$HOME/signalforge-private/sf296-synthetic" \
  --profile REFERENCE_RAW --attempt 1
```

Capture exit codes separately from each command rather than assuming success. Success requires `NON_ECONOMIC_EVIDENCE_VERIFIED` exit 0 from launch and an *independent real process* verification, private complete-set 0700 / files 0600, correct hash/identity/ack links, mandated worker-side effective cgroup/RLIMIT checks and confirmed inactive scope. Capture separate worker/scope telemetry when practical; absence of a retained transient snapshot alone is **not** a new blocker under the independently accepted proportional single-user model, and a separate harmless probe must not be misrepresented as actual-worker telemetry. After complete first-profile evidence, the `ADVERSE_RAW` attempt may be run under its own distinct name using the same verified procedure. Do not automatically rerun a blocked attempt, clear a marker or widen limits.

### 5. Evidence packet / no-go criteria

Record **privately**: host distro + WSL version, systemd version/user bus, native filesystem and repository HEAD/clean status, Python/tool versions; exact commands, profile/attempt, exit code and redacted status; scope identifier and `systemctl --user show` state; effective cgroup memory/swap/tasks and RLIMIT controls, actual peak where measurable, stop confirmation; preserved private worker receipt/parent ack, canonical v2 and two companions and restricted SHA proofs. Public GitHub issue/PR should contain only a sanitised short result and links to approved private evidence, not raw receipts, filenames in private roots, hashes, modeled economics, source candles or OOS details.

**NO-GO:** mismatch with reviewed HEAD, dirty checkout, missing user systemd/cgroup v2/tools, non-native filesystem, unexpectedly public private root, wrong resource ceilings, ambiguous stop, unvalidated receipt/ack, unexpected stdout/stderr/log disclosure, unsupported synthetic profile or any access to protected sources. The separately validated mock-composition CI does not satisfy AC-01. Mapping: `EXERCISED_SYNTHETIC` only for the distinct synthetic-only CLI/worker/producer/custody verifier actually run; `NOT_PROVEN_FUTURE_PROTECTED` for protected-source admission, historical provenance, different resource loads, trading economics/OOS and any actual live/paper path. Independent 04 acceptance of the corrected implementation is recorded above; merge remains a separate FIN/DoD action. No protected execution or economic Gate D permission follows from it.
