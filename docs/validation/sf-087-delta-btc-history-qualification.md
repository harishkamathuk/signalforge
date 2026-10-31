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

## Qualification evidence observed on 2026-10-31

Stage A used a pre-registered bounded probe around 2026-10-30 00:00 UTC. The observed REST contract
was:

- returned `time` values are Unix seconds aligned to exact minute boundaries;
- returned rows are ordered newest-first;
- both `start` and `end` request bounds were inclusive in the bounded probe;
- matching provider 5m rows exactly equalled deterministic 5×1m OHLCV aggregation for complete
  probe buckets, supporting a candle-open interpretation of `time`.

The pre-registered Stage B canonical range was
`[2026-10-29T00:00:00Z, 2026-10-30T00:00:00Z)`. It produced:

- 1,440 / 1,440 expected one-minute observations;
- 288 / 288 expected five-minute observations;
- no duplicate or missing expected timestamps;
- exact minute alignment;
- provider-tick alignment for all observed OHLC values;
- mathematically integral volume for all observed rows;
- byte-identical independent one-minute acquisitions;
- 288 / 288 exact provider-5m versus deterministic 5×1m OHLCV matches.

A diagnostic Stage B mapping was saved and reloaded through SF-084 without provider access:

- instrument: `DELTA:BTCUSD`;
- price basis: `traded`;
- adjustment policy: `not_applicable`;
- derived five-minute candles after reload: 288.

The earlier diagnostic dataset id
`9de91e8e0d19ad555344cda5caec6c262e5e14b3f130bf8fa1493f9bd2f3b93f`
predated binding the interpretation-critical product metadata digest into semantic provenance and is
therefore **superseded**. It must not be treated as the durable identity of a qualified dataset.

Pre-registered 10-minute one-minute retention probes on 2025-10-29 and 2024-10-29 each returned
10 rows. This proves bounded availability at those dates, not uninterrupted two-year continuity.

The provider-native product evidence resolved BTCUSD product id 27 as a perpetual future with
contract value 0.001 BTC, tick size 0.5, underlying asset BTC, quoting asset USD and
`settling_asset=USD`.

Do not interpret Delta's API `settling_asset` field as SignalForge's effective/user settlement
currency. Delta India's current BTCUSD contract specification separately describes
"Margin & Effective Settlement Currency" as INR. That distinction belongs to later execution/margin
research and is not collapsed into historical candle semantics here.

## Current gate status

1. **SOURCE IDENTITY — PASS**
2. **SOURCE SEMANTICS — PASS**
3. **CANONICAL REPRESENTABILITY — PASS**
4. **BOUNDED OFFLINE REUSE — PASS for bounded personal/internal academic research use**

Delta's official public `trades` WebSocket documentation labels BTCUSD trade field `s` as
"size in contracts". A bounded live semantic probe on 2026-10-31 then observed one complete BTCUSD
minute, 21:46:00Z to 21:47:00Z:

- 26 public trades were observed for the minute;
- the exact sum of documented trade sizes was `473.0` contracts;
- the matching historical 1m candle reported `volume = 473.0`;
- equality was exact.

Combined with the existing Stage B evidence that all historical 1m volumes were mathematically
integral and that all 288 provider 5m volumes exactly equalled the sum of their constituent 1m
volumes, this establishes the bounded BTCUSD traded-price historical candle volume semantic as
**contract quantity**, losslessly representable by canonical integer `HistoricalBar.volume`.

This is a bounded source-contract qualification result, not a claim that every future Delta
instrument necessarily uses the same volume unit. A different product/asset class must qualify its
own source semantics.

Delta's official support/API material expressly presents historical data for quantitative analysis
and strategy backtesting. Delta Exchange India's Terms permit use of Exchange content for the user's
own personal use and apply the stated restrictions expressly to API data; the Terms restrict
non-personal, public or commercial use without prior written consent. The Terms also contemplate
information being stored/backed up on a user's own systems.

SignalForge's qualified workflow is deliberately narrower than those restricted uses: bounded
acquisition through the documented API, protected local retention, offline SF-084 reload and repeated
personal/internal academic research into strategy provenance. On that stated non-public,
non-commercial basis, SF-087 treats bounded offline reuse as sufficiently supported.

This qualification does **not** establish redistribution, publication of raw Delta market data,
resale, third-party data-service use, or broader commercial archival rights. Raw provider OHLCV
remains outside Git; only sanitized hashes and qualification reports are retained in the repository.

`research_retention_depth = PARTIAL`: bounded one-year and two-year probes succeeded, but a full
research horizon has not been acquired and continuity across that horizon has not been validated.

All four SF-087 gates now PASS, so this bounded source contract is **QUALIFIED** for SignalForge's
personal/internal academic research workflow.

This does not mean the 24-hour qualification sample is a sufficient research dataset. The next
research step still requires an appropriately sized historical dataset and separately defined BTC
strategy semantics before any performance backtest.


## Durable evidence identifiers

Raw provider OHLCV artifacts remain outside Git pending rights clarification. The following
non-market-data identifiers are retained durably so the evidence chain does not disappear when
temporary Actions artifacts expire.

Qualification workflow:
- GitHub Actions run: `41236336078`
- artifact id: `13055606961`
- artifact digest:
  `sha256:1382ee96d06ef4fbb41f6d9a00acf3dd0edde9b209913835a78efd6d2a6d28ca`

Stage B provider evidence:
- product metadata raw SHA-256:
  `20c5934250bedc469f9eb951343e6894223268d0fdedb430210dd80b3a46ae4d`
- interpreted product metadata semantic SHA-256:
  `ed75ad70ae87faa95deba5f9c2860067ca63c09f6c4b5d3dc5f7aa6d384b1355`
- independent 1m response #1 SHA-256:
  `7f8dd51556757efc1730dcb3a1ff202409e1fca83b8b80cc2e24068569b9870d`
- independent 1m response #2 SHA-256:
  `7f8dd51556757efc1730dcb3a1ff202409e1fca83b8b80cc2e24068569b9870d`
- matching 5m response SHA-256:
  `1975113b213529ed280309a29edbb32b94247578bc9116bcb1ece256c924ada2`


Volume semantic probe:
- GitHub Actions run: `41245086613`
- job id: `124666740617`
- observed UTC minute: `2026-10-31T21:46:00Z`
- public trade count: `26`
- exact sum of trade sizes: `473.0` contracts
- matching historical 1m candle volume: `473.0`
- exact equality: `true`
- trade-message evidence SHA-256:
  `3ecf2ec2290b5d48d002e530c9483188329c52b918ce3bb599ac117e8e55208e`
- candle-response SHA-256:
  `50c8017ede3f365cebf76d3349946ae9bf0680c00783d536f652e5edc637248f`

Retention probes:
- 2025-10-29 1m response SHA-256:
  `6d12eaec03c742b2dcefe474c2602530a235c51904c691afacf4529654befdd9`
- 2024-10-29 1m response SHA-256:
  `ad879cda37a608cf7f46d64d409d8a7b662687bdf72037bc965f07a38bd274c4`

The provider's raw product-response bytes differed for later retention probes even though the
interpretation-critical product fields used by SignalForge remained equal. For dataset provenance,
SignalForge therefore binds the stable semantic digest of those interpretation-critical fields,
while retaining raw-response hashes separately as acquisition evidence.


## Repository implementation status

The implementation provides deterministic exact-numeric parsing, source-shape inspection,
timestamp-bound translation, exact 1m→5m comparison, canonical mapping and write-once raw-evidence
capture. Normal repository CI remains offline. The temporary provider-evidence workflow used to
obtain the bounded evidence is not part of the intended permanent CI surface.
