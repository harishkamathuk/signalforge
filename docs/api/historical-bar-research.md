# Historical Bar Research Boundary

DATA-004 implements the first executable historical-bar research vertical defined by ADR-010.

The boundary is deliberately separate from event replay:

```text
canonical historical 1m bars
        ↓
validation / immutable dataset identity
        ↓
deterministic coverage-grid-anchored 1m → 5m aggregation
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

Canonical source bars are exact one-minute observations with strictly
positive OHLC, non-negative integral volume, explicit provider timestamp evidence, and
an explicit canonicalisation version. Stored source observations are `VALID`; missing
minutes are represented by absence and detected during aggregation rather than by
fabricated flat rows.

## Dataset provenance and identity

::: signalforge.research.historical_grid.HistoricalBarGrid


::: signalforge.research.historical_bars.HistoricalDatasetManifest

::: signalforge.research.historical_bars.HistoricalBarDataset

The dataset identity is derived from semantic canonical content and interpretation
provenance. Operational acquisition time and local file location are not dataset
identity. Legacy manifests declare explicit NSE regular session dates and keep their
original semantic identities. New manifests instead declare versioned
`HistoricalBarGrid` coverage intervals: half-open, aware UTC timestamps with
exact minute boundaries, non-overlapping ordered segments of complete 5-minute
length. Each segment anchors its own 5-minute buckets. The requested bounds
must match coverage endpoints. This is **expected coverage**, not provider
metadata or an exchange-calendar rule engine. Contradictory duplicates fail explicitly. Canonical row/missing counts must reconcile
with canonical content. Raw-row, duplicate, and corrupt-rejected counts are retained as
operational acquisition provenance and do not alter semantic dataset identity.

## Deterministic aggregation

::: signalforge.research.historical_bars.aggregate_one_minute_to_five_minute

The aggregator enumerates the manifest's expected coverage grid, including
segments with no returned rows. Legacy NSE manifests resolve to the unchanged
09:15–15:30 IST regular session (375 minutes and 75 five-minute buckets).
Continuous UTC coverage can span a whole day (1,440/288); a bounded grid
starting at 00:02 UTC anchors its buckets at 00:02, 00:07, 00:12, rather than
silently aligning to midnight. It uses half-open intervals. A bucket is:

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

## SF-095 experimental BTC strategy and raw diagnostic historical execution

::: signalforge.config.btc_momentum_baseline_v0.BtcMomentumBaselineV0Config

::: signalforge.runtime.btc_momentum_baseline_v0.BtcMomentumBaselineV0Strategy

::: signalforge.research.historical_execution.HistoricalPriceMode

::: signalforge.research.historical_execution.HistoricalExecutionAssumptionProfile

::: signalforge.research.historical_execution.HistoricalBarExecutionRunner

::: signalforge.research.historical_execution.HistoricalExecutionRunResult

The registered `btc_momentum_baseline_v0 / 0.1.0-experimental` follows the
approved specification in `docs/strategies/btc-momentum-baseline-v0.md`.
It is a **research strategy only**. The independent frozen Tier-1 research
contract is in `docs/validation/btc-momentum-baseline-v0-validation-v0.md`.

`HistoricalPriceMode.RAW_DIAGNOSTIC` explicitly prohibits a historical
tick schedule; it **does not** make raw trigger/target/fill prices historically
tradable. `REFERENCE_RAW / 1.0.0` and `ADVERSE_RAW / 1.0.0` are the only
frozen raw profiles; the adverse variant applies ten basis points to the modeled
entry, stop exit and target exit (not to its zero forced-exit assumption).
No current Delta tick rule is substituted for missing historical applicability.

A raw run requires:
- the registered BTC experimental strategy and canonical `DELTA:BTCUSD`;
- a traded-price dataset with an explicit, continuous UTC coverage grid;
- a `RawDiagnosticSource` bundle returned by the protected-evidence audit
  (dataset and source evidence identity are not caller-paired strings);
- an aware, predeclared `measurement_start`, with at least 250 preceding
  complete five-minute candles of pre-roll;
- `CONTINUOUS_HISTORICAL_SESSION_POLICY`, which has no compulsory exit;
- `tick_schedule=None` and a raw profile.

The SF-088 `generation-0001` protected **evidence-only** archive is not a
strict SF-084 dataset. For the approved Tier-1 contract only, SF-095 provides
a read-only transient diagnostic input bridge:

::: signalforge.research.btc_raw_diagnostic_input.RawDiagnosticSource

::: signalforge.research.btc_raw_diagnostic_input.load_sf095_raw_diagnostic_source

This bridge reruns independent two-pass audit, verifies the frozen provisional
report and five-minute-close hashes, checks each retained first-pass chunk's
raw and semantic digest, and maps exactly the observed provider OHLCV into
`HistoricalBarDataset` **in memory** without checking against today's tick.
It does not publish this dataset, call a provider or weaken SF-088's strict
historical metadata qualification gate. Its returned
`source_diagnostic_id` must be forwarded to the historical runner; the
derived `dataset_id` is only a reproducible **diagnostic representation**,
not SF-088 Stage-B `READY_FOR_BTC_STRATEGY_RESEARCH`.

```python
from pathlib import Path

raw_source = load_sf095_raw_diagnostic_source(
    Path(".signalforge-data/sf088/evidence/evidence-only/generation-0001")
)
dataset = raw_source.dataset
source_id = raw_source.source_diagnostic_id  # provenance carried by raw_source
```

For example, once the source-diagnostic identity and dataset have been
independently verified in conversation 04:

```python
result = HistoricalBarExecutionRunner().run(
    raw_source.dataset,
    raw_source=raw_source,
    strategy_selection=StrategySelection(
        "btc_momentum_baseline_v0", "0.1.0-experimental", {}
    ),
    engine_calculation_version="engine-v1",
    tick_schedule=None,
    execution_profile=HistoricalExecutionAssumptionProfile.reference_raw(),
    market_session_policy=CONTINUOUS_HISTORICAL_SESSION_POLICY,
    measurement_start=verified_measurement_start,
)
assert result.execution_valid is False
```

Pre-roll updates indicators but cannot arm or open trades. A position remaining
OPEN at dataset end stays UNRESOLVED; UTC midnight is not a trading boundary.
The result identity includes strategy/config/engine/simulator, source dataset,
diagnostic evidence identity, measured-window start, market policy and raw profile.
Its `tick_schedule_semantic_id` explicitly records unresolved historical
tick applicability. Raw outcomes never populate `tradable_trigger` or
`tradable_target_price` as executable levels.

The existing execution-valid NSE mode remains the default: it still requires
an evidence-backed `TickSizeSchedule`, the established NSE market policy and
ADR-011 ambiguity semantics. It is not retroactively changed to raw diagnostics.

**Do not interpret implementation tests or diagnostic output as evidence of
BTC profitability, execution validity, PAPER readiness, or deployment approval.**

In RAW_DIAGNOSTIC summaries, qualified candles blocked by an existing ARMED
or OPEN lifecycle remain auditable in `outcomes` and are counted separately as
`blocked_non_actionable_signals`; they do not inflate `total_actionable_opportunities`
or determinate-coverage denominators. Legacy execution-valid NSE summary identity
remains unchanged. For RAW_DIAGNOSTIC, `raw_decision_evidence` now retains each measured completed
five-minute candle's decision/rejection reasons, readiness, blocked-by-active
status, and raw Decimal MACD line/signal/histogram. The trace is included in the
raw result semantic identity; pre-roll is excluded and NSE result mappings are
unchanged. MACD remains non-mandatory for strategy qualification.

Audited source bundles additionally bind the frozen evidence identity to the
exact diagnostic dataset content hash. Replacing the dataset while copying the
audit proof is rejected before research execution. Synthetic-only source
identities remain available for unit tests.

Intrabar entry-versus-exit ambiguous branches use the selected RAW_DIAGNOSTIC
sell-fill slippage before calculating possible R outcomes. Existing NSE
execution-valid legacy ambiguity output remains unchanged.

### SF-097 opt-in bounded-flat continuation (experimental)

The existing historical runner remains `FAIL_CLOSED_V1` by default. A separate
`HistoricalContinuationPolicy.BOUNDED_FLAT_V1` is available only with
`RAW_DIAGNOSTIC`, using simulator calculation identity
`historical-bar-execution-v2-bounded-flat`. It is not a general branch-state
simulator or an execution-valid model.

When the *only* competing intrabar event is entry versus pre-entry invalidation,
and the invalidation threshold is **at or below the post-fill stop**, every
supported history ends **flat**: either the unfilled setup expires or a modeled
entry is followed by a STOP (and potentially a TARGET if reachable first).
Possible closed-trade R values use the chosen raw slippage profile, remain
conditional, and never enter determinate point estimates. The default v1
runner still returns its original `OPEN_POSSIBLE` termination result.

If an unknown OPEN state remains possible, the new policy also terminates
rather than pretending a later trade is independent. Future branching work
would require separately reviewed lifecycle-history propagation; this optional
policy does not discard possible open states.

Select it explicitly with
`continuation_policy=HistoricalContinuationPolicy.BOUNDED_FLAT_V1` when
calling `HistoricalBarExecutionRunner.run(...)`. Research provenance must
retain both this calculation version and the existing source/profile identities.
The frozen SF-096 prefix evidence must not be overwritten by any rerun.

**SF-097 identity and deferred scope:** The v2 `BOUNDED_FLAT_V1` policy
namespaces its run, signal and execution-opportunity IDs with the new simulator
version, while preserving the v1 and NSE identity calculations exactly.
A shared underlying candle interval is not itself an execution-outcome identity;
cross-model joins must use the explicit dataset/strategy/config/interval and
model-version columns, never a presumed shared opportunity ID.

The separate `historical_possible_worlds` synthetic state-propagation proof
retains pre-failure causal world IDs, the failing minute key and both finite
resource budgets if enumeration exhausts. This evidence is intentionally
`UNRESOLVED`, not a pruned or estimated continuation. Its resolver is
caller-supplied, **not** a validated OHLCV-to-branch adapter. General continuation
through still-possible OPEN states is deferred to GitHub #251 and is not
supported by `BOUNDED_FLAT_V1`.
