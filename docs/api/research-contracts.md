# Research Identity Contracts

SF-068 defines the first strategy-neutral provenance boundary for reproducible SignalForge
historical research.

The contracts describe **what experiment is being run**, not how strategy rules are implemented.
Research continues to resolve strategies through the existing registry and typed configuration
surface.

## Explicit universe

::: signalforge.research.contracts.UniverseDefinition

Universe membership is explicit. The canonical representation is sorted and unique so caller
ordering does not create a different experiment.

## Historical dataset

::: signalforge.research.contracts.DatasetSourceDefinition

::: signalforge.research.contracts.DatasetDefinition

Each instrument source uses a content-derived `source_id` from the canonical replay source
contract. Mutable file paths are not experiment identity.

The first thin vertical may use JSON replay-event files as storage, but the research identity
depends on canonical source content/provenance and the requested timezone-aware experiment range.

## Execution inputs

::: signalforge.research.contracts.InstrumentExecutionDefinition

Fixed quantity and effective-dated tick rules are execution/replay configuration, not strategy
semantics. They participate in experiment identity because they can change resulting trades or
economics.

## Experiment

::: signalforge.research.contracts.ExperimentDefinition

Creating an experiment resolves the configured strategy through the registered typed strategy
boundary before any backtest begins.

The experiment identity is derived from:

- registered strategy ID/version;
- canonical strategy config hash;
- explicit universe identity;
- historical dataset identity;
- engine calculation version;
- per-instrument execution configuration.

Changing any material input changes the experiment identity.

## Non-goals

SF-068 does not implement:

- the per-instrument backtest runner;
- multi-instrument orchestration;
- analytics;
- automatic stock selection or ranking;
- parameter optimisation;
- point-in-time index universe construction;
- Parquet ingestion;
- OpenAlgo/live data;
- strategy-semantic changes.
