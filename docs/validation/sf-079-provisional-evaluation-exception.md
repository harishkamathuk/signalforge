# SF-079 — Provisional nsemine evaluation exception

**Decision:** APPROVED by project owner, 14 October 2026.
**Scope:** experimental **offline** historical-data integration against synthetic fixtures or legitimately retained data, not a live NSE acquisition authorization.
**Tracking:** [SF-079 #199](https://github.com/harishkamathuk/signalforge/issues/199).
**Reference fork revision for the proposed experiment:** `signalforge-nsemine` merge commit `23f286a88974a0e56e3f058d26b4a56cb978b4dd` (offline qualification preparation only). This revision is not a validated provider acquisition build or the future mapper's implementation identity. Each experiment must record its actual checked-out fork and mapper revisions plus fixture hashes.

## Decision and rationale

For a hobby/research project, permit a small, disposable integration experiment before source-wide qualification so that canonical historical-data compatibility can be tested rather than waiting for every source candidate to be approved. This is a **bounded exception to the engineering sequencing policy**, not a change to the Gate A selection policy.

The production Phase B acquisition/canonicalization adapter remains prohibited until a source is SELECTED. The existing executable `CURRENT_SF079_PHASE_A_REPORT` stays authoritative; all 14 criteria and their statuses remain unchanged. Current `signalforge-nsemine` remains BLOCKED; `TIMESTAMP_SEMANTICS`, `DATA_USE_CONSTRAINTS`, `RAW_REFERENCE_RETENTION` and other pending criteria remain PENDING. No strategy `intraday_momentum_v1 / 1.0.0` or SF-078 simulator semantic changes.

The owner's prior internal acceptance of licensing risk is not external authorization. Do **not** perform fresh NSE charting/API calls without permission independently established for acquisition and retention. No live trading, broker orders, or production deployment under this exception.

## Smallest implementation plan (approved experimental scope; separate implementation PR)

The owner has authorized implementation of this isolated offline experiment under the restrictions below. This PR records that approval and plan only; the experiment's code must be proposed and reviewed separately. This does not authorize production Phase B integration.

1. **Fixture boundary** — use one predeclared synthetic 1-minute NSE session fixture with explicit provider-shaped raw timestamp, symbol identity, OHLCV, missing intervals, and source provenance. Alternatively use a dataset whose retention and use rights are independently established. No network.
2. **Single-use mapper** — in a clearly labeled experimental module/test area outside the production provider adapter interface, map each record to the existing `HistoricalBar` / `HistoricalBarDataset` and session manifest. Preserve raw timestamp and interpreted source clock separately; use existing ADR-010 bucket semantics, tick/identity types and 1m→5m aggregation. Do not invent missing bars.
3. **Fail-closed validation** — deterministic tests for wrong symbol/series, malformed timestamps, duplicates, out-of-order records, off-grid, missing 1m slots, partial windows and OHLCV invariants. The mapping must not reinterpret provider-local clock as actual UTC.
4. **Auditable result** — record fixture hash, exact mapper/fork revision, session calendar source, accepted/rejected row counts, canonical dataset identity, deterministic 5m reconciliation and limitations. Synthetic results must carry an unmistakable `synthetic / non-market evidence` designation.
5. **Optional mechanical simulator smoke** — only after canonical fixture correctness, exercise existing SF-078 consumer using valid tick-size evidence or synthetic explicitly-labeled tick schedule. No strategy-performance claims from synthetic data.

**Exit:** Tests reproducibly construct or explicitly reject a dataset; report remaining mismatch evidence and stop. Do not promote source qualification, freeze a research sample or start production Phase B. A later authorized provider, including DhanHQ/FYERS, must pass existing Gate A independently.

**Review triggers:** any proposal for real external acquisition, retained proprietary dataset, vendor change, distribution, live/paper broker execution, commercial use, or entry to Phase B. At each trigger re-evaluate third-party permissions and Gate A evidence.
