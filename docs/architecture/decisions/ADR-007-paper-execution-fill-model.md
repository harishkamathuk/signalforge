# ADR-007 — Paper Execution & Fill Model

> **Historical Reference Notice**\
> This ADR records an architecture decision made during the initial SignalForge build and reconstructed from the contemporaneous 02.01 Strategy Framework & Architecture conversation. It is retained for historical reference and architectural provenance. It must not be treated as a new design decision or as overriding later accepted ADRs, current strategy specifications, implementation contracts, or tested system behaviour.

**Status:** Historical — retrospectively reconstructed

## Context

Paper trading must provide useful execution evidence without producing unrealistically favourable fills or defining semantics that would later diverge from live execution.

## Decision

Paper and eventual live execution share a broker-independent domain-facing execution boundary.

Paper execution uses actual observed eligible trade/LTP evidence.

A trigger/reference price does not imply a fill at that price. If the first eligible observed market price is beyond the trigger, paper execution fills at that observed price.

Do not introduce an artificial slippage model in the initial implementation.

Where available data cannot determine intra-period event ordering, do not invent favourable ordering.

Fill evidence remains distinct from trigger/reference evidence, and downstream trade economics use the actual fill according to the normative strategy contract.

## Rationale

Observed-price fills produce more realistic and reproducible execution behaviour and prevent paper results from benefiting from fabricated trigger-price execution.

## Consequences

Gap-through executions are represented at the actual observed price.

Broker order APIs, sophisticated execution simulation and position-sizing policy remain outside this ADR.

## Historical boundary

Later `PaperExecutionPort` / `PaperExecutionResult` names, exact idempotency implementation and lifecycle-coordinator APIs are not back-projected into ADR-007.
