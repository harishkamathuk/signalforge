# ADR-005 — Market Data & Candle Contract

> **Historical Reference Notice**\
> This ADR records an architecture decision made during the initial SignalForge build and reconstructed from the contemporaneous 02.01 Strategy Framework & Architecture conversation. It is retained for historical reference and architectural provenance. It must not be treated as a new design decision or as overriding later accepted ADRs, current strategy specifications, implementation contracts, or tested system behaviour.

**Status:** Historical — retrospectively reconstructed

## Context

Trading decisions require a single deterministic interpretation of market chronology and completed candles.

## Decision

Use authoritative exchange/event timestamps where available.

Represent candle intervals as half-open intervals `[start, end)` and use a single canonical Candle Engine to construct completed candles.

Do not create synthetic flat candles merely to fill periods without accepted market events.

Represent missing, stale or otherwise invalid market-data conditions explicitly.

Only healthy market-data state permits new actionable signals.

Once a completed candle has been consumed for a live trading decision, a late event must not silently mutate that historical live decision. Late data may instead be audited, reconciled or incorporated through controlled replay.

## Rationale

The contract prevents look-ahead, mode-specific candle construction, hidden gap repair and retroactive alteration of trading decisions.

## Consequences

Indicators and strategy evaluation consume canonical completed candles rather than constructing independent OHLC state.

## Historical boundary

Later exception classes, method signatures, source-validation details and other Candle Engine implementation mechanics are not back-projected into ADR-005.
