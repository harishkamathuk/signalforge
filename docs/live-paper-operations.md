# Live PAPER operator

SF-058/SF-073 expose a two-stage operator flow for one configured NSE security:

```bash
signalforge prepare-session --config path/to/live-paper.json
signalforge live-paper --config path/to/live-paper.json
```

`prepare-session` establishes or verifies trustworthy indicator readiness before the target
session. `live-paper` consumes that prepared state; it never fetches history implicitly.

The command is **PAPER only**. It has no option that enables broker order placement.

## Prerequisites

Before starting the command:

- PostgreSQL must be reachable through `DATABASE_URL`;
- OpenAlgo must be configured and have an active broker session;
- the configured instrument must resolve as one exact NSE cash equity;
- the strategy/config identity must be valid;
- no unresolved prior live PAPER run may require ADR-009 reconciliation;
- a suitable immutable `PreparedIndicatorCheckpoint` must exist through the final completed
  5-minute candle of the immediately preceding NSE trading session.

SignalForge does not auto-load `.env` files.

Required environment values are the existing OpenAlgo and PostgreSQL settings, including:

```text
DATABASE_URL
OPENALGO_HOST
OPENALGO_API_KEY
OPENALGO_WS_URL
```

Optional OpenAlgo timeout/reconnect variables retain their existing meanings.

## Command configuration

The JSON config contains no secrets:

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

M8 live PAPER operation is restricted to the accepted
`intraday_momentum_v1 / 1.0.0` strategy.

## Startup phases

The runner validates, in order:

1. command configuration and strategy identity;
2. PostgreSQL connectivity;
3. read-only OpenAlgo preflight;
4. current-trading-date NSE reference/tick metadata;
5. durable M7 recovery status;
6. prepared-indicator checkpoint suitability for the target NSE session.

No WebSocket subscription occurs before these checks succeed. Missing, stale, incompatible,
non-ready, broken-continuity or invalid-provenance prepared state fails closed.

If the same deterministic live-paper run is already RESUMABLE, the command reports
`reconciliation_required` and does not start market processing.

## Pre-session launch

The command may be started before 09:15 IST.

Validation runs immediately, but live WebSocket activation waits until the canonical regular NSE
session opens. This prevents normal pre-open silence from being misclassified as stale market data.

A fresh command started after the 09:15 IST activation boundary fails closed rather than guessing a continuity point. Start the operator before the session so it can cross the accepted activation boundary under observation.

## Runtime behavior

During the active session the runner:

- polls the SF-057 live runtime synchronously before dispatching wall-clock ARMED progression, so an already-buffered quote retains its authoritative exchange chronology;
- advances accepted time-based ARMED lifecycle boundaries without requiring a quote at the exact boundary;
- emits material feed/candle/decision/lifecycle changes as JSON lines;
- stops when ADR-009 requires reconciliation or the runtime becomes terminal.

OPEN compulsory exit still requires the first qualifying observed market price at/after the accepted
forced-exit boundary. Wall-clock time alone never fabricates an exit price.

The accepted market-input window is inclusive through **15:30:00 IST**. When the wall clock reaches
the session boundary, the runner drains immediately buffered events whose exchange timestamps are
still within that window and rejects later provider events from runtime processing.

## Structured logs

Operational records are line-delimited JSON. Typical event names include:

```text
startup
openalgo_preflight
reference_ready
recovery
pre_session_wait
live_activation
feed_state
candle_completed
strategy_decision
lifecycle_transition
reconciliation_required
runtime_failure
shutdown
```

API keys, database URLs, broker credentials, raw environment dumps and raw provider payloads are not
intended to be logged. Known credential-bearing environment values are redacted from surfaced error
details.

## Shutdown

SIGINT and SIGTERM request cooperative shutdown between synchronous runtime steps.

Shutdown best-effort closes the live feed and reports the last lifecycle/continuity state. It does
not flush forming-candle memory as authoritative durable state and does not auto-close ARMED/OPEN
lifecycle state.

A later process restart must recover under ADR-009.

## Exit codes

- `0` — clean operator/session shutdown;
- `2` — startup validation failure;
- `3` — reconciliation required;
- `4` — runtime failure after activation.

## Pre-session indicator preparation

Run `prepare-session` before the live activation boundary. The operation is idempotent:

- if suitable prepared state already exists, it returns `READY_EXISTING`;
- otherwise it fetches authoritative completed 5-minute OpenAlgo history, validates the bounded NSE
  session sequence, advances the canonical `IndicatorEngine`, and atomically persists a new
  immutable checkpoint;
- it never fabricates MarketEvents, completed-candle counts or indicator seeds;
- historical candles never enter strategy/lifecycle evaluation;
- an unprovable expected 5-minute history gap fails closed rather than being filled synthetically.

Strategy V1's 250 completed regular-session candle requirement is unchanged. The count comes from
actual canonical indicator updates.

Prepared checkpoints are run-independent and retained by market boundary. At NEW live activation,
the suitable checkpoint initializes the normal run-scoped indicator state and the run durably
records which prepared checkpoint it consumed. ADR-009 recovery semantics remain unchanged.

## Out of scope

SF-058 does not provide:

- live broker orders;
- automatic gap reconciliation or backfill;
- broker-position reconciliation;
- emergency flattening;
- multi-security operation;
- dashboard/UI;
- daemon/service-supervisor deployment.
