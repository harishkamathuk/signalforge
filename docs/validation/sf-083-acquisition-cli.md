# SF-083 — Local acquisition CLI (experimental)

The runnable CLI is `tools/research/sf083_acquire_sample.py`. Install SignalForge
(`python -m pip install -e .`) and install a separately pinned/recorded nsemine
fork into the local Python environment before attempting acquisition. Neither
nsemine nor broker credentials are imported by offline verification.

## Required prerequisites

Register the exact NSE EQ symbol, one regular historical NSE session, the
exchange-calendar reference and a source/use/retention basis in SF-083 **before**
examining the outcome. Put the source-use evidence in a local text file and
record the actual installed nsemine/fork commit as the `--revision`. A nonempty
local evidence file is a workflow guard **not proof of legal authorization**.
Confirm allowed acquisition and local retention independently. Restrict
permissions of the private output directory and do not add it to Git.

## Commands

```bash
mkdir -p /path/outside-repository/sf083-sample
python tools/research/sf083_acquire_sample.py acquire \
  --symbol TCS \
  --session 2026-10-09 \
  --series EQ \
  --revision PINNED_INSTALLED_NSEMINE_COMMIT \
  --calendar-reference NSE_REGULAR_SESSION_REFERENCE \
  --entitlement-evidence /path/private/source-use-evidence.txt \
  --output /path/outside-repository/sf083-sample
```

The published `harishkamathuk/signalforge-nsemine` source confirms the exact `nsemine.historical.get_stock_historical_data(stock_symbol, start_datetime, end_datetime, interval, raw)` signature; the script checks the installed callable signature before retrieval. nsemine performs internal token lookup and transport, so one top-level call does **not** imply only one network request. It also does not enforce EQ-series identity for historical lookups. The revision, calendar reference and nonempty entitlement file are **operator attestations**; installed package version and module path are recorded separately but cannot prove entitlement or exact Git commit provenance. No NSE request was made in CI.

The **single** nsemine `historical.get_stock_historical_data(...,
interval=1, raw=True)` call captures an SDK-decoded, deterministically re-encoded JSON dictionary to `sdk-decoded-response.json`,
then writes `acquisition-manifest.json` with the SHA-256 of **those saved JSON bytes, not upstream HTTP transport bytes**, the requested time
range, acquisition timestamp and declared revision. It refuses nonempty
directories rather than risking replacement. If writing either artifact fails, the script attempts to remove its own partial output and reports an error; inspect/quarantine any remnants before retrying. A failed API response with no saved evidence must not be described as an acquired sample. This is a bounded local
experiment; its output does **not** contain a canonical dataset ID yet.

**Important stop:** The published nsemine API documents raw historical
retrieval, but the actual raw schema, timestamp interpretation, returned series,
candle completion and permission basis remain unverified for this real sample.
The CLI explicitly stops at `RAW_CAPTURED_CANONICAL_MAPPING_BLOCKED_PENDING_SOURCE_EVIDENCE`.
It does **not** map unverified timestamps or fabricate market data. Inspect the
saved SDK-decoded evidence independently, then make a narrow real-response mapper
implementation/test based on proven semantics before declaring SF-083 complete.

Once the validated canonical dataset has been stored with SF-084, run the
separate verification command by its ID in an **OS-level network-isolated**
environment:

```bash
python tools/research/sf083_acquire_sample.py offline-verify \
  --dataset-id YOUR_CANONICAL_DATASET_SHA256 \
  --output /path/outside-repository/canonical-store
```

This command imports no nsemine/broker modules; it checks the on-disk sidecar,
canonical content hash, dataset ID and 5m aggregation. An ordinary invocation
alone does not prove OS-level network isolation.

Do not commit real SDK-decoded response JSON, persisted canonical bars/sidecars,
provider credentials, or restricted logs. Sanitized hashes, observed quality
counts, mapping limitations and a session reference may be recorded on
SF-083. Synthetic-only tests cover the script in CI.

## Completion distinction

**The script is runnable for SDK-decoded JSON capture, but full SF-083 real-sample
acquire → validate → canonicalize → store → disconnected verify is not yet
automated end to end.** That is an evidence-dependent remaining task in
SF-083, not proof that the synthetic mapper can safely be reused on live
nsemine responses.

Offline verification currently validates any given canonical SF-084 dataset; it does **not** link that dataset to this acquisition's manifest or upstream response hash. That linkage must be supplied by subsequent independently evidenced real-source mapping before SF-083 acceptance.
