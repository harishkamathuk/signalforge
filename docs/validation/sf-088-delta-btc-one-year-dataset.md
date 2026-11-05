# SF-088 — Delta BTCUSD One-Year Research Dataset

SF-088 acquires and freezes one year of Delta Exchange India BTCUSD one-minute traded-price
history for SignalForge's personal/internal academic research workflow.

It does **not** define or evaluate a BTC strategy.

## Frozen dataset window

- instrument: `DELTA:BTCUSD`
- provider product: `BTCUSD`
- price basis: traded
- source resolution: one minute
- canonical chronology: continuous UTC
- start inclusive: `2025-10-30T00:00:00Z`
- end exclusive: `2026-10-30T00:00:00Z`
- expected one-minute intervals: `525600`
- deterministic request chunk size: at most `2000` minutes
- expected deterministic chunks per complete pass: `263`

The window is frozen for acquisition/coverage reasons before strategy outcome inspection.

## Historical product metadata applicability

The acquisition command requires Delta product `created_at` and `updated_at` evidence.

A single product metadata rule is accepted only when:

1. the product existed before the research window; and
2. the captured provider `updated_at` predates the research start.

If Delta reports a product update after the research start, SF-088 stops rather than applying
today's tick/contract metadata retrospectively. An explicit effective-dated metadata schedule would
then be required.

The product semantic identity must also match across both full acquisition passes.

## Protected local evidence

Raw Delta responses and canonical market data must stay outside Git.

Use a local ignored directory, for example:

```bash
mkdir -p .signalforge-data/sf088/evidence
mkdir -p .signalforge-data/sf088/store
```

The acquisition path is write-once/resumable. Existing chunk evidence is verified and reused;
it is never silently overwritten.

Deleting raw/reference evidence later weakens source-level reproducibility and should be recorded
as a limitation if it occurs.

## Evidence-only mode when historical metadata cannot be established

The public Delta India BTCUSD product response may omit `created_at` and
`updated_at`. This means the strict historical metadata applicability
guard cannot certify that today's tick size and contract value applied to
the frozen one-year interval.

The explicitly separate mode below collects **unqualified source evidence**.
It does not relax `validate_product_applicability()`, publish a canonical
dataset, save Parquet bars, or authorize strategy analysis.

```bash
python -m signalforge.research.delta_historical_dataset_acquisition evidence-only \\
  --evidence-dir .signalforge-data/sf088/evidence \
  --generation generation-0001
```

Use a protected local directory with `umask 077`. Evidence is written to
`<evidence-dir>/evidence-only/<generation>/pass-1` and `pass-2`. The command runs the
frozen 263-chunk plan in each pass, records raw and structural candle-content
hashes, compares the passes and produces
`<evidence-dir>/evidence-only/<generation>/evidence-only-report.json`.
Missing product timestamps are reported as
`historical_metadata_applicability=UNRESOLVED`. Retain the first-seen raw
responses locally, outside Git. Resume reuses already-captured and
hash-verified chunks, and conflicting evidence must not be overwritten.
A mismatch between the full passes stops the command with its raw evidence
retained for investigation. If a structurally malformed provider response is
received, the first-seen raw bytes remain on disk but the missing metadata
sidecar deliberately blocks automatic resume; inspect and quarantine that
incomplete capture rather than deleting or overwriting it.

**Do not** pass evidence-only output to the strict canonical qualification
command until an authoritative historical specification or effective-dated
schedule establishes metadata applicability. The strict `acquire` command
continues to reject missing timestamps, and `verify-offline` cannot promote
evidence-only output without a qualifying canonical dataset.

### Immutable generations and offline handoff

Use an explicit generation name, such as `generation-0001`. If a provider
revision, malformed response, or interruption leaves incompatible or incomplete
evidence, preserve that entire generation and record its hashes. Start a new
generation under a different name rather than rewriting the original.

After historical product metadata applicability has been independently established,
the existing strict qualification can consume completed evidence offline:

```bash
python -m signalforge.research.delta_historical_dataset_acquisition qualify-evidence-offline \\
  --evidence-dir .signalforge-data/sf088/evidence \\
  --generation generation-0001 \\
  --store-dir .signalforge-data/sf088/store
```

This checks pre-existing captures and never downloads missing chunks. It still
requires the existing `validate_product_applicability()` guard to pass.
With missing Delta product timestamps, qualification remains blocked.
A future effective-dated schedule requires separate reviewed support.

## Two-pass acquisition

Run:

```bash
python -m signalforge.research.delta_historical_dataset_acquisition acquire \
  --evidence-dir .signalforge-data/sf088/evidence \
  --store-dir .signalforge-data/sf088/store
```

The command performs:

1. pass 1 over the complete deterministic 263-chunk plan;
2. pass 2 over the same plan;
3. exact semantic comparison of every chunk;
4. refusal to freeze a mixed-vintage dataset when any historical candle differs;
5. canonicalization through the SF-087 provider mapping;
6. immutable provider-neutral persistence;
7. local reload and deterministic five-minute derivation;
8. a sanitized final report.

Raw response byte differences are permitted between passes only when interpreted candle content is
semantically identical. Semantic revisions stop finalization rather than patching individual chunks.

## Missing-minute rule

SF-087 did not establish a provider rule for omitted zero-trade minutes.

Therefore absence is never converted into a synthetic flat candle.

Any missing one-minute interval remains an explicit coverage gap unless authoritative or direct
empirical evidence classifies it. A complete dataset with unresolved gaps cannot receive
`READY_FOR_BTC_STRATEGY_RESEARCH`.

## Parquet persistence

SF-084's legacy JSON representation remains readable for existing small datasets.

Bulk historical datasets use a versioned provider-neutral Parquet representation behind the same
`LocalHistoricalDatasetStore.save/load` boundary:

```text
<dataset-id>/
  manifest.json
  bars.parquet
  content-manifest.json
  content-manifest.sha256
```

The Parquet representation preserves:

- exact decimal OHLC values using Parquet decimal logical types;
- explicit UTC timestamps;
- integer contract volume;
- canonical bar provenance;
- deterministic component hashes;
- semantic dataset identity independent of physical representation.

The loader verifies the content-manifest digest, every component digest/size, the Parquet schema
fingerprint, and the reconstructed canonical dataset ID. It never performs provider acquisition.

## Offline verification

After acquisition completes, verify from the frozen store in a separate network-disabled shell or
environment:

```bash
python -m signalforge.research.delta_historical_dataset_acquisition verify-offline \
  --evidence-dir .signalforge-data/sf088/evidence \
  --store-dir .signalforge-data/sf088/store \
  --dataset-id <dataset-id>
```

The command loads only local persisted content, verifies the frozen Parquet content-manifest identity,
writes immutable offline-verification evidence, and is the **only** path that can promote a complete
dataset from `PENDING_OFFLINE_VERIFICATION` to `READY_FOR_BTC_STRATEGY_RESEARCH`.

The acquisition/finalization command itself performs a same-process storage round-trip, but that is
recorded only as `same_process_round_trip_pass`; it does not satisfy the offline-verification gate.

## Final disposition

A complete acquisition initially ends in `PENDING_OFFLINE_VERIFICATION`. Only the separate
network-disabled verification command may promote it to `READY_FOR_BTC_STRATEGY_RESEARCH`.

`READY_FOR_BTC_STRATEGY_RESEARCH` requires:

- historical product metadata applicability established for the full interval;
- complete two-pass semantic coherence;
- no unresolved duplicate/conflicting observations;
- no unexplained rejected/corrupt observations;
- no unresolved missing-minute coverage gaps;
- explicit missing-minute evidence retained with each absent minute classified (initially
  `unresolved_absence` unless authoritative/direct evidence supports a stronger classification);
- successful canonicalization;
- successful Parquet save/load;
- successful offline verification;
- durable sanitized acquisition-run and dataset identities.

`PARTIAL` means a reproducible dataset exists but explicit coverage limitations prevent claiming the
complete one-year horizon.

`BLOCKED` means source identity, metadata applicability, source semantics, revision coherence,
rights or canonical representability cannot be established faithfully.

No strategy signals or performance metrics are inspected by SF-088.


## Maintained offline raw-evidence audit (Stage A)

Use the source-controlled offline audit instead of the temporary repository-root script.
This reads immutable `generation-0001` evidence and writes a separate, write-once
JSON report; it does **not** access Delta, qualify product metadata, or publish a
canonical dataset.

```bash
python -m signalforge.research.delta_historical_evidence_audit \
  --generation-dir .signalforge-data/sf088/evidence/evidence-only/generation-0001 \
  --output .signalforge-data/sf088/audits/generation-0001-completeness-v2.json
```

The v2 audit recalculates raw/semantic hashes, checks source/request identities,
coverage, duplicate/missing/out-of-window minutes, OHLC shape and volume through
the existing parser, and reports every current-snapshot tick-grid discrepancy with
the exact field and price. Current-snapshot tick discrepancies are observations,
**not** determinations about historically applicable contract rules.

The report deliberately uses a separate audit version/hash: do not overwrite the
existing `generation-0001-completeness.json`, and do not edit any source capture.
Local raw responses and reports remain outside Git. Historical applicability
remains unresolved; the existing `validate_product_applicability()` boundary
continues to block canonical publication.

Run the synthetic regression checks independently:

```bash
python -m pytest tests/unit/research/test_delta_historical_evidence_audit.py \
  tests/unit/research/test_delta_historical_dataset_acquisition.py -q
```

After local validation and a merged review, the untracked temporary root-level
`sf088_offline_evidence_audit.py` may be deleted manually; retain the immutable
source generation and both separate audit reports.

The audit marks hard integrity defects as `audit_status=FAIL` and exits nonzero,
while retaining a separate diagnostic report. Missing minutes, duplicates,
out-of-grid timestamps, fractional volume and cross-pass disagreement cannot
silently pass. Off-current-tick observations do not block this **raw-evidence**
audit because historical specification applicability is unresolved.
At most 100 per-pass price-field examples are embedded in the report; full
per-pass anomaly counts and `anomaly_examples_truncated` remain explicit.
Use only an ignored/protected `.signalforge-data` or `signalforge-data` output
location. Inspect `git check-ignore -v .signalforge-data/sf088/audits/`
before running, and do not commit the report or raw data.


## Owner-approved provisional price exploration (separate from Stage B)

The owner approved a **restricted exploratory-only** path on 2026-11-05,
recorded in [issue #240](https://github.com/harishkamathuk/signalforge/issues/240).
This does **not** qualify the one-year historical contract, change the
`validate_product_applicability()` guard, publish a canonical dataset, or
authorize strategy performance, fills, P&L or live/paper execution.

After independently confirming the protected `generation-0001` is intact,
run the explicit local-only, provider-free command:

```bash
umask 077
python -m signalforge.research.delta_provisional_research \
  --generation-dir .signalforge-data/sf088/evidence/evidence-only/generation-0001 \
  --output .signalforge-data/sf088/audits/generation-0001-price-exploration-v1.json
```

The command first reruns the existing maintained **two-pass evidence audit**,
requiring complete coverage and a successful structural integrity result.
It then re-verifies the first-pass chunk hashes while constructing deterministic
completed UTC five-minute closes and exploratory SMA(20). Its JSON contains only
counts, SHA-256 digests and the existing audit's exact five off-current-snapshot
tick observations, **not** a rewritten candle series.

The SMA uses the 20 latest completed five-minute closing prices, with no values
until 20 complete bars have arrived. Derived digests use numerical canonical
Decimal serialization rather than display scale and label five-minute values
by UTC candle **open**; the report also identifies when the first and last SMA
values become available at the corresponding end-exclusive candle boundaries.
It is an exploratory numerical diagnostic,
**not** an entry, exit, strategy filter, simulated trade or profitability metric.

The report is written once outside immutable generation evidence, **under the same
resolved `.signalforge-data/` root as the input generation**. A similarly named
`signalforge-data/` directory, another unrelated `.signalforge-data/` tree, or a
symlink that escapes the input's protected root is refused. The project
`.gitignore` ignores `.signalforge-data/`; verify the local source and output
with `git check-ignore -v` before execution. The command refuses overwrites,
missing/inconsistent minutes,
wrong provenance and audit failures. Retain raw prices unchanged and keep the
full local reports outside Git, under the previously qualified personal/internal
academic data-use boundary.

Every output is labelled `UNQUALIFIED_HISTORICAL_METADATA` and explicitly states
that no historical tick rule is assumed, no canonical dataset was published, and
trade/strategy performance use is not authorized. Stage B remains **BLOCKED**.

Acceptance requires local execution against the protected real generation,
a fresh write-once report/digest, focused tests, repository CI and adversarial
PR review. Successful synthetic CI tests alone do not prove real-generation
acceptance. If new effective-dated product history is established, qualification
must still proceed through the original separately reviewed strict Stage B path.
