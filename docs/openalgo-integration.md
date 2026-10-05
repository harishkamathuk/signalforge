# OpenAlgo integration boundary

SF-054 introduces the first concrete OpenAlgo integration seam. It is deliberately limited to
configuration and a read-only startup preflight; symbol normalization, live subscriptions and
runtime assembly belong to later M8 work.

## Configuration

SignalForge reads OpenAlgo connection values from externally supplied configuration. The supported
environment names are:

- `OPENALGO_HOST` — the OpenAlgo service root. Plain HTTP is accepted only for loopback development hosts such as `http://127.0.0.1:5000`; remote hosts must use HTTPS;
- `OPENALGO_API_KEY` — the OpenAlgo application API key;
- `OPENALGO_CONNECT_TIMEOUT_SECONDS` — optional positive connect timeout;
- `OPENALGO_REQUEST_TIMEOUT_SECONDS` — optional positive response/read timeout.

The API key is represented as a secret value and must not be committed, logged, included in normal
representations, or copied into diagnostic status objects. Remote plaintext HTTP is rejected so the
API key cannot be transmitted over an unencrypted non-loopback connection. Broker credentials and broker access
tokens are not SignalForge configuration; OpenAlgo owns those credentials and resolves the active
broker session server-side.

## Startup preflight

SF-054 uses the authenticated, read-only `POST /api/v1/ping` endpoint. The request requires only the
OpenAlgo API key and does not require symbol/instrument resolution or invoke an order endpoint.

The SignalForge-facing result is one of:

- `READY` — API key accepted and an active broker session resolved; broker identity is returned;
- `UNREACHABLE` — network, DNS, TLS, connection or timeout failure;
- `API_AUTH_FAILED` — the OpenAlgo API key was rejected;
- `BROKER_SESSION_UNAVAILABLE` — OpenAlgo was reached but the authenticated ping could not resolve an active broker session;
- `PROTOCOL_ERROR` — malformed JSON, unexpected response shape/status, or application-level error that cannot be safely classified.

A raw HTTP 200 is not sufficient for readiness. The response must be JSON with OpenAlgo's success
envelope, `pong`, and a non-empty broker identity. Unknown provider behavior fails closed.

## NSE instrument and tick-reference resolution

SF-055 resolves one configured canonical `InstrumentId("NSE:<SYMBOL>")` against OpenAlgo's
current symbol/reference metadata. Resolution requires exact NSE cash-equity identity and checks
the exact `/symbol` result against the exact candidate returned from `/search`.

OpenAlgo's public current-reference surfaces do not establish historical tick-size lineage.
SignalForge therefore binds the accepted `TickSizeRule` to the requested trading date only:

```text
effective_from = trading_date
effective_to   = trading_date
```

The observation timestamp must fall on that trading date in IST. This records what reference data
was observed and accepted for the live trading date without claiming validity before or after it.

Tick-size JSON numbers are decoded directly as `Decimal` values. Missing, non-finite,
non-positive or contradictory tick sizes fail closed; SignalForge never substitutes a permanent
NSE tick-size default. OpenAlgo broker tokens and native symbols remain provenance metadata and do
not replace canonical SignalForge identity.

## Testing

Unit tests inject a provider-private transport fake. CI therefore needs no OpenAlgo instance,
broker connection, API key, or internet access. Tests explicitly cover secret redaction and the
classification boundaries between API authentication, broker-session availability, network
failure and malformed provider responses.

## Explicit non-goals

SF-055 does not implement WebSocket subscriptions, reconnect behavior, MarketEvent conversion,
stale-feed handling, CandleEngine integration, runtime assembly, historical reference-data
warehousing, or any broker order operation. Those remain owned by SF-056 and later M8 issues.
