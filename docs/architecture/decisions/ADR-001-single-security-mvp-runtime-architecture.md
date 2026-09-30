# ADR-001 — Single-Security MVP Runtime Architecture

> **Historical Reference Notice**\
> This ADR records an architecture decision made during the initial SignalForge build and reconstructed from the contemporaneous 02.01 Strategy Framework & Architecture conversation. It is retained for historical reference and architectural provenance. It must not be treated as a new design decision or as overriding later accepted ADRs, current strategy specifications, implementation contracts, or tested system behaviour.

**Status:** Historical — retrospectively reconstructed

## Context

SignalForge required an executable architecture for the initial Strategy V1 without prematurely designing the eventual multi-security platform.

## Decision

Use a deliberately narrow **single-security modular runtime**.

Compose distinct responsibilities for market data, canonical candles, indicators, strategy evaluation, signal lifecycle, execution and trade/position management.

Keep orchestration lightweight and keep broker/data integration outside strategy logic.

Prefer one maintainable Python runtime over distributed infrastructure for the MVP.

## Rationale

A one-security vertical permits deterministic implementation and testing of the complete trading lifecycle while retaining modular boundaries that can later support replay, paper and live operation.

## Consequences

The MVP does not require multi-security ranking, portfolio orchestration, microservices, Kafka, Redis, Kubernetes, ML or a strategy DSL.

Future expansion should extend tested component boundaries rather than require a rewrite of strategy semantics.

## Historical boundary

This reconstruction records the accepted architectural direction only. Exact later class names, package structure, replay APIs, persistence technology and implementation-specific state objects are not back-projected into ADR-001.
