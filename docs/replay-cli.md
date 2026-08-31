# Replay CLI

Install SignalForge in the development environment, then run:

```bash
signalforge replay --config replay-config.json --input replay-events.json
```

`replay-config.json` contains the configured single NSE instrument, paper quantity, engine calculation version, effective-dated tick rules, and Strategy V1 configuration. Omitting Strategy V1 fields uses only the accepted typed defaults already defined by `StrategyV1EvaluationConfig`.

Example:

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

Successful runs write one deterministic JSON summary to stdout containing run/source identity, event/evaluation counts, decision counts, Signal/Trade/Exit counts, open rejections, and the final lifecycle state. Invalid configuration, input, or runtime contracts return a non-zero process status and write the error to stderr.

The replay command is single-security and in-memory. It does not connect to a database, broker, OpenAlgo, or live execution path.
