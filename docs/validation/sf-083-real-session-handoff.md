# SF-083 — First real historical NSE session: evidence handoff

**Status:** real acquisition NOT COMPLETE. This change proves only the offline
canonical persistence/reload integration with explicitly synthetic
nsemine-shaped records. No NSE endpoint was called or provider rights inferred.

**Preferred experimental source:** nsemine / signalforge-nsemine. The merged
SF-079 provisional mapping helper in `tests/support/` is deliberately
synthetic-only; treating it as a verified real provider adapter would be an
unapproved source-semantics and provenance change.

## Real-sample execution requirements (still outstanding)

1. Record the independently permitted acquisition and local-retention path,
   actual nsemine/library + fork commit, endpoint identity and limitations.
   Use only an authorized path; do not infer permission from library availability.
2. Predeclare a real NSE cash-equity instrument with exact provider symbol/
   series, and one official regular NSE trading session including calendar
   identity, before inspecting signal outcomes. No cherry-picked windows.
3. Acquire just that 1-minute session into a **local, access-controlled raw
   evidence file** without committing restricted market OHLCV into Git. Record
   provider/raw digest, requested/returned windows, acquisition timestamp and
   provider timestamp-label convention from evidence.
4. Validate actual source clock semantics independently; do **not** apply the
   synthetic NSE-wall-clock assumption merely because shaped timestamps resemble
   those of the existing synthetic mapper. Refuse unsupported or contradictory
   identity/clock/volume/adjustment policies and log unresolved limitations.
5. Convert the permitted real sample to the accepted
   `HistoricalBarDataset` after independent evidence supports the mapping;
   validate counts, OHLCV invariants, missing/duplicate/rejected minutes and
   the derived 75 five-minute candle qualities.
6. Save the canonical dataset using `LocalHistoricalDatasetStore` from
   SF-084. Disconnect network/provider access, construct a **fresh store**
   instance, load by the frozen dataset ID, and assert exact identity, manifest,
   counts, hashes and 1m→5m derivation. Reject tampered/missing evidence.
7. Produce a report carrying a source/raw digest, canonical dataset ID,
   source-use basis, observed first/last bucket, all data-quality counts,
   known tick/calendar gaps and the exact replay verification. Do not claim
   performance or Gate A SELECT.

## Automated rehearsal and boundary

`tests/unit/research/test_sf083_offline_store_integration.py` uses 59
synthetic provider-shaped one-minute records, including one deliberately absent
minute, and checks 11 valid / 1 incomplete / 63 missing derived five-minute
candles. It stores and reloads the canonical dataset with network disabled and
checks integrity fail-closed after local mutation. It does **not** validate a
real nsemine response, provider licensing, calendar selection or actual source
timestamp semantics.

SF-083 remains open until real permitted acquisition and evidence validation
are completed. SF-079 Gate A remains unchanged. The first sample is not
by itself sufficient for SF-080 strategy-performance claims.
