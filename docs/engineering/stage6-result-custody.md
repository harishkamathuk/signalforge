# Stage 6 — Independent inputs and sealed-result custody (SF-264)

**Status:** [Gate D owner ACCEPT](https://github.com/harishkamathuk/signalforge/issues/253#issuecomment-6778010311)
was recorded on 2026-11-10 **conditionally**. Protected research execution is
still blocked until the actual guarded launch is verified on the operator's WSL
machine. This document and its tools are not Gate E, historical-fill or PAPER/live
authority.
The 00.01 [solo-developer assurance protocol](https://github.com/harishkamathuk/signalforge/issues/253#issuecomment-6711344205),
as narrowed by the later [Option A decision](https://github.com/harishkamathuk/signalforge/issues/253#issuecomment-6727241981),
allows operator-attested independent **algorithmic** checks without implying
independent human inspection of protected bytes. Stage 6 remains **Level 2 formal
validation**, with one explicit pre-execution Gate D and later Gate E acceptance.
Existing SHA evidence and a byte-verified encrypted external copy may be reused;
neither an extra physical backup nor a second human custodian is a default gate.

This guide covers two standard-library scripts under repository-root `scripts/`:

- `sf260_independent_input_verifier.py`: performs **read-only** protected-source,
  exact private manifest, run/preregistration identity and source-dependent five-minute
  digest verification. It uses its **own** canonical encoder/decoder and no SignalForge imports.
- `stage6_result_custody.py`: accepts an **already-produced** typed canonical
  scenario-result JSON; enforces private non-overwriting local storage, captures a
  SHA-256 receipt, exposes a deliberately narrow **IS grid/QA only** artifact, and
  supports full-result release only against a separate OOS owner decision.
  It never creates results, dispatches the scenario runner, computes point performance,
  contacts a broker/provider, or upgrades data qualification.

## Operator setup / no Python path tricks

Run from an updated, clean `develop` checkout after this PR has been merged. The
original SF-261 artifacts remain outside Git in
`~/signalforge-private/stage6/gate-d-preregistration/`, with directory mode `0700`
and three JSON file modes `0600`. The original SF-088 protected source remains under
`.signalforge-data` and must never be copied to Git. No additional Python package is required.

```bash
cd ~/dev/signalforge
python scripts/sf260_independent_input_verifier.py
```

Default paths match the validated WSL layout; optional `--repo-root`, `--private-dir`
and `--generation-dir` overrides remain available. The original preflight Git SHA
inside `preflight-readiness.json` remains `458ead333e29e51b073c1655acbea5d077d650aa`.
The versioned verifier can run on a *later clean `develop`* only when the approved
Gate C `signalforge/`, BTC strategy/validation and ADR files remain unmodified.
The originally operator-tested standalone verifier has SHA-256
`5c1d6232fb9db038c2de3bb9ee7fb66e522a926b58eeea83891c081c233feadb`;
**this repo-managed revision is a distinct code artifact** and must be retested locally
before attributing protected-source verification to it.

## Resource-only snapshot — allowed during preparation

Prepare a separate directory **outside Git** and `.signalforge-data`:

```bash
umask 077
mkdir -m 700 "$HOME/signalforge-private/stage6/gate-d-custody"
python scripts/stage6_result_custody.py \
  --root "$HOME/signalforge-private/stage6/gate-d-custody" \
  resource-check --min-ram-gib 6 --min-disk-gib 20
```

The `--min-ram-gib 6` and `--min-disk-gib 20` values are **diagnostic
operator choices**, not normative Gate D approval thresholds. Under
[Option A](https://github.com/harishkamathuk/signalforge/issues/253#issuecomment-6727241981),
a 6 GiB free-RAM snapshot failure **alone is not a Gate D blocker**; the
tool's `meets_thresholds=false` and exit code 2 still accurately mean its
*specified* thresholds were not met. Do not relabel the snapshot as a pass.

The operator measured a full-window fabricated 525,600-minute
`run_verified` scheduled-activity probe at **3,034,071,040 bytes (2.826 GiB)
peak RSS**, roughly **178 MiB below** its **3 GiB RSS guard**. A separate
quiet-mode probe peaked at about 2.66 GiB. Both finished, but do **not**
prove worst-case protected-history headroom. The original WSL resource snapshot
reported ~4.67 GiB available RAM and >900 GiB free local disk; this
is observation, not full-run certification. In particular, the full **canonical
result JSON serialization and retention** of the complete high-activity result
were **not** measured; Python object duplication, result bytes, and overlapping
processes could exceed the observed headroom.

**Before Gate D**, 04 must give a defensible evidence-based disposition of this
serialization/peak-memory and bounded abort/recovery risk, and 02 owns any
necessary engineering change. A representative **synthetic-only** full-result
canonicalization/serialization measurement, bounded and process isolated,
is preferred to either assuming success or inflating thresholds. Do not
silently alter frozen `FINITE_FAIL_CLOSED` semantic budgets, runner behaviour,
research identity or allowed windows. This command only reads Linux
`MemAvailable` and filesystem free space; it never reads market
data, events or scenario performance.

## Post-Gate-D custody workflow — **NOT authorised yet**

The steps below describe the **future** workflow only. **Do not run on protected
IS/OOS results before the owner explicitly records `GATE_D_ACCEPT` on #253.**
Synthetic fixtures and tests may exercise the API before then.

1. The execution operator produces each approved **full-window** canonical
   scenario-result JSON with the exact Gate C runner, no IS-only short-cut.
   Two process-isolated `run_verified` invocations per RAW profile remain
   mandatory under #260, each with two in-method deterministic traversals.
2. The custodian checks the actual public GitHub `GATE_D_ACCEPT` decision, writes
   a private 0600 *local record* with `parent_issue=253`, exact `record_url`,
   `decision=GATE_D_ACCEPT`, `preregistration_id` and `execution_revision`.
   **This CLI checks the local record's shape/values but cannot verify GitHub
   authorship or substitute for the owner's genuine decision.**
3. `seal` uses `--source-file`, `--profile`, `--attempt` (1 or 2),
   `--private-manifest` and `--gate-d-record`. The profile's original manifest
   SHA-256, complete typed mapping and domain-separated run ID must agree.
   `sealed/<profile>-attempt-N.json` is an exclusive **0600** full-result copy;
   `receipts/<profile>-attempt-N.json` contains its SHA-256 and run/result IDs.
   **No previous attempt or receipt may be overwritten or silently repaired.**
   Use a new documented custody root if a failed partial operation needs rework.
4. `is-qa` validates the sealed bytes and creates a new, exclusive, explicitly
   whitelisted `is-qa/<profile>-attempt-N.json` with only IS **grid counts**,
   expected count, source identity and source-result SHA. It contains **no OOS
   counters, result arrays, trade economics, result failure explanations,
   conditional point metrics, or outcomes/traces**. This is deliberately more
   restrictive than a full post-Gate-D research report. It is **not** proof of
   full-run methodology sufficiency, IS performance or any OOS conclusion.
5. **Approved Level 2 policy:** the single operator records IS-first QA/review
   and an explicit **OOS release checkpoint** bound to each sealed full-result
   SHA and IS-QA artifact SHA, before viewing OOS performance. This checkpoint
   is not a second default **project-owner research-approval gate** under
   Option A. **Existing CLI limitation:** `oos-release --oos-record` still
   requires a genuine separate parent-issue `OOS_RELEASE_ACCEPT` comment,
   linked through a local record with `parent_issue`, `record_url`,
   `decision=OOS_RELEASE_ACCEPT`, `preregistration_id`, `seal_sha256`,
   and `is_qa_sha256`. The CLI does not
   authenticate GitHub authorship and cannot stop the Linux account owner
   reading the seal. **Do not forge a comment, bypass the CLI, or claim the
   approved simpler checkpoint works with this version.** Before any release
   using this utility, either comply with its genuine existing record rule
   or have 02 separately review and authorise a scoped tooling alignment.
   This outstanding tooling/policy mismatch must be disclosed in the Gate D
   packet. An `OOS_RELEASE_ACCEPT` comment does not substitute for Gate D.
6. A separate reviewed comparison of both independent attempts, complete-grid
   gates, all `SCENARIO_UNSUPPORTED` and result-byte equality is required
   before interpreting *any* scenario-conditioned point statistics; this utility
   does **not** implement those scientific checks and never implies Gate E.

All custody artifacts live outside Git and protected archive trees, under 0700
folders with 0600 files, as enforced by this existing utility. Retain
tamper-evident result hashes and recorded checkpoints. The separately encrypted
USB backup and independent-algorithmic protected source checks have **already
been reported by the operator** in #260; preserve their hashes and evidence
qualification, but **do not mandate another external backup as a ceremony**.
A single operator can change local bytes and records; hashes and backups
support later detection but are **not** segregation of duties. A crash after
writing a seal but before its receipt leaves an orphan and must **block**, not
be silently overwritten/recovered.

### Synthetic-only testing

The repository tests use fabricated canonical result JSON with `synthetic-`
source/strategy identities and conspicuous fake OOS economics, never the protected
SF-088 source. A synthetic `seal` requires `--synthetic-test-only`; that flag
rejects any manifest identifying the actual protected source. Synthetic
`oos-release` still needs a separate local `SYNTHETIC_OOS_RELEASE_TEST` record.

```bash
pytest -q tests/unit/test_stage6_result_custody.py \
  tests/unit/test_sf260_independent_input_verifier.py
```

The custody tool is **preparation engineering only**. It grants neither Gate D
nor protected performance authority, nor qualified historical fills, paper/live
operation, or a change to BTC strategy/model/source/windows/profiles/budgets.


## Guarded historical-launch command (SF-274; operator verification required)

The narrow [SF-274](https://github.com/harishkamathuk/signalforge/issues/274)
launcher binds the **existing** frozen research request and approved private
manifest to external Linux controls. It deliberately runs **one named profile
and attempt per invocation**, never an automatic four-run batch or an IS-only
shortcut. It does not compute/publish point metrics or release OOS.

After a separate **FIN/merge** of the SF-274 implementation, on the *clean
updated* WSL `develop` checkout:

```bash
cd ~/dev/signalforge
python scripts/stage6_guarded_launcher.py --probe
```

This source-free probe uses **the same** `systemd-run --user --scope` /
`timeout` / `prlimit` command builder as the protected worker and checks
inside the cgroup that `MemoryMax=3 GiB`, `MemorySwapMax=0`,
`RLIMIT_AS=4 GiB`, `RLIMIT_CPU<=1800 seconds` and
`RLIMIT_FSIZE<=512 MiB` are effective. The subprocess wall limit is
1,200 seconds with TERM then KILL. This is a **research operator limit**,
not a change to the frozen `FINITE_FAIL_CLOSED` semantic budgets or proof
that actual historical workload fits in memory. Host prelaunch
`MemAvailable` must exceed 3 GiB + 0.75 GiB reserve; the output filesystem
must hold 512 MiB + 256 MiB reserve. No arbitrary 6 GiB RAM threshold.

The script expects the unchanged original private manifests and one operator
record at
`~/signalforge-private/stage6/gate-d-preregistration/gate-d-record.json`
with 0600 permissions and exact values `parent_issue=253`,
`record_url=https://github.com/harishkamathuk/signalforge/issues/253#issuecomment-6778010311`,
`decision=GATE_D_ACCEPT`, frozen `preregistration_id` and frozen
`execution_revision`. The operator must authenticate the GitHub comment;
the script cannot independently validate that comment's author. Original
SF-088 data stays in its protected local generation directory; no alternate
data path is offered. Create the result root in advance, with mode 0700,
outside the Git checkout and protected source:

```bash
umask 077
mkdir -p -m 700 "$HOME/signalforge-private/stage6/gate-d-historical-results"
```

**Future command, only after SF-274 FIN and the WSL operator verifies
the exact scope/probe/failure behaviour, and only under the existing owner
Gate D decision:**

```bash
python scripts/stage6_guarded_launcher.py --run \
  --profile REFERENCE_RAW --attempt 1
```

Run attempts 1 and 2 for each of REFERENCE_RAW and ADVERSE_RAW **sequentially**,
with fresh non-overwriting destinations. The launcher also takes one nonblocking
OS file lock at the shared private result root **before** prelaunch headroom
checks. A second invocation cannot overlap another profile or attempt. While
the worker scope is active, the private root contains a 0600
`.sf274-active.json` marker; it is cleared only after systemd confirms the
scope is inactive/removed. If the parent crashes, the bus cannot be queried,
or termination remains uncertain, the marker **stays** and blocks later runs
even after the file lock is released. On this condition, inspect the named
scope and confirm it is terminated before any manual marker clearance. Do not
remove a marker merely to get another attempt running, or reinterpret an
unknown `systemctl` status as safe termination.

Each launched process checks its own
effective cgroup and rlimits before loading protected history. Source and
strategy/run manifest identity must match the original fixed hashes and frozen
Gate C calculation tree before invoking `run_verified`. Only canonical bytes
and a non-economic digest/size receipt can be promoted to a private
`canonical-result.json` in the isolated attempt directory. Any nonzero,
timeout, memory/file-size limit or incomplete receipt leaves the directory
**quarantined**; never publish partial point performance or rerun selectively.

The launcher **does not automatically seal or release results**. Feed a completed
canonical result exclusively to the existing `stage6_result_custody.py seal`
command with the genuine matching Gate D record and private manifest, then
run its IS-only grid QA. The separate genuine parent
`OOS_RELEASE_ACCEPT` checkpoint must identify the exact sealed and IS-QA
hashes for each released attempt. Gate E acceptance is still separate.
A solo operator can read local bytes; this procedure is tamper-evident,
not independent separation of duties.

**Known limitation:** the parent does not inspect economics and cannot prove
future historical capacity. A cgroup memory stop or other failure must produce
only a resource/integrity failure receipt; a successful canonical write alone
does not establish complete coverage, zero unsupported, result-byte replay
agreement or permission to interpret performance.
