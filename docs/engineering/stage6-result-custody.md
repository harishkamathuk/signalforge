# Stage 6 — Independent inputs and sealed-result custody (SF-264)

**Status:** tooling for preparation and synthetic testing only; **Gate D historical
execution remains withheld** until an explicit separate decision under [#253](https://github.com/harishkamathuk/signalforge/issues/253).
The 00.01 [solo-developer assurance protocol](https://github.com/harishkamathuk/signalforge/issues/253#issuecomment-6711344205)
allows an operator-attested second algorithmic pass but **not** a claim of independent human review.

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

The default safety thresholds are **conventional operator thresholds**, **not** a
proven worst-case upper bound. The earlier WSL snapshot had ~4.4 GiB available RAM,
so a 6 GiB minimum may fail. `CAPACITY_SNAPSHOT_ONLY_NOT_FULL_RUN_CERTIFIED`
means **memory feasibility remains unproved**, even when thresholds pass.
This command reads Linux `MemAvailable` and current filesystem free space;
it does not read market data, model events, or scenario performance. Do not
change the frozen `FINITE_FAIL_CLOSED` run budgets based on resource observations.

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
5. The operator documents the IS QA checkpoint and obtains a distinct genuine
   **OOS_RELEASE_ACCEPT** decision in #253, linked to the exact full-result
   SHA and IS-QA artifact SHA. Only then may `oos-release --oos-record` create
   a new exclusive `released/<profile>-attempt-N.json` full-window copy.
   The local OOS record must contain `parent_issue`, `record_url`,
   `decision=OOS_RELEASE_ACCEPT`, `preregistration_id`, `seal_sha256`,
   `is_qa_sha256`. **The program cannot cryptographically confirm the GitHub
   comment or prevent the Linux account owner reading the sealed file.**
6. A separate reviewed comparison of both independent attempts, complete-grid
   gates, all `SCENARIO_UNSUPPORTED` and result-byte equality is required
   before interpreting *any* scenario-conditioned point statistics; this utility
   does **not** implement those scientific checks and never implies Gate E.

All custody artifacts live outside Git and protected archive trees, under 0700
folders with 0600 files. Keep protected SHA records in a separate evidence log
and byte-verified backup to make a later alteration detectable. A single
operator can change both local bytes and local records; GitHub-published hashes,
external backups and owner decisions create audit evidence, **not** strict
segregation of duties. A crash after writing a seal but before its receipt leaves
an orphan and must **block**, not be silently overwritten/recovered.

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
