# ADR-002 — Core Domain Models & State Machines

> **Historical Reference Notice**\
> This ADR records an architecture decision made during the initial SignalForge build and reconstructed from the contemporaneous 02.01 Strategy Framework & Architecture conversation. It is retained for historical reference and architectural provenance. It must not be treated as a new design decision or as overriding later accepted ADRs, current strategy specifications, implementation contracts, or tested system behaviour.

**Status:** Historical — retrospectively reconstructed

## Context

The trading lifecycle needed to be deterministic, auditable and capable of later persistence and recovery.

## Decision

Represent material trading concepts as explicit typed domain facts and state machines rather than implicit procedural state.

The logical lifecycle distinguishes:

`Candle → IndicatorSnapshot → StrategyEvaluation → Signal → ArmedSetup → TriggerEvent → Fill → Trade → Position → Exit`

`ArmedSetup` transitions from `ARMED` to either `TRIGGERED` or `EXPIRED`.

Trade and Position are distinct concepts and transition from `OPEN` to `CLOSED`; they are 1:1 for the MVP.

A trade originates from accepted execution/fill evidence rather than directly from a signal or trigger.

## Rationale

Explicit domain concepts prevent trigger, execution and position semantics from being conflated and provide deterministic audit and recovery boundaries.

## Consequences

Lifecycle transitions must be explicit and terminal states must remain terminal.

Portfolio aggregation, multi-security allocation and short-side domain behaviour remain outside the MVP.

## Historical boundary

Exact dataclass/Pydantic choices, deterministic-ID implementation, field names, persistence schema and concrete transition methods were later implementation details and are not asserted as part of the original decision.
