# Replay CLI

Install SignalForge in the development environment, then run:

```bash
signalforge replay --config replay-config.json --input replay-events.json
```

`replay-config.json` contains the configured single NSE instrument, paper quantity,
engine calculation version, effective-dated tick rules, and a strategy selection.

## Canonical strategy selection

New configuration should select an explicitly registered strategy ID/version and
provide only that strategy's parameters:

```json
{
  "instrument_id": "NSE:RELIANCE",
  "quantity": 10,
  "engine_calculation_version": "engine-v1",
  "tick_rules": [
    {"tick_size": "0.10", "effective_from": "2026-01-01"}
  ],
  "strategy": {
    "id": "intraday_momentum_v1",
    "version": "1.0.0",
    "parameters": {}
  }
}
```

The strategy envelope is strict. Unknown envelope fields, missing `id`,
`version` or `parameters`, unsupported versions, and malformed strategy
parameters fail during startup before replay market input is read.

Strategy parameters are validated by the registered strategy's typed schema.
For Strategy V1 this retains `extra="forbid"`; unknown parameters are not
silently ignored.

## Legacy Strategy V1 compatibility

Existing replay configurations remain supported:

```json
{
  "instrument_id": "NSE:RELIANCE",
  "quantity": 10,
  "engine_calculation_version": "engine-v1",
  "tick_rules": [
    {"tick_size": "0.10", "effective_from": "2026-01-01"}
  ],
  "strategy": {}
}
```

A strategy mapping with **none** of the canonical envelope keys
(`id`, `version`, `parameters`) is interpreted as the historical
`intraday_momentum_v1 / 1.0.0` parameter mapping. Existing non-default
Strategy V1 parameters may therefore remain directly under `strategy`.

If any canonical envelope key is present, the whole value is validated as the
canonical envelope. Mixed shapes are rejected rather than guessed.

The canonical envelope is only a selection mechanism. Strategy V1 continues to
derive ConfigIdentity from its existing semantic mapping, so equivalent legacy
and canonical configurations produce the same configuration and deterministic
run identity.

## Replay input

`replay-events.json` is a JSON array of canonical historical trade/LTP observations:

```json
[
  {
    "exchange_timestamp": "2026-08-31T10:00:00+05:30",
    "received_timestamp": "2026-08-31T10:00:00.001+05:30",
    "price": "100.00",
    "quantity": 1,
    "source": "fixture",
    "source_event_id": "e1"
  }
]
```

Successful runs write one deterministic JSON summary to stdout containing
run/source identity, event/evaluation counts, decision counts, Signal/Trade/Exit
counts, open rejections, and the final lifecycle state. Invalid configuration,
input, or runtime contracts return a non-zero process status and write the error
to stderr.

The replay command is single-security and in-memory. It does not connect to a
database, broker, OpenAlgo, or live execution path.
