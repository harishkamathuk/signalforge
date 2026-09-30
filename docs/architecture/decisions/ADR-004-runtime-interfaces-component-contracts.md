# ADR-004 — Runtime Interfaces & Component Contracts

> **Historical Reference Notice**\
> This ADR records an architecture decision made during the initial SignalForge build and reconstructed from the contemporaneous 02.01 Strategy Framework & Architecture conversation. It is retained for historical reference and architectural provenance. It must not be treated as a new design decision or as overriding later accepted ADRs, current strategy specifications, implementation contracts, or tested system behaviour.

**Status:** Historical — retrospectively reconstructed

## Context

Replay, paper and eventual live operation should share domain semantics while permitting different external data and execution adapters.

## Decision

Use explicit component contracts approximately along these responsibilities:

- market-data adapter → normalized market events;
- candle engine → completed canonical candles;
- indicator engine → indicator snapshots;
- strategy evaluator → strategy evaluations;
- signal lifecycle → signals, armed setups and trigger events;
- execution port → execution/fill facts;
- position management → trades, positions and exits.

Use a thin coordinator for sequencing rather than placing business rules in orchestration.

Keep domain-facing execution and data contracts broker-independent.

## Rationale

Clear contracts isolate external systems from strategy semantics and make components independently testable and reusable across replay, paper and live modes.

## Consequences

Broker SDK types do not belong in strategy/domain logic.

Multi-security orchestration and distributed messaging remain deferred.

## Historical boundary

Exact Python Protocols, constructor signatures, result dataclasses, replay APIs and later persistence interfaces are implementation details and are not asserted as original ADR text.
