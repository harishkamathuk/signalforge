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
