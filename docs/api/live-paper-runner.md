# Live PAPER operator command

SF-058 exposes the single-security live runtime through the existing `signalforge` CLI.

## Command

```bash
signalforge live-paper --config live-paper.json
```

The command is explicitly **PAPER only**. It has no option that enables broker order placement.

Example non-secret configuration:

```json
{
  "instrument_id": "NSE:RELIANCE",
  "quantity": 10,
  "engine_calculation_version": "engine-v1",
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
7. waits for the canonical NSE regular-session activation boundary when launched early;
8. constructs and starts the live runtime.

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

## Shutdown

SIGINT and SIGTERM request cooperative shutdown between synchronous processing steps.

Shutdown:

- stops new work;
- allows the current synchronous step to finish or fail;
- best-effort unsubscribes/closes the feed;
- reports final lifecycle/continuity/feed state;
- does not fabricate or flush forming-candle chronology.

Durable ARMED/OPEN state remains authoritative and is recovered under ADR-009 on a later process.

## Current M8 limitations

- PAPER only; no broker order methods are exposed.
- One NSE security only.
- No automatic gap reconciliation or historical backfill.
- No service supervisor/dashboard.
- A new live run derives warmup readiness from real indicator checkpoint samples. It does not inject
  an artificial 250-candle warmup value. Historical indicator pre-seeding is not implemented by
  SF-058.
