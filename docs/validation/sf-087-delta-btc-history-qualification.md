# SF-087 — Delta BTCUSD Historical Qualification

SF-087 qualifies one concrete provider/data shape against SignalForge's provider-neutral historical
research boundary:

- venue/provider: Delta Exchange India;
- product: BTCUSD perpetual;
- price basis: traded price;
- source resolution: one minute;
- comparison resolution: five minutes;
- canonical chronology: timezone-aware UTC;
- expected coverage: explicit continuous `HistoricalBarGrid`.

This page is an operator/evidence procedure, not a strategy specification. No strategy result,
entry/exit rule or profitability conclusion is authorized by SF-087.

## Official provider baseline

Delta's public v2 REST documentation currently identifies the production origin as
`https://api.india.delta.exchange`, documents `GET /v2/products/{symbol}` for provider-native
product metadata, and documents `GET /v2/history/candles` for public historical OHLC candles.
The historical endpoint accepts `resolution`, `symbol`, `start` and `end`; request bounds are
documented as Unix timestamps in seconds, and 1m/5m are documented resolutions.

These documentation facts justify a bounded qualification experiment. They do **not** prove the
returned candle-time label, exact REST boundary inclusion behavior, completeness, repeatability,
volume semantics or historical retention depth.

## Canonical boundary

Reusable SignalForge types remain provider, asset and session neutral.

Two small canonical provenance corrections are required by SF-087:

- `HistoricalPriceBasis` records the economic price series (for this sample, `traded`) and is
  semantic dataset identity material when present;
- `CorporateActionPolicy.NOT_APPLICABLE` allows non-equity instruments to avoid false
  equity-adjustment semantics.

Legacy datasets that omit price basis retain their existing semantic identity and immutable-store
wire representation.

## Exact numeric rule

Provider numeric fields used for comparison or canonicalization are parsed from JSON using exact
decimal semantics. OHLCV must not pass through binary `float` before validation, comparison or
dataset hashing.

A valid source volume that is fractional is a hard canonicalization stop while
`HistoricalBar.volume` remains integral. Do not round or truncate it.

## Raw evidence capture

Use the provider-specific qualification entry point. Raw provider responses must stay outside Git
unless rights explicitly permit publication.

Example shape:

```bash
python -m signalforge.research.delta_historical_qualification \
  --symbol BTCUSD \
  --resolution 1m \
  --start-epoch <provider-start> \
  --end-epoch <provider-end> \
  --repeats 2 \
  --output-dir <local-evidence-directory>
```

The command performs one uncached product request and the requested number of independent candle
requests. It writes raw response bytes plus `capture-manifest.json` containing request URLs,
acquisition timestamps and SHA-256 digests.

The command deliberately accepts provider epoch bounds directly. It does not guess whether the
provider `end` bound is inclusive or exclusive.

## Stage A — semantic probe

Before the canonical 24-hour sample, use a small outcome-blind probe to establish:

1. returned `time` unit;
2. whether `time` denotes candle open, candle close or another boundary;
3. UTC interpretation and exact-minute alignment;
4. ordering;
5. start-bound inclusion;
6. end-bound inclusion/exclusion.

Only after those facts are evidenced may `DeltaTimestampContract.provider_bounds()` translate a
canonical half-open interval into provider request parameters.

If candle-open labeling or request-bound translation cannot be established, SF-087 is BLOCKED.

## Stage B — pre-registered 24-hour sample

After Stage A, pre-register one exact half-open UTC interval `[start, end)` of 24 hours before
inspecting price outcomes.

Expected canonical coverage:

- 1,440 one-minute intervals;
- 288 five-minute intervals.

Acquire:

1. provider product metadata;
2. two independent 1m responses for the same provider request;
3. one matching 5m response.

Do not select the day using volatility, strategy signals or trade outcomes.

## Required source checks

For the Stage B 1m source, record:

- provider product ID/symbol/contract type and product-metadata digest;
- exact API origin;
- tick size and contract metadata exposed by the provider;
- returned row count and first/last timestamp;
- strict ordering and duplicate timestamps;
- exact-minute alignment;
- missing intervals against the declared continuous grid;
- OHLC validity;
- price/tick alignment;
- volume unit and numeric representation;
- whether every valid volume is losslessly integral;
- independent-response SHA-256 equality/difference.

A continuous market does not authorize fabrication of missing candles. An omitted provider minute
remains missing evidence until provider semantics explain it.

## Exact 1m → 5m comparison

For every complete five-minute bucket, provider 5m is equivalent only when all fields match exactly:

- open = first constituent open;
- high = maximum constituent high;
- low = minimum constituent low;
- close = final constituent close;
- volume = exact sum of constituent volume.

Do not apply tolerance or use provider 5m to repair 1m gaps.

## Canonicalization and SF-084

Canonicalization is allowed only after source semantics are established.

The Delta mapping creates:

- `HistoricalPriceBasis.TRADED`;
- `CorporateActionPolicy.NOT_APPLICABLE`;
- a versioned explicit continuous UTC `HistoricalBarGrid`;
- UTC `CandleInterval` values;
- raw/interpreted timestamp provenance;
- provider product identity in manifest provenance.

After creation, save through the existing `LocalHistoricalDatasetStore` and reload without network
access. Dataset identity, grid, bars, price basis and deterministic aggregation must remain equal.
No second provider-specific persistence mechanism is permitted.

## Qualification outcome

Record the four independent SF-087 gates:

1. **SOURCE IDENTITY** — PASS / BLOCKED / FAIL;
2. **SOURCE SEMANTICS** — PASS / BLOCKED / FAIL;
3. **CANONICAL REPRESENTABILITY** — PASS / BLOCKED / FAIL;
4. **BOUNDED OFFLINE REUSE** — PASS / BLOCKED / FAIL.

Only four PASS results permit **QUALIFIED**.

Report historical retention separately as `PROVEN`, `PARTIAL` or `UNKNOWN`. A successful
24-hour qualification sample is not by itself a research-period dataset.

## Current repository status

The repository implementation provides deterministic parsing, source-shape inspection,
timestamp-bound translation, exact 1m→5m comparison, canonical mapping and raw-evidence capture.

The real-provider SF-087 gates remain unproven until Stage A and Stage B are executed against the
public Delta endpoint and the bounded-use/retention evidence is recorded. CI intentionally remains
offline and does not convert synthetic tests into provider qualification evidence.
