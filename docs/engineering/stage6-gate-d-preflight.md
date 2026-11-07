# Stage 6 Gate D preflight — preparation only (SF-261)

**Purpose.** The repository-root script **scripts/stage6_gate_d_preflight.py**
is an operator-controlled, read-only check of the protected SF-088
**generation-0001** source and the **input-only** frozen BTC scenario manifest
required by Stage 6 Child D [#260](https://github.com/harishkamathuk/signalforge/issues/260).
The governing parent [#253](https://github.com/harishkamathuk/signalforge/issues/253)
has authorised **preparation only**, not historical scenario performance.
This script is not an execution or backtest command.

## Before running

Use the validated local WSL workstation, not CI or a fixture environment.
The complete original protected archive must already exist at:

    .signalforge-data/sf088/evidence/evidence-only/generation-0001

Use a clean **develop** checkout containing the merged SF-261 PR. The tool
verifies that all interpretation-sensitive Gate C source/specification
files are identical to the accepted scenario implementation revision
**5d2812d11f8f5f061a1b637726f9e73b488c6e43**. A subsequent merge
commit adding this script is permitted; a changed strategy, audit, schema or
scenario calculation is not.

The code uses the existing audit_generation, explore_generation,
load_sf095_raw_diagnostic_source and one-minute-to-five-minute
aggregation contracts. They may read protected OHLC and compute diagnostic
source digests, but **must not** run scenario trade lifecycles or inspect
performance.

Create a fresh private output directory **outside the repository and the
entire .signalforge-data tree**. For example:

~~~bash
mkdir -m 700 /tmp/signalforge-stage6-preflight-001
python scripts/stage6_gate_d_preflight.py \
  --generation-dir "$PWD/.signalforge-data/sf088/evidence/evidence-only/generation-0001" \
  --output-dir /tmp/signalforge-stage6-preflight-001
~~~

Only use this command on a clean develop checkout with access to
the real protected source. The script rejects a symlinked generation path,
symlinked or publicly readable output directory, dirty working tree,
non-ancestor Gate C revision, altered calculation/contract files and any
source identity/count/hash mismatch.

## Outputs and handling

The output directory receives three **exclusive, private 0600** files:

- **reference_raw-input-manifest.json** — canonical, type-tagged
  input-only manifest plus deterministic scenario_run_id.
- **adverse_raw-input-manifest.json** — the separately frozen adverse-profile
  manifest and scenario_run_id.
- **preflight-readiness.json** — sanitized source identity, audit,
  inventory-before/after fingerprint, counts, input SHA-256 values and
  immutable preregistration identity.

**No source OHLC values, raw archive files, scenario opportunities, actual
trades, results, win rates or OOS metrics are produced.** The full
input-only manifests remain *private* until reviewed for sensitive
provenance; only approved sanitized fields/digests may be copied into
GitHub. Do not upload protected archive files.

The script uses the current accepted private _manifest(...) builder
**directly**, with typed frozen source/strategy/assumptions/profiles,
without importing or invoking ScenarioResearchRunner.run or
run_verified. This dependency is intentionally pinned by the strict
Git-diff check and must be reassessed if the merged schema changes.

## What a successful script does **not** prove

A successful invocation proves only that the locally accessible source
and input manifests passed the declared **pre-performance** checks. It
does **not** prove that a future full run is resource-feasible,
repeatable, complete, zero-unsupported, economically correct, or
execution-valid. It does not enforce or independently attest OOS
quarantine or provide a human reviewer.

Before returning a Gate D packet to conversation 00 / parent #253,
record separately:

1. An independent review of the local source hashes and manifest IDs.
2. Named protected-output custodian, write-once location and storage
   capacity, role-based OOS sealing/release and an IS QA checkpoint.
3. Synthetic or non-performance resource feasibility and deterministic
   replay **plan**, with exact frozen budgets and later two-process
   per-profile procedure.
4. Current SF-098/#252 disposition and any stronger qualified source
   implications.
5. The exact manifest/revision, remaining blockers and the requested
   research-only historical execution scope.

The preflight always labels **gate_d_approved=false**,
**gate_d_ready=false**, **execution_valid=false**. A separate explicit
**Gate D ACCEPT** decision by 00 is necessary *before* any protected
historical scenario performance on IS **or** OOS.

## Fail-closed and reproducibility rules

The script never downloads provider data, repairs candles, normalises
historical ticks, changes the frozen strategy or writes under SF-088 or
SF-096. It detects source inventory differences across its own reads.
An existing output file is a hard failure; rerun in a new private
directory and preserve the failed attempt as evidence when appropriate.

The inventory SHA-256 is a new, deterministic per-file-path/size/content
encoding used for **before/after comparison in this invocation**; it
is **not** the same hashing method as the earlier recorded SF-096
inventory digest. The latter must not be treated as directly comparable.
The original provisional 5m-close digest also differs from the
scenario manifest config hash of five-minute closes: do not equate them
merely because both describe the same source.

See [the accepted scenario runner operator boundary](scenario-research-runner.md)
and the immutable predeclared [scenario validation methodology](../validation/btc-momentum-baseline-v0-scenario-validation-v0-proposal.md).
