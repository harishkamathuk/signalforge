# Live PAPER operator command

SF-058 exposes the single-security live runtime through the existing `signalforge` CLI.

## Commands

```bash
signalforge prepare-session --config live-paper.json
signalforge live-paper --config live-paper.json
```

Preparation is explicit and separate from live startup. `live-paper` never downloads historical
bars as an implicit repair step.

The command is explicitly **PAPER only**. It has no option that enables broker order placement.

Example non-secret configuration:

```json
{
  "instrument_id": "NSE:RELIANCE",
  "quantity": 10,
  "engine_calculation_version": "engine-v1",
  "evidence_path": "/home/operator/signalforge-m9/evidence/validation-2026-10-07.jsonl",
  "evidence_max_bytes": 50000000,
  "strategy": {
    "id": "intraday_momentum_v1",
    "version": "1.0.0",
    "parameters": {}
  }
}
```

Only one canonical `NSE:<SYMBOL>` instrument is supported.

## Required environment

The runner reuses the existing OpenAlgo and PostgreSQL configuration:

- `DATABASE_URL`
- `OPENALGO_HOST`
- `OPENALGO_API_KEY`
- `OPENALGO_WS_URL`

Optional OpenAlgo timeout/stale/reconnect environment variables continue to use the existing adapter
names documented in the OpenAlgo integration guide.

Do not place the API key or database credentials in the command JSON.

## Startup sequence

Before market-data activation the runner:

1. validates command and strategy configuration;
2. loads secret-safe OpenAlgo configuration;
3. proves PostgreSQL connectivity with a read-only query;
4. requires OpenAlgo REST preflight status `READY`;
5. resolves exact current-date NSE reference/tick metadata;
6. inspects durable recovery state;
7. requires a suitable `PreparedIndicatorCheckpoint` through the immediately preceding NSE
   trading-session close;
8. waits for the canonical NSE regular-session activation boundary when launched early;
9. constructs and starts the live runtime from that prepared indicator state.

A failed dependency prevents WebSocket subscription.

A recovered `RESUMABLE` live run is reported as reconciliation-required under ADR-009 and is not
silently resumed.

## Pre-session launch

The canonical regular-session input window remains **09:15–15:30 IST**.

The command may be launched before 09:15 IST. Validation occurs immediately, but the OpenAlgo
WebSocket and `LiveRuntime` do not start until 09:15. This prevents expected pre-open silence from
being misclassified as stale market data.

A fresh command started after 09:15 IST fails closed rather than guessing that the unobserved opening-session chronology was continuous. Start the operator before the session so it can cross the accepted activation boundary under observation.

## Runtime behavior

The operator loop is synchronous:

```text
poll LiveRuntime once
→ dispatch accepted ARMED time progression
→ log material feed/candle/decision/lifecycle events
→ repeat while the session is active
```

Polling precedes wall-clock dispatch so an already-buffered quote keeps its authoritative exchange
chronology rather than being invalidated by delivery latency. ARMED time expiry/cutoff is driven
through the existing lifecycle policy and persisted atomically.
Wall-clock progression does not fabricate an OPEN exit price. OPEN compulsory session exit still
requires the first qualifying observed market price at/after the accepted exit boundary.

The accepted regular-session market-input window remains inclusive through 15:30:00 IST. At the
wall-clock boundary the runner drains immediately buffered events still stamped within that window;
events stamped later than 15:30:00 are not passed into LiveRuntime.

A chronology-breaking feed gap causes `RECONCILIATION_REQUIRED` and stops same-run processing in
accordance with ADR-009.

## Structured logs

Operator output uses compact JSON-line records for material events such as:

- database/startup readiness;
- OpenAlgo preflight result;
- reference-data acceptance;
- pre-session waiting;
- live activation;
- feed-state changes;
- completed candles;
- strategy decisions;
- lifecycle transitions;
- reconciliation/failure;
- shutdown.

API keys, broker credentials, raw environment dumps and raw provider payloads are not logged.


## M9 validation evidence

When `evidence_path` is configured, `live-paper` creates a separate bounded JSONL evidence file.
It is diagnostic/audit evidence only and is never used as provider identity, replay sequencing,
restart state, or ADR-009 reconciliation input.

The evidence stream records:

- safe observed OpenAlgo Quote facts needed to validate provider timestamp and cumulative-volume
  handling, including connection generation and baseline/unchanged/emitted-delta disposition;
- accepted normalized `MarketEvent` facts recorded only after session filtering and successful live-runtime
  processing/persistence, so observed provider quotes remain distinguishable from accepted runtime input;
- canonical completed-candle interval, OHLCV, quality, source, and source-event count;
- the canonical per-candle `IndicatorSnapshot`, including calculation version and requirement
  readings/readiness;
- the strategy decision projected through the same `StrategyDecisionFact` audit projection used
  for durable persistence.

The evidence file is created exclusively: an existing path fails closed rather than appending a
second run. `evidence_max_bytes` bounds local retention. Exceeding the bound or losing the evidence
file is surfaced as `evidence_failure`; before activation this is a startup failure, and after
activation it is a runtime failure. A session with evidence failure is not M9-qualifying.

The evidence contains no API key, database URL, broker credential, raw environment dump, or
credential-bearing raw provider payload. It deliberately does not invent `source_event_id` or a
provider sequence.

## Shutdown

SIGINT and SIGTERM request cooperative shutdown between synchronous processing steps.

Shutdown:

- stops new work;
- allows the current synchronous step to finish or fail;
- best-effort unsubscribes/closes the feed;
- reports final lifecycle/continuity/feed state;
- does not fabricate or flush forming-candle chronology.

Durable ARMED/OPEN state remains authoritative and is recovered under ADR-009 on a later process.

## SF-073 prepared-state boundary

`prepare-session` uses completed OpenAlgo historical OHLCV bars directly at the canonical
indicator-input boundary; it does not manufacture historical MarketEvents or intrabar chronology.

The operation requires complete provable regular-session 5-minute history for its accepted bootstrap
window. The provider does not expose evidence that distinguishes an omitted zero-event bar from
provider data loss, so an expected missing interval fails closed and no synthetic flat candle is
created.

A NEW live run copies the suitable prepared `IndicatorEngineState` into the existing run-scoped
checkpoint path and records the prepared-checkpoint provenance. A RESUMABLE interrupted run cannot
use prepared state to bypass ADR-009 reconciliation.

## Current M8 limitations

- PAPER only; no broker order methods are exposed.
- One NSE security only.
- No automatic gap reconciliation or historical backfill for interrupted runs.
- NSE session-calendar coverage is deliberately bounded to the authoritative 2026 equities calendar
  required by the current M8 implementation.
- No service supervisor/dashboard.
