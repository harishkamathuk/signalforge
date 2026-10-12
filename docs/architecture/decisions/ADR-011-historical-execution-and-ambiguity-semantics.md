# ADR-011 — Strategy-Agnostic Historical Execution and Ambiguity Semantics

**Status:** Proposed  
**Work item:** SF-077 / GitHub #196  
**Strategy semantics changed:** No  
**Runtime/execution semantics changed:** No — this ADR defines historical simulation semantics only  
**Schema/migrations changed:** No

## Context

SignalForge can now consume canonical historical one-minute OHLCV, derive deterministic completed
five-minute candles, compute strategy-declared indicators, and invoke registered strategies through
the shared completed-candle Strategy boundary.

That research path can establish whether a strategy would have emitted an actionable completed-candle
decision. It cannot yet establish a historical trade outcome.

The existing live/PAPER lifecycle is event-oriented. While ARMED, strategy policy consumes ordered
`MarketEvent` observations and shared lifecycle code reacts to the first qualifying event. Historical
OHLCV does not contain that ordered event chronology.

Therefore historical simulation must not manufacture ticks, synthesize an OHLC traversal order, or
construct fake MarketEvent chronology merely to reuse the event-oriented runtime.

The purpose of this ADR is to define what historical OHLCV can prove, what must be modeled, what is
ambiguous, and what evidence may be included in deterministic research statistics.

## Decision summary

Adopt a **bar-evidence historical execution model** with explicit separation between:

1. **observed facts** — canonical OHLCV and session/time boundaries;
2. **strategy intent** — entry, invalidation, validity, stop and post-fill economics supplied through
   typed strategy-facing contracts;
3. **execution assumptions** — deterministic fill/slippage/tick-normalization rules identified by
   configuration/version;
4. **derived conclusions** — lifecycle outcomes that are invariant across every intra-bar ordering
   compatible with the observed bar;
5. **ambiguity** — multiple lifecycle outcomes remain compatible with the same observed bar.

Historical research must never present an execution assumption or one possible intra-bar ordering as
an observed market fact.

## Scope of genericity

"Strategy-agnostic" in this ADR means strategy-neutral within the currently accepted SignalForge
long-entry lifecycle family.

The current core contract assumes:

- an actionable strategy can produce an ARMED entry opportunity;
- entry has a positive price trigger;
- the position has a stop;
- positive-risk positions have a target;
- risk is entry fill minus stop for the current long-only domain;
- compulsory intraday safety is shared runtime policy.

This ADR does **not** claim that the current Strategy protocol already supports every conceivable
strategy shape.

In particular, the current protocol/domain does not natively represent:

- immediate/market entry with no price trigger;
- targetless positive-risk positions;
- short-side economics;
- arbitrary multi-leg or scale-in/scale-out execution.

Those are explicit current architecture limitations, not requirements for SF-077 to solve.

## Historical execution vocabulary

### Observed fact

A value directly present in or deterministically derived from canonical historical data without an
execution model assumption.

Examples:

- one-minute bar open/high/low/close;
- one-minute bucket start/end;
- session boundary;
- whether a price level lies inside the observed `[low, high]` range;
- whether the opening price is already through a level.

### Reachability

A level is **reachable** in a bar when the observed OHLC range proves that at least one qualifying
price at or beyond that level occurred during the bar.

Reachability does not establish when the level occurred relative to another reachable level.

### Modeled execution fact

A deterministic simulated value created under an explicitly identified execution-assumption profile.

Examples:

- modeled fill price;
- slippage adjustment;
- tick normalization;
- modeled exit price.

These values are valid research artifacts but are not observed market facts.

### Determinate lifecycle conclusion

A lifecycle outcome is **determinate** when every event ordering compatible with the observed bar and
the accepted strategy/execution contract leads to the same lifecycle state/outcome.

### Ambiguous lifecycle conclusion

A lifecycle outcome is **ambiguous** when two or more materially different lifecycle outcomes remain
compatible with the same observed bar.

Ambiguity must be first-class evidence and must not be silently resolved through a conventional
OHLC path such as O-H-L-C or O-L-H-C.

## Strategy-to-historical-simulation boundary

Historical simulation must reuse strategy-owned policy without importing strategy IDs or strategy
formulas into the simulator.

The historical simulator may consume:

- completed-candle Strategy decisions;
- typed entry/arming intent;
- strategy validity/expiry intent;
- typed pre-entry invalidation intent;
- typed strategy-specific entry-cutoff intent, when present;
- accepted post-fill economics derived from the modeled Fill;
- shared session-safety rules.

### Required implementation clarification for SF-078

The current `ArmIntent` exposes trigger, stop and validity but does not declaratively expose two
strategy-owned ARMED policies that matter to historical execution:

- strategy-specific pre-entry invalidation;
- strategy-specific earlier entry cutoff.

Live/PAPER currently obtains those behaviors from `Strategy.evaluate_armed_market_event(...)` and
`Strategy.evaluate_armed_time(...)`.

SF-078 must **not** solve this by creating synthetic MarketEvent objects from OHLCV or by duplicating
the same policy in a historical-only code path.

Instead, SF-078 must first introduce the smallest typed declarative ARMED policy needed by the
existing strategies and make that policy authoritative for both live/PAPER and historical mechanics.

The implementation should remain a known typed lifecycle contract, not a strategy DSL.

For the currently registered strategies this must be able to express at least:

- momentum V1: price trigger, signal-low pre-entry invalidation, one-following-candle validity and
  the strategy-specific 15:05 IST entry cutoff;
- RSI mean-reversion V1: price trigger, no price-based pre-entry invalidation, one-following-candle
  validity and no strategy-specific earlier entry cutoff.

Shared compulsory session safety remains separate from strategy-specific cutoff intent.

Live and historical paths must consume the same accepted intent so the historical simulator does not
become a second implementation of strategy semantics.

## Strategy-facing fill economics boundary

The existing `domain.execution.Fill` is an authoritative execution fact whose current modes are
PAPER and LIVE. A historical simulator must not manufacture a PAPER/LIVE Fill merely to reuse
`Strategy.post_fill_economics(...)`.

SF-078 must therefore introduce the smallest strategy-facing fill view required by post-fill
economics, or an equivalent typed boundary, so that:

- live/PAPER passes values originating from the authoritative real/PAPER Fill;
- historical research passes a modeled historical fill carrying explicit execution-assumption
  provenance;
- strategy code receives the same economic inputs in both modes;
- historical modeled fills are never misidentified as broker/PAPER execution facts.

The current registered strategies only require the accepted entry fill price to derive their
post-fill economics. The new view must not expose broader execution state without evidence that a
strategy needs it.

Adding `HISTORICAL` to `ExecutionMode` solely to force research through the authoritative Fill
entity is not the preferred design, because execution mode and research evidence are different
concepts.

Historical exits likewise require research evidence types rather than fabricated PAPER/LIVE Exit
facts.

## One-minute bar evidence rules

The canonical one-minute bar is the finest historical observation used by the first simulator.

For a long price level `L`:

- `open >= L` proves the first observed bar price is already at/through an upward trigger/target;
- `high >= L` proves an upward level was reachable during the bar;
- `open <= L` proves the first observed bar price is already at/through a downward stop/invalidation;
- `low <= L` proves a downward level was reachable during the bar.

These facts do not prove ordering between two levels that are both reachable in the same bar.

The simulator must use half-open bucket time semantics consistently with canonical historical bars.

## Entry eligibility

For an active long entry trigger:

### No trigger reach

If `high < trigger`, the trigger was not reached during that bar.

### Gap-through at bar open

If `open >= trigger`, trigger eligibility is determinate at the bar opening observation unless a
higher-priority shared time/session rule has already expired the opportunity at that exact boundary.

The modeled entry base price is the observed `open`, not the trigger.

### Intrabar trigger reach

If `open < trigger <= high`, the bar proves that the trigger condition became reachable, but the
exact triggering trade price/time is unobserved.

If no competing strategy invalidation, expiry/session boundary, or post-fill exit can materially
change the lifecycle result within the same bar, entry occurrence is determinate and the execution
model may use the tradable trigger as its modeled base fill price.

That use of the trigger price is an explicit execution assumption, not an observed fill.

If a competing condition is reachable in the same bar and ordering affects the lifecycle, the result
is ambiguous.

## Fill-price assumptions

All historical execution must reference an immutable, versioned execution-assumption profile.

The profile must specify, at minimum:

- entry slippage rule;
- stop-exit slippage rule;
- target-exit slippage rule;
- compulsory-exit slippage rule;
- tick-normalization version/rules;
- gap-through treatment.

No research run may silently inherit ambient/default slippage assumptions.

A zero-slippage profile is acceptable for deterministic fixtures/tests but must be explicitly
identified as such. Mature strategy evidence must include realistic slippage/cost sensitivity
separately.

### Directional normalization

For the current long-only domain:

- modeled buy fills are rounded in the adverse/upward direction after slippage;
- modeled sell fills are rounded in the adverse/downward direction after slippage.

Existing canonical NSE tick rules remain shared infrastructure; strategies do not perform tick
normalization.

## Gap-through semantics

Gap-through cases are distinguishable because bar open is an observed price.

For long entry:

- `open >= trigger` uses open as the modeled execution base.

For an already-open long position:

- `open <= stop` makes stop exit determinate at the opening observation and uses open as the modeled
  execution base;
- `open >= target` makes target exit determinate at the opening observation and uses open as the
  modeled execution base, subject to higher-priority compulsory-session handling.

A gap may cross more than one relevant level. If multiple lifecycle actions are possible at the same
opening observation and the accepted shared priority rules do not resolve them, the case is ambiguous.

## Post-fill economics

The historical simulator must construct a modeled historical fill first.

Strategy post-fill economics are then derived through the shared strategy-facing fill-economics
boundary using that modeled fill. The authoritative PAPER/LIVE Fill entity itself must not be
fabricated for historical research.

Therefore:

- risk is based on the modeled actual fill, not on the signal or trigger price;
- target economics remain strategy-owned;
- exchange tick normalization remains shared;
- the simulator must not contain Strategy V1's 1.5R formula or any other strategy-specific target rule.

A non-positive-risk modeled fill must follow the same shared rejection semantics as the runtime.

## Open-position exit evidence

For an already-open long position and a one-minute bar before compulsory exit:

### Neither level reachable

If `low > stop` and `high < target`, the trade remains open.

### Stop only reachable

If `low <= stop` and `high < target`, stop exit is determinate.

If the bar opens below/equal stop, modeled base exit is open; otherwise modeled base exit is stop.

### Target only reachable

If `high >= target` and `low > stop`, target exit is determinate.

If the bar opens above/equal target, modeled base exit is open; otherwise modeled base exit is target.

### Stop and target both reachable

If `low <= stop` and `high >= target` and neither opening condition/shared priority resolves the
case, the bar cannot establish which exit occurred first.

The outcome is ambiguous.

The simulator must not choose stop-first or target-first merely to produce a point result.

## Entry-bar ambiguity

A single bar may contain enough range to support both entry and a later stop/target outcome.

Examples:

- trigger and pre-entry invalidation both reachable;
- trigger and post-fill stop both reachable;
- trigger and post-fill target both reachable;
- trigger, stop and target all reachable.

Where ordering changes whether a trade opens or how it closes, the lifecycle outcome is ambiguous.

The simulator must retain all material possible outcomes that are consistent with:

- observed bar facts;
- shared session priority;
- accepted strategy intent;
- accepted execution assumptions.

## Time, validity and session boundaries

Time boundaries are authoritative facts and take precedence when their ordering relative to a bar
observation is known.

### Exact bar boundary

If strategy validity or compulsory session cutoff equals a one-minute bucket start, the opportunity
is expired/forced before processing later observations in that bucket according to the shared runtime
priority.

For example, the current compulsory exit at 15:15 IST is evaluated at that boundary before
strategy price-trigger/stop/target handling for observations at or after 15:15.

### Boundary inside a one-minute bar

If a strategy-specific validity/cutoff falls strictly inside a one-minute bucket, OHLCV does not prove
whether a reachable trigger occurred before or after the time boundary.

If this difference changes the lifecycle, the case is ambiguous.

### Compulsory intraday exit

For an open position at the shared compulsory-exit boundary, the first canonical bar opening
observation at/after the boundary is the modeled execution base for forced exit under the initial
bar-resolution simulator.

This is an execution assumption required by bar-resolution data and must be recorded in the execution
profile/provenance.

The simulator must not allow strategy policy to extend beyond the shared compulsory safety boundary.

## Conceptual typed contract

The following shapes are normative at the responsibility level but illustrative at the exact Python
naming/API level. SF-078 may adjust names while preserving these ownership boundaries.

```python
class HistoricalOutcomeCertainty(StrEnum):
    DETERMINATE = "determinate"
    BOUNDED_AMBIGUOUS = "bounded_ambiguous"
    UNRESOLVED = "unresolved"


class PriceBarrierDirection(StrEnum):
    AT_OR_ABOVE = "at_or_above"
    AT_OR_BELOW = "at_or_below"


@dataclass(frozen=True)
class PriceBarrierIntent:
    price: Price
    direction: PriceBarrierDirection
    reason: str


@dataclass(frozen=True)
class HistoricalArmedPolicyIntent:
    raw_trigger: Price
    stop_price: Price
    valid_until: datetime
    pre_entry_invalidation: PriceBarrierIntent | None
    strategy_entry_cutoff_at: datetime | None


@dataclass(frozen=True)
class StrategyEntryFillView:
    fill_price: Price
    filled_at: datetime


@dataclass(frozen=True)
class HistoricalExecutionAssumptionProfile:
    profile_id: str
    version: str
    entry_slippage: object
    stop_slippage: object
    target_slippage: object
    forced_exit_slippage: object
    tick_rule_version: str


@dataclass(frozen=True)
class BarReachabilityEvidence:
    bar_start: datetime
    bar_end: datetime
    open: Price
    high: Price
    low: Price
    close: Price
    reachable_actions: tuple[str, ...]


@dataclass(frozen=True)
class HistoricalPossibleOutcome:
    terminal_state: str
    exit_reason: str | None
    modeled_entry_fill: Price | None
    modeled_exit_fill: Price | None
    outcome_r: Decimal | None


@dataclass(frozen=True)
class HistoricalExecutionOutcome:
    certainty: HistoricalOutcomeCertainty
    ambiguity_reasons: tuple[str, ...]
    possible_outcomes: tuple[HistoricalPossibleOutcome, ...]
```

Important constraints:

- `HistoricalArmedPolicyIntent` is strategy-owned policy expressed through a known typed lifecycle
  contract, not a generic rule language.
- `StrategyEntryFillView` is a strategy-facing economic view, not an authoritative execution fact.
- slippage fields above are placeholders for known versioned model types; SF-078 must not use
  arbitrary callables/executable config.
- `possible_outcomes` contains materially distinct supported branches, not every synthetic price
  path through the bar.
- result/evidence identities must be deterministic from strategy/config/dataset/assumption profile
  and causal bar/opportunity identity.

## Ambiguity taxonomy

SF-078 must support at least the following classifications:

- `ENTRY_VS_INVALIDATION`
- `ENTRY_VS_EXPIRY`
- `ENTRY_VS_STRATEGY_CUTOFF`
- `ENTRY_VS_SESSION_CUTOFF`
- `ENTRY_VS_POST_FILL_STOP`
- `ENTRY_VS_POST_FILL_TARGET`
- `STOP_VS_TARGET`
- `MULTIPLE_COMPETING_ACTIONS`
- `UNSUPPORTED_STRATEGY_POLICY`

Additional classifications may be added only when they represent a real distinguishable ambiguity,
not as free-form strategy logic.

## Ambiguous outcome representation

Adopt **explicit ambiguity classification plus possible-outcome bounds**.

A historical opportunity produces one of:

- **DETERMINATE** — exactly one lifecycle/economic outcome is supported;
- **BOUNDED_AMBIGUOUS** — a finite set/range of materially different outcomes is supportable from
  the same observed evidence;
- **UNRESOLVED** — the current bar-resolution contract cannot safely enumerate the material outcome
  set.

For BOUNDED_AMBIGUOUS cases, evidence must preserve the possible terminal outcomes rather than only a
single optimistic/pessimistic scalar.

Examples may include:

- no trade vs entered-and-stopped;
- stopped vs targeted;
- entered vs expired;
- a minimum/maximum R range when every possible branch produces a closed trade.

### Research statistics rule

Only DETERMINATE trades may enter ordinary point-estimate statistics such as:

- win rate;
- average R / expectancy;
- profit factor;
- deterministic equity curve;
- deterministic drawdown.

Ambiguous opportunities must be reported separately.

A research report may additionally publish explicit lower/upper sensitivity bounds that include
ambiguous cases, but those must be labeled as bounded sensitivity results and must never be mixed
silently into the deterministic point estimate.

Rejecting ambiguous trades from point statistics is not equivalent to deleting them: their count,
rate, possible outcomes and concentration must remain visible.

## Evidence and provenance

Each historical execution opportunity must retain enough information to reproduce why its result was
classified as determinate or ambiguous.

Minimum evidence:

- strategy ID/version;
- strategy config hash;
- historical dataset ID;
- instrument ID;
- decision/signal candle interval;
- strategy decision/reasons;
- raw and tradable entry trigger intent;
- pre-entry invalidation intent, if any;
- strategy-specific entry cutoff, if any;
- validity/expiry boundary;
- stop intent;
- execution-assumption profile ID/version;
- relevant one-minute bar identities/OHLCV;
- reachability facts used;
- modeled fill base, slippage and normalized fill;
- post-fill strategy economics;
- target intent where applicable;
- ambiguity classification;
- possible lifecycle outcomes for bounded ambiguity;
- lifecycle transitions for determinate outcomes;
- exit reason/fill/outcome R where determinate;
- compulsory-session rule/version;
- simulator calculation/version identity.

Do not persist fabricated MarketEvent IDs/timestamps for bar-only evidence.

## Three-strategy-shape pressure test

The proposed contract is evaluated against three materially different shapes.

### Shape 1 — intraday_momentum_v1

Exercises:

- multi-indicator completed-candle qualification;
- upward price trigger offset from signal close;
- price-based pre-entry invalidation at signal low;
- one-following-candle validity;
- strategy-specific 15:05 entry cutoff;
- stop at signal low;
- post-fill 1.5R target.

Pressure exposed:

- historical simulation requires declarative pre-entry invalidation and strategy-specific cutoff
  intent shared with live semantics.

### Shape 2 — rsi_mean_reversion_v1

Exercises:

- different indicator composition;
- trigger at signal close rather than offset;
- no price-based pre-entry invalidation;
- no strategy-specific earlier entry cutoff;
- same generic ARMED lifecycle family;
- post-fill 1.0R target.

Pressure exposed:

- the shared contract must support absence of pre-entry invalidation without embedding momentum policy.

### Shape 3 — test-only delayed-breakout execution shape

The design is pressure-tested against this explicit non-production shape:

- long-only completed-candle opportunity;
- raw trigger = signal close × 1.002;
- stop = signal-candle low;
- pre-entry invalidation = a separate downward barrier above the stop (for example a deterministic
  fixture value between signal low and close), proving invalidation is not assumed to equal stop;
- validity = two following five-minute candles;
- strategy-specific earlier entry cutoff = 14:55 IST;
- positive-risk target = 2.0R from modeled entry fill.

This shape is intentionally not registered as a production strategy. It pressure-tests independent
trigger, stop, invalidation, validity, cutoff and post-fill target fields.

The proposed contract can represent all of these differences without adding strategy IDs/formulas to
historical mechanics. SF-078 must implement this as a test-only Strategy shape to convert the design
proof into executable evidence.

### Explicit protocol limits exposed by the pressure test

The current Strategy/domain contract cannot honestly demonstrate these materially different shapes
without prior core changes:

- immediate market entry with no price trigger;
- positive-risk targetless trade;
- short-side trade.

SF-078 must not fake support for those shapes. They remain future architecture work if/when a real
strategy requires them.

## Rejected alternatives

### Fabricate MarketEvent chronology from OHLCV

Rejected because OHLCV does not establish event ordering and this would violate ADR-010.

### Assume a conventional OHLC path

Rejected. O-H-L-C, O-L-H-C or similar traversal rules are model inventions that can materially alter
win rate and expectancy.

### Always choose the adverse outcome

Rejected as the canonical result. Conservative stress testing may be useful as a separate sensitivity
view, but treating the adverse branch as historical truth misstates the evidence.

### Always drop ambiguous opportunities without recording them

Rejected because ambiguity frequency itself is material research evidence and exclusion can bias
results.

### Use optimistic/pessimistic point estimates as primary results

Rejected. Bounds are supplementary sensitivity evidence; the primary deterministic result set must
contain only determinate outcomes.

## Implementation direction for SF-078

The next implementation work item should deliver the smallest single-instrument deterministic
historical execution vertical.

At minimum SF-078 must:

1. introduce typed shared pre-entry invalidation and strategy-specific entry-cutoff intent needed
   to avoid synthetic MarketEvents;
2. migrate both registered strategies/live lifecycle to that shared intent without semantic change;
3. define versioned execution-assumption profile types;
4. define bar reachability and ambiguity result types;
5. simulate one active opportunity at a time over canonical one-minute bars;
6. introduce/use the shared strategy-facing fill view so modeled historical fills can drive
   Strategy post-fill economics without fabricating PAPER/LIVE Fill facts;
7. reuse canonical tick normalization/session safety;
8. emit determinate/bounded/unresolved evidence;
9. exclude ambiguous outcomes from ordinary point-estimate metrics;
10. prove the reusable abstraction against three materially different strategy shapes;
11. add golden tests for gap-through, same-bar trigger/invalidation, entry/stop, entry/target,
    stop/target and compulsory exit boundaries;
12. never construct MarketEvent objects from OHLCV.

## Consequences

Historical research gains an execution model that is deterministic about its assumptions without
claiming false market chronology.

Some opportunities will remain ambiguous at one-minute resolution. That is an expected property of
the evidence, not a simulator defect.

Higher-resolution data may resolve some ambiguity later, but must enter through its own canonical
data contract; the simulator must not infer missing detail.

Point-estimate backtest metrics become deliberately conservative in sample size because ambiguous
trades are excluded from the deterministic result set. Their frequency and bounded outcome
sensitivity remain visible so that research users can judge whether one-minute data is sufficient for
a strategy.

This ADR changes no existing strategy rule. It defines how future historical simulation may represent
those rules honestly.
