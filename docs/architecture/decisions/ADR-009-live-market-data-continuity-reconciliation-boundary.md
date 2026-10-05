# ADR-009 — Live Market-Data Continuity & Reconciliation Boundary

**Status:** Accepted  
**Decision source:** SF-057 / GitHub #115  
**Applies from:** SF-057 onward

## Context

SignalForge now has a live single-security OpenAlgo market-data adapter for PAPER operation.

The existing M7 restart-safe replay path assumes every accepted market input has evidence strong
enough to prove ordering, duplicate delivery and exact restart progression, including a stable source
identity, monotonic source sequence and stable non-null market-event identity.

OpenAlgo ordinary live market-data messages do not provide a genuine stable provider event ID or a
replayable event sequence with equivalent guarantees. SF-056 therefore deliberately leaves
`MarketEvent.source_event_id=None`, uses observed Quote snapshots, and re-baselines after a real
disconnect instead of inventing missing trades.

A process restart or feed disconnect can consequently create an interval whose market chronology
SignalForge cannot prove. That uncertainty can affect:

- forming-candle state;
- indicator continuity;
- ARMED trigger chronology;
- OPEN stop/target chronology;
- compulsory exit chronology;
- exact market-input restart semantics.

Transport recovery alone cannot restore historical certainty.

## Decision

SignalForge will **fail closed across any unprovable live market-data gap**.

The live runtime must distinguish three separate concepts:

1. **transport/feed health** — whether the current adapter connection is operating;
2. **market-history continuity** — whether SignalForge can prove that no relevant market chronology
   is missing from the runtime's observed stream;
3. **durable lifecycle state** — the last authoritative persisted Signal/ARMED/Trade/Position state.

These concepts must not be conflated.

A WebSocket reconnect that returns the adapter to HEALTHY does not, by itself, restore
market-history continuity.

## Live input identity

SignalForge must not manufacture provider evidence.

For live OpenAlgo input:

- do not synthesize `source_event_id` from timestamp, price, quantity, volume, hashes or tuples;
- do not claim a provider sequence that OpenAlgo does not supply;
- do not apply replay exactly-once guarantees to a non-replayable live source;
- do not feed live events through `CanonicalMarketInput.from_replay_input` merely to reuse replay
  orchestration.

Replay/backtest and live modes continue to share strategy, lifecycle, candle and indicator semantics,
but source guarantees may differ where the external provider contract genuinely differs.

## Normal continuous operation

While live chronology remains proven continuous, processing order is:

```text
MarketEvent
→ lifecycle market-event processing
→ CandleEngine
→ completed candle, if any
→ lifecycle completed-candle processing
→ IndicatorEngine
→ strategy evaluation using current feed state
→ lifecycle evaluation
→ atomic persistence of synchronous durable consequences
```

Only completed canonical candles advance indicators and strategy evaluation.

ARMED and OPEN lifecycle states continue to consume ordered observed market events while continuity
remains proven.

Only a HEALTHY feed may make a newly qualified strategy evaluation actionable through the existing
guard contract.

## Gap behaviour

A genuine process/feed gap that leaves market chronology unprovable invalidates same-run
price-sensitive continuation.

The gap does **not** erase or automatically terminalise the durable trading lifecycle itself.

### IDLE

If no ARMED setup or OPEN position exists, the runtime still must not silently continue indicator or
strategy progression across an unproven gap. A new operational session/run may begin only from a
continuity boundary the runtime can establish safely.

### ARMED

If an ARMED setup exists when continuity is lost:

- preserve the durable ARMED state as the last trusted state;
- do not infer whether the trigger was crossed during the gap;
- do not trigger from the first post-gap quote;
- do not auto-expire merely because the feed later resumes;
- block further same-run price-sensitive progression;
- require reconciliation before any further lifecycle decision.

### OPEN

If an OPEN Trade/Position exists when continuity is lost:

- preserve the durable OPEN state as the last trusted state;
- do not infer stop, target or forced-exit chronology from post-gap data;
- do not auto-close the position;
- do not treat the first post-gap price as proof of what happened during the gap;
- block further same-run price-sensitive progression;
- require reconciliation.

For PAPER M8, reconciliation is an explicit operational/manual boundary. SignalForge must prefer an
honest unresolved PAPER outcome over a fabricated trade history.

## Restart behaviour

M7 recovery remains mandatory before accepting live market data.

Startup ordering is:

```text
configured strategy/run/reference identity
→ RecoveryBootstrap
→ durable compatibility validation
→ hydrate recoverable state
→ establish live-runtime continuity/session state
→ only then start/accept OpenAlgo market data
```

Hydrating durable state does not prove that live market chronology between process instances is
complete.

A process restart therefore does not automatically authorize continuation of a prior live session.
Where continuity cannot be proven, the recovered lifecycle is preserved for reconciliation but
price-sensitive progression remains blocked.

Contradictory or corrupt durable state remains a hard failure.

## Persistence boundary

Live processing must retain atomic durable consequences without pretending that OpenAlgo provides a
replayable market-input checkpoint.

A live-specific persistence transaction may mirror the durable fact set of the replay
`MarketInputCommit` while omitting synthetic provider sequence/event identity.

Existing repositories and persistence facts remain authoritative, including as applicable:

- indicator checkpoints;
- strategy decision facts;
- Signal and ArmedSetup;
- TriggerEvent;
- EntryIntent and Fill;
- PositionOpenOutcome;
- Trade and Position;
- Exit;
- StateTransition.

No schema change is implied by this ADR.

If an accepted live event mutates in-memory candle/lifecycle/indicator state and processing or
persistence subsequently fails, that runtime instance becomes terminal. It must not continue from
memory ahead of PostgreSQL; recovery must begin again from durable state.

## PAPER versus future live-capital operation

ADR-009 applies to the current PAPER M8 runtime.

For eventual real-capital execution, preserving an unresolved OPEN durable position while market
chronology is unavailable is not sufficient as a complete operational safety mechanism.

Future controlled live execution must separately define broker/position reconciliation and any
protective-order, emergency-flattening or equivalent capital-safety policy.

ADR-009 does not authorize or define those mechanisms.

## Rationale

SignalForge prioritizes auditability and recovery correctness over optimistic continuity.

When the provider contract cannot prove what happened during a market-data gap, guessing would
silently change trading outcomes and produce unreproducible history. Preserving the last trusted
durable state and blocking further price-sensitive progression makes the uncertainty explicit.

## Consequences

SF-057 and later live-runtime work must:

- model runtime chronology continuity separately from adapter feed health;
- preserve ARMED/OPEN state through unproven gaps without inventing outcomes;
- prevent reconnect from silently restoring same-run actionability;
- keep live OpenAlgo provider details outside strategy/domain policy;
- retain the existing PAPER execution semantics while continuity is proven;
- surface reconciliation-required state for operator-facing work in SF-058.

Historical/backfill reconciliation is deferred until an explicit contract can prove enough chronology
for candle/indicator state and ARMED/OPEN price-sensitive decisions.

## Relationship to earlier ADRs

ADR-003 remains the historical persistence/recovery foundation: contradictory durable state fails
explicitly and authoritative lifecycle/economic facts are preserved.

ADR-004 remains the component-boundary foundation: market-data adapters normalize external data while
strategy/domain logic remains broker-independent.

ADR-005 remains the historical market-data/candle foundation: stale/missing data is explicit and late
data must not silently rewrite live decisions.

ADR-009 is the Git-native refinement for the specific case where live external market chronology
cannot be proven across a feed or process gap.

## ADR source-of-truth convention

Git is canonical for this decision.

GitHub #115 retains the decision discussion, SF-057 implementation contract and validation evidence.
Later issues/PRs may refine implementation mechanics, but any material change to this continuity or
reconciliation policy requires an explicit superseding or amended ADR.
