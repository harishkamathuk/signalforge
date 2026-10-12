# Historical Bar Research Boundary

DATA-004 implements the first executable historical-bar research vertical defined by ADR-010.

The boundary is deliberately separate from event replay:

```text
canonical historical 1m bars
        ↓
validation / immutable dataset identity
        ↓
deterministic NSE-anchored 1m → 5m aggregation
        ↓
canonical CompletedCandle
        ↓
existing IndicatorEngine
        ↓
registered Strategy completed-candle evaluation
```

No OHLCV row is converted into a `MarketEvent`. This surface therefore supports
completed-candle indicator/signal research only; it does not simulate entry, stop,
target, fill, or exit chronology.

## Canonical one-minute bar

::: signalforge.research.historical_bars.HistoricalBar

Canonical source bars are exact one-minute, regular-session observations with strictly
positive OHLC, non-negative integral volume, explicit provider timestamp evidence, and
an explicit canonicalisation version. Stored source observations are `VALID`; missing
minutes are represented by absence and detected during aggregation rather than by
fabricated flat rows.

## Dataset provenance and identity

::: signalforge.research.historical_bars.HistoricalDatasetManifest

::: signalforge.research.historical_bars.HistoricalBarDataset

The dataset identity is derived from semantic canonical content and interpretation
provenance. Operational acquisition time and local file location are not dataset
identity. The manifest explicitly declares the expected regular NSE session dates;
the requested range must span those complete sessions from 09:15 through 15:30 IST.
This keeps holidays/non-trading dates out of the thin vertical without inferring an
exchange calendar. Contradictory duplicates fail explicitly. Canonical row/missing counts must reconcile
with canonical content. Raw-row, duplicate, and corrupt-rejected counts are retained as
operational acquisition provenance and do not alter semantic dataset identity.

## Deterministic aggregation

::: signalforge.research.historical_bars.aggregate_one_minute_to_five_minute

The aggregator builds the regular NSE 09:15–15:30 five-minute grid for every
explicitly declared expected session date, including a declared session for which the
provider returned no rows. It uses half-open intervals. A bucket is:

- `VALID` with all five expected valid one-minute constituents;
- `INCOMPLETE` with at least one but fewer than five constituents;
- `MISSING` with no constituents and no fabricated OHLCV.

Only `VALID` derived candles may advance research indicators.

## Completed-candle research runner

::: signalforge.research.historical_bars.HistoricalBarResearchRunner

::: signalforge.research.historical_bars.HistoricalBarResearchResult

A non-VALID derived candle raises `HistoricalContinuityError` and fails the research
run explicitly. The thin vertical does not silently resume indicators after a gap and
does not silently discard all later valid data. Re-establishing continuity or re-seeding
across gaps requires a separate explicit contract.

The runner resolves strategies through the existing registry, constructs the existing
`IndicatorEngine` from the strategy's declared requirements, and invokes the existing
completed-candle strategy boundary. It does not own indicator formulas or strategy rules.

## Deterministic fixture

`examples/research/historical-bars-one-session.json` is an infrastructure fixture.
It is synthetic deterministic bar data, not observed historical market evidence. It must
not be used for profitability, parameter-selection, or validation claims about Strategy V1.
