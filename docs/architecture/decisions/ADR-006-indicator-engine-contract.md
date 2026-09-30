# ADR-006 — Indicator Engine Contract

> **Historical Reference Notice**\
> This ADR records an architecture decision made during the initial SignalForge build and reconstructed from the contemporaneous 02.01 Strategy Framework & Architecture conversation. It is retained for historical reference and architectural provenance. It must not be treated as a new design decision or as overriding later accepted ADRs, current strategy specifications, implementation contracts, or tested system behaviour.

**Status:** Historical — retrospectively reconstructed

## Context

Indicator results must remain deterministic across uninterrupted runtime, restart, replay and validation.

## Decision

The Indicator Engine consumes canonical completed candle sequences and maintains incremental indicator state.

It produces explicit indicator snapshots for strategy evaluation.

Indicator state carries across regular trading sessions; legitimate overnight/session gaps do not by themselves invalidate continuity.

Missing, invalid or corrupt canonical input breaks indicator continuity and suppresses strategy evaluation until the state is recovered or deterministically replayed.

Persist or checkpoint sufficient indicator state for restart consistency.

The exact numerical definitions of individual indicators are owned by the accepted numerical specification rather than redefined by this architecture contract.

## Rationale

A canonical indicator boundary prevents different runtime modes or strategy components from calculating nominally identical indicators differently.

## Consequences

Indicator implementations require independent numerical validation, including incremental/batch and uninterrupted/restart equivalence.

## Historical boundary

Later enum names, checkpoint field layouts, sample-count invariants, readiness observations and concrete methods are implementation details and are not asserted as part of the original ADR.
