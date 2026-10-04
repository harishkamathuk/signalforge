# Research CLI

SF-071 exposes the first complete SignalForge Research Harness thin vertical through a thin,
machine-readable command-line interface.

~~~bash
signalforge research run --experiment examples/research/golden-experiment.json
~~~

The CLI delegates to the research application boundary. It does not implement strategy, candle,
indicator, lifecycle, fill, stop, target, orchestration, or analytics semantics.

## Experiment file

The first external research experiment format is strict JSON.

~~~json
{
  "strategy": {
    "id": "intraday_momentum_v1",
    "version": "1.0.0",
    "parameters": {}
  },
  "engine_calculation_version": "engine-v1",
  "start_at": "2026-08-26T09:15:00+05:30",
  "end_at": "2026-08-31T15:30:00+05:30",
  "instruments": [
    {
      "instrument_id": "NSE:AAA",
      "input_file": "nse-aaa-events.json",
      "quantity": 10,
      "tick_rules": [
        {
          "tick_size": "0.10",
          "effective_from": "2026-01-01"
        }
      ]
    }
  ]
}
~~~

Unknown fields are rejected. The universe is explicit. SF-071 does not discover, rank, select,
or optimize securities.

Relative input_file paths are resolved relative to the experiment file, not the operator's
current working directory. Absolute paths are also accepted for local developer/test workflows.

## Historical event files

Each input file is a JSON array of canonical market-event values.

~~~json
[
  {
    "exchange_timestamp": "2026-08-26T09:15:00+05:30",
    "received_timestamp": "2026-08-26T09:15:00.001+05:30",
    "price": "100.0",
    "quantity": 1,
    "source": "historical-provider",
    "source_event_id": "provider-event-1"
  }
]
~~~

The command constructs one canonical ReplaySource per instrument. Dataset/source identities are
derived from normalized event content rather than entered manually in the experiment file.
Moving the same experiment and source files to another directory therefore does not change
research identity.

All experiment configuration and registered strategy parameters are validated before historical
source execution. All declared source files are loaded and validated before ResearchOrchestrator
begins per-instrument backtests, so a malformed later source cannot return a partial result.

## Output

Successful execution writes one compact JSON object to stdout.

The research-result-v1 output contains:

- ExperimentId, UniverseId and DatasetId;
- strategy/config and engine provenance;
- canonical UTC research range;
- per-instrument BacktestRunId, runtime RunId and source ID;
- per-instrument replay counts and lifecycle outcome;
- deterministic typed trade-result rows;
- aggregate gross analytics;
- per-instrument gross analytics.

Decimal economics are serialized as canonical numeric JSON strings (non-semantic trailing scale removed) to avoid binary floating-point reinterpretation and incidental Decimal formatting drift.
No filesystem path is emitted into the result, so identical semantic inputs are reproducible
across machines/directories.

## Golden experiment

The repository ships:

~~~text
examples/research/golden-experiment.json
examples/research/nse-aaa-events.json
examples/research/nse-bbb-events.json
~~~

The fixture uses Strategy V1 over two explicit NSE-style instruments. Each source contains 302
events spanning four regular sessions and produces one closed trade.

Run it with:

~~~bash
signalforge research run --experiment examples/research/golden-experiment.json
~~~

The golden CI proof runs this command in two separate Python processes and requires byte-identical
stdout, including experiment, universe, dataset, source, run and trade identities plus economics
and metrics.

Changing a material execution input such as quantity changes ExperimentId and the affected
research-scoped BacktestRunId while preserving the underlying historical DatasetId.

## Metric interpretation

SF-071 exposes the metric definitions implemented by SF-070: win rate, expectancy / average
realised R, profit factor, deterministic realised-R maximum drawdown, gross P&L/profit/loss,
trade/open/realised counts, exit-reason distribution, and per-instrument equivalents.

See Research Orchestration & Analytics for exact formulas and undefined-value behavior.

All current economics are **gross**. Brokerage, taxes, exchange charges and a mature transaction
cost/slippage model are not deducted. Output from this thin vertical must not be described as net
profitability.

## Research discipline

The golden experiment proves infrastructure and reproducibility. It does **not** establish that
Strategy V1 is profitable or suitable for live capital.

Do not use this first vertical to select the best stocks from historical outcomes, mine strategy
parameters, optimize against the golden fixture, infer out-of-sample robustness, or ignore
survivorship / point-in-time universe bias.

Those require explicit validation methodology and later experimental evidence.

## Failure behavior

The command returns a non-zero exit code and writes the error to stderr for invalid configuration,
unknown strategies, missing/malformed sources, provenance contradictions, or failed research
execution. Unexpected internal defects are not converted inside the research orchestration layer
into normal instrument-validation failures.
