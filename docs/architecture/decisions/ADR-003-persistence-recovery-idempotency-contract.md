# ADR-003 — Persistence, Recovery & Idempotency Contract

> **Historical Reference Notice**\
> This ADR records an architecture decision made during the initial SignalForge build and reconstructed from the contemporaneous 02.01 Strategy Framework & Architecture conversation. It is retained for historical reference and architectural provenance. It must not be treated as a new design decision or as overriding later accepted ADRs, current strategy specifications, implementation contracts, or tested system behaviour.

**Status:** Historical — retrospectively reconstructed

## Context

SignalForge must survive process restarts without duplicating trades, losing authoritative state, or reconstructing material trading facts incorrectly.

## Decision

Use a **hybrid persistence model** consisting of immutable lifecycle/audit facts plus explicit authoritative current state.

Do not use full event sourcing.

Treat material lifecycle transitions as atomic logical boundaries, including signal/arming, triggering, opening from a fill, and closing from an exit.

Operations that may be replayed or retried must be idempotent.

Persist sufficient authoritative state to recover run identity, indicator progress, active ARMED state and OPEN trade/position state.

Persist already-established OPEN economics rather than recomputing them after restart.

Contradictory durable state must fail explicitly rather than be guessed or silently repaired.

## Rationale

Recovery correctness and auditability are capital-safety concerns. Durable state must prevent duplicate or semantically different outcomes after retry or restart.

## Consequences

Persistence implementations must support atomicity, idempotency and consistency validation.

The physical database technology and schema are implementation concerns unless separately decided.

## Historical boundary

The later PostgreSQL schema, SQLAlchemy repositories, Alembic migrations, concrete Unit of Work implementation and recovery functions are not back-projected into ADR-003.
