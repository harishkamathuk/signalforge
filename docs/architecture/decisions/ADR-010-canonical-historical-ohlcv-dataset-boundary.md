# ADR-010 — Canonical Historical OHLCV Dataset & Bar Boundary

**Status:** Proposed
**Work item:** #189 / DATA-003
**Strategy semantics changed:** No
**Runtime/execution semantics changed:** No
**Schema/migrations changed:** No

## Context

DATA-001 (#186) evaluated free NSE historical-data sources and closed without selecting a canonical
acquisition library:

- nsepython 2.101 was rejected because the observed historical cash-equity path is daily/EOD only;
- OpenChart 0.2.0 was rejected because the observed high-level path did not preserve requested
  instrument identity and bounded historical retrieval did not yield trustworthy instrument data;
- nsemine 2.2.1 was retained as a fallback because exact BAJAJ-AUTO identity and useful 1-minute
  and 5-minute OHLCV were demonstrated, but fresh repeatability and retention-depth validation were
  blocked by transport failures.

The current Research Harness is event-oriented:

```text
ReplaySource
    ↓
ReplayInput
    ↓
MarketEvent
```

That boundary is correct for historical event/tick sources but is not a legitimate reason to invent
intra-bar chronology for OHLCV-only data.

SignalForge therefore needs a provider-neutral historical-bar contract that can preserve observed
bar facts, produce deterministic completed candles for indicator/signal research, and retain enough
provenance to reproduce a dataset without silently changing execution semantics.

## Decision

Introduce a distinct **canonical historical OHLCV dataset boundary**.

This boundary is upstream of strategy evaluation and separate from `ReplaySource -> MarketEvent`.
It represents observed or deterministically derived bar facts. It must never manufacture
`MarketEvent` chronology.

The conceptual research path becomes:

```text
external historical provider
        ↓
provider adapter / acquisition
        ↓
raw provider response retained or referenced
        ↓
canonical historical 1m bars + quality/provenance
        ↓
deterministic SignalForge 1m → 5m aggregation
        ↓
canonical completed 5m candles
        ↓
indicators / completed-candle strategy evaluation
```

A separate later decision is required before OHLCV-only data may be used to simulate entry/stop/
target sequencing when multiple relevant levels can occur inside the same source interval.

## 1. Canonical bar identity

One canonical historical bar is identified by:

- `instrument_id` — SignalForge canonical instrument identity;
- `interval` — explicit bar duration, initially 1 minute for stored source bars;
- `bucket_start` — timezone-aware start of the SignalForge canonical half-open interval;
- `bucket_end` — timezone-aware end, with `[bucket_start, bucket_end)` semantics.

Canonical timestamps use timezone-aware datetimes. Dataset serialization must preserve a single
unambiguous instant representation. UTC is preferred for physical storage; session calculations
use the applicable exchange timezone, currently Asia/Kolkata for NSE.

The provider timestamp is **not** the canonical bucket identity. Provider timing evidence is
retained separately:

- raw timestamp value where available;
- raw timestamp unit/encoding where known;
- provider/library interpreted timestamp;
- provider/library interval label convention where known;
- canonicalisation rule/version used to assign the canonical bucket.

Provider-specific timestamp repair or heuristics must remain in the acquisition/canonicalisation
adapter. They must not be hidden inside the canonical historical-bar model.

## 2. Canonical OHLCV schema and invariants

The minimum canonical stored bar contract is conceptually:

```text
instrument_id
interval
bucket_start
bucket_end
open
high
low
close
volume
quality
source_provider
source_record_count
provider_timestamp_raw
provider_timestamp_interpreted
canonicalisation_version
```

The implementation may use typed domain models and additional provenance fields, but must preserve
these semantics.

### Price and volume

- OHLC prices use SignalForge decimal price semantics; binary floating-point values are not
  canonical identity.
- Prices must be strictly positive for a present bar.
- Volume is an integer and must be non-negative.
- No bar may violate:
  - `low <= open <= high`;
  - `low <= close <= high`;
  - `low <= high`.

### Ordering and uniqueness

Within one instrument and interval:

- canonical `bucket_start` values are strictly increasing in serialized logical order;
- at most one canonical bar record exists per bucket;
- duplicated provider observations must be detected before canonical uniqueness is asserted;
- contradictory duplicate values are a validation failure, not an arbitrary last-write-wins case.

## 3. Missing observations and bar quality

SignalForge must distinguish **missing evidence** from **zero trading activity**.

An absent provider row does not prove that no trade occurred during that minute.

The historical bar quality vocabulary uses the existing canonical candle concepts where
appropriate:

- `VALID` — the source supplied a bar that passed structural validation for that exact canonical
  bucket;
- `INCOMPLETE` — OHLCV is present but one or more required constituent observations are absent
  for a derived aggregate;
- `MISSING` — no source bar is available for the canonical interval and no OHLCV values may be
  fabricated;
- `CORRUPT` — source data violates required invariants or is internally contradictory.

`STALE` remains principally a live-market-data concept and is not required merely because a
historical bucket is absent.

No flat bar may be synthesized solely to fill a gap.

If an upstream provider explicitly and reliably represents a zero-trade interval as a real record,
that fact may be preserved as provider evidence, but it must not be inferred from absence.

## 4. Deterministic 1-minute → 5-minute aggregation

For Strategy V1 research, canonical five-minute candles are derived from canonical one-minute
source bars wherever one-minute data is the authoritative stored research input.

### Session anchoring

Five-minute buckets use the regular NSE session grid anchored at 09:15 Asia/Kolkata:

```text
09:15–09:20
09:20–09:25
...
15:25–15:30
```

Intervals remain half-open `[start, end)`.

Holiday, exceptional-session and exchange-calendar handling must be supplied by an explicit
calendar/session contract; DATA-003 does not infer special sessions.

### Aggregation formula

For a five-minute bucket whose ordered constituent one-minute bars are
`m1, m2, m3, m4, m5`:

- open = first constituent open;
- high = maximum constituent high;
- low = minimum constituent low;
- close = last constituent close;
- volume = sum of constituent volume.

The aggregation is deterministic and provider-neutral.

### Completeness

A five-minute bucket is `VALID` only when all five expected canonical one-minute buckets are
present and structurally valid.

If at least one expected constituent minute is absent but one or more valid constituent bars are
present:

- an aggregate may be calculated for diagnostic/provider reconciliation purposes;
- its quality is `INCOMPLETE`;
- it must not be silently promoted to `VALID`;
- numerical equality with a provider-supplied five-minute bar does not prove complete minute
  coverage.

If no constituent observations are present, the canonical bucket is `MISSING` and has no OHLCV.

Corrupt constituent data makes the derived bucket unusable until the contradiction is resolved.

The canonical aggregator does not apply provider-specific timestamp offsets, rounding rules or
label fixes.

## 5. Provider-supplied 5-minute bars

Provider-supplied five-minute bars may be retained as **reconciliation evidence**, but they are not
automatically authoritative over SignalForge-derived five-minute candles when canonical one-minute
input is available.

A reconciliation result must distinguish at least:

- `GRID_COMPLETE` / `GRID_INCOMPLETE`;
- `OHLCV_MATCH` / `OHLCV_MISMATCH`.

These are independent dimensions.

The DATA-001 nsemine evidence demonstrated why this distinction matters: incomplete one-minute
coverage can numerically match a provider aggregate, while a provider/library five-minute
timestamp transformation can also yield a non-canonical label.

## 6. Dataset provenance manifest

Every immutable historical dataset version must carry a manifest sufficient to identify what was
acquired and how it became canonical.

Minimum provenance includes:

- provider/source name;
- acquisition library/adapter and version;
- upstream endpoint or endpoint family;
- requested instrument identity;
- resolved provider instrument identity;
- SignalForge `instrument_id`;
- requested time range;
- returned time range;
- interval requested and interval returned;
- acquisition timestamp;
- provider/raw timestamp representation;
- timezone interpretation;
- canonicalisation version;
- row count before canonicalisation where available;
- canonical row count;
- missing expected intervals;
- duplicate observations;
- corrupt/rejected rows;
- content hash;
- known provider retention constraints;
- known corporate-action limitations;
- acquisition warnings/errors relevant to interpretation.

Secrets, session cookies and authentication material are never provenance.

## 7. Immutable dataset format and identity

Parquet is the preferred analytical storage format for canonical historical bars because it is
columnar, typed, widely supported and appropriate for larger research datasets.

Parquet is a storage choice, not the semantic contract. Canonical identity is derived from
normalized semantic content plus the canonicalisation contract, not from incidental file bytes
whose metadata or writer implementation may differ.

A dataset version should therefore separate:

### Semantic identity

Material to dataset identity:

- canonical instrument identity;
- interval;
- ordered canonical bar content;
- bar quality;
- canonical bucket timestamps;
- canonicalisation version;
- any source/provenance field explicitly declared material to interpretation.

### Operational provenance

Recorded but not automatically identity-changing:

- acquisition wall-clock timestamp;
- local filesystem path;
- download host/process details;
- compression/layout metadata.

Acquiring byte-equivalent logical market data at a different wall-clock time must not create a
different semantic dataset merely because the download happened later.

If upstream source content changes, the canonical content hash and therefore dataset version must
change.

## 8. Corporate actions

Historical OHLCV must explicitly state whether prices/volumes are:

- raw/unadjusted;
- split-adjusted;
- dividend-adjusted;
- otherwise transformed;
- unknown.

SignalForge must not silently mix adjustment policies inside one canonical dataset identity.

DATA-003 does not choose an adjustment policy. That requires evidence from the eventual provider
and the research question.

## 9. Research Harness boundary

The existing event-level Research Harness remains authoritative for event/tick replay.

Historical-bar research adds a distinct legitimate input boundary for completed-candle validation.

The first implementation vertical should support:

```text
immutable canonical 1m dataset
        ↓
quality validation
        ↓
deterministic 5m candles
        ↓
existing canonical indicator calculations
        ↓
existing registered Strategy V1 completed-candle evaluation
        ↓
signal/decision evidence
```

It must not:

- expand OHLCV bars into fake ticks;
- claim exact entry/stop/target chronology from OHLCV alone;
- silently reuse event-level fill semantics when ordering is ambiguous;
- alter Strategy V1 indicator/signal thresholds;
- create a second implementation of indicator mathematics.

A later historical execution/lifecycle work item must explicitly define what happens when entry,
stop and/or target levels are reachable inside the same lowest-resolution historical bar.

## 10. Relationship to existing domain models

The existing `CompletedCandle`, `CandleInterval` and `CandleQuality` concepts remain the
canonical completed-candle semantics.

DATA-003 does **not** require changing them immediately.

The persisted historical-bar record needs additional source timestamp/provenance fields that do
not belong in the current runtime `CompletedCandle` fact. A later implementation should therefore
prefer a dedicated historical storage/input model that validates into `CompletedCandle` rather
than bloating the runtime candle with provider-specific metadata.

Likewise, the existing `DatasetDefinition` currently identifies event-source datasets through
`source_id`. Historical-bar dataset implementation must extend or introduce a strategy-neutral
dataset-source identity without reinterpreting existing event dataset identities.

## 11. Failure policy

Canonicalisation fails explicitly when:

- requested and resolved instrument identities contradict;
- timestamps cannot be mapped to canonical buckets under the declared canonicalisation version;
- duplicate source rows conflict;
- OHLC invariants fail;
- volume is negative;
- the source interval is not the declared interval;
- timezone interpretation is unknown where required for bucket assignment;
- durable manifest/content identity contradicts the persisted dataset.

The system must not guess through contradictory durable evidence.

Missing intervals are quality facts and do not by themselves imply corruption.

## 12. DATA-001 evidence carried forward

The BAJAJ-AUTO nsemine evidence is retained as a useful contract example, not as a provider
selection:

- exact provider identity was established as BAJAJ-AUTO-EQ / 16669 / Equity / NSE;
- one-minute source data returned 368 of 375 expected regular-session minute labels;
- seven expected minute labels were absent;
- returned one-minute rows were monotonic, on-grid and had no duplicate timestamps, OHLC
  invariant violations or negative volume;
- 73 complete five-minute buckets derived from one-minute data matched provider OHLCV exactly;
- two incomplete buckets also matched numerically, which did not prove complete constituent
  coverage;
- a provider/library five-minute timestamp transformation produced an off-grid 15:11 label for
  the row assigned to the canonical 15:15 bucket.

These observations directly motivate explicit canonical bucket identity, independent quality
dimensions, and separation of provider timestamps from SignalForge timestamps.

## Consequences

### Positive

- acquisition libraries remain adapters rather than owners of research semantics;
- provider replacement does not require a strategy rewrite;
- missing data is auditable rather than silently repaired;
- derived five-minute candles are deterministic;
- experiment provenance can identify exactly which market facts were used;
- event replay and bar research no longer need to be conflated.

### Costs

- historical-bar storage needs its own typed boundary and provenance manifest;
- execution/lifecycle backtesting from bars remains a separate unresolved problem;
- exchange calendar and corporate-action policy require explicit follow-up decisions when needed.

## Smallest implementation follow-up

After this ADR is accepted, the next implementation work item should be a **single-instrument
historical-bar thin vertical**, not a broad ingestion platform.

It should:

1. define typed canonical historical 1-minute bar + manifest models;
2. load one deterministic local fixture;
3. validate timestamps/invariants/quality;
4. derive canonical five-minute candles deterministically;
5. feed those completed candles through the existing indicator and Strategy V1 evaluation path;
6. emit reproducible signal/decision evidence;
7. include unit/integration tests for missing minutes, duplicate/conflicting rows and content
   identity.

It should explicitly exclude:

- network acquisition;
- provider selection;
- event/tick synthesis;
- entry/stop/target fill simulation;
- portfolio/multi-security work;
- strategy parameter changes.

## Non-goals

DATA-003 does not:

- select or repair a historical-data provider;
- implement nsemine transport changes (#188);
- choose a paid provider;
- rewrite `ReplaySource`;
- define synthetic ticks;
- define ambiguous intra-bar execution ordering;
- optimize Strategy V1;
- implement a multi-security data lake;
- establish strategy profitability.

## Decision boundary

This ADR changes the **architecture contract for historical research data**, not trading strategy
semantics.

Any future change that lets bar-only data determine entry, stop, target or realized-R outcomes
under ambiguous intra-bar ordering is a separate material decision and must be explicitly reviewed.
