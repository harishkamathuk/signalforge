# SignalForge

SignalForge is a strategy-driven intraday trading research and execution framework focused initially on NSE equities.

It is designed to keep strategy semantics consistent across:

- deterministic historical replay;
- backtesting and validation;
- paper trading;
- eventual live execution.

## Current MVP

The initial MVP is deliberately narrow:

- one NSE equity;
- 5-minute completed candles;
- `intraday_momentum_v1 / 1.0.0`;
- deterministic indicator calculations;
- explicit signal and trade state machines;
- paper execution;
- persistence and restart recovery.

## Architecture

SignalForge is initially implemented as a Python modular monolith.

External market-data and broker infrastructure such as OpenAlgo remains behind adapters. SignalForge owns:

- deterministic candle construction;
- canonical indicator calculations;
- strategy evaluation;
- signal and ARMED lifecycle;
- trade and position state;
- paper execution semantics;
- persistence, recovery and auditability.

Replay, paper and future live modes should share the same authoritative domain and strategy logic wherever practical.

## Strategy V1

The current frozen MVP strategy is long-only and uses completed 5-minute candles:

- Trend: `EMA20 > EMA50`
- Momentum: `58 <= RSI14 <= 65` and `ADX14 > 22`
- Setup: `Close > EMA9`
- MACD: calculated and persisted, but not a qualification filter
- Entry trigger: signal close `× 1.001`, rounded upward to a valid exchange tick
- Stop: signal-candle low
- Risk: actual fill minus stop
- Target: actual fill plus `1.5R`

Exact strategy semantics are version-controlled and must not change silently.

## Development Model

SignalForge uses a lightweight GitFlow-style branch model:

- `main` — stable/released code
- `develop` — default integration branch
- `feature/*` — implementation work
- `release/*` — release stabilization
- `hotfix/*` — urgent fixes to released code

Normal feature work should enter `develop` through pull requests.

Python source documentation follows the repository [Python Documentation Standard](docs/python-documentation-standard.md): Google-style docstrings for public APIs and mandatory rationale comments for non-obvious ordering, invariants, safety boundaries and persistence/recovery behaviour.

Generated documentation uses MkDocs + mkdocstrings. Install `.[docs]` and run `mkdocs build --strict` to build the site locally.

## Current Status

Architecture discovery is complete for the MVP. The following ADRs are accepted:

- [ADR-001 — Single-Security MVP Runtime Architecture](docs/architecture/decisions/ADR-001-single-security-mvp-runtime-architecture.md)
- [ADR-002 — Core Domain Models & State Machines](docs/architecture/decisions/ADR-002-core-domain-models-state-machines.md)
- [ADR-003 — Persistence, Recovery & Idempotency Contract](docs/architecture/decisions/ADR-003-persistence-recovery-idempotency-contract.md)
- [ADR-004 — Runtime Interfaces & Component Contracts](docs/architecture/decisions/ADR-004-runtime-interfaces-component-contracts.md)
- [ADR-005 — Market Data & Candle Contract](docs/architecture/decisions/ADR-005-market-data-candle-contract.md)
- [ADR-006 — Indicator Engine Contract](docs/architecture/decisions/ADR-006-indicator-engine-contract.md)
- [ADR-007 — Paper Execution & Fill Model](docs/architecture/decisions/ADR-007-paper-execution-fill-model.md)
- [ADR-008 — Strategy Runtime Boundary](docs/architecture/decisions/ADR-008-strategy-runtime-boundary.md)

### ADR source of truth

Git is canonical for SignalForge architecture decision records from ADR-008 onward.

ADR-001 through ADR-007 predate the standalone ADR-file convention. Their accepted decisions have now been retrospectively reconstructed from the contemporaneous 02.01 Strategy Framework & Architecture conversation and are retained in Git as clearly marked historical-reference ADRs. They do not become part of the Git-native ADR series and must not override later accepted ADRs, current strategy specifications, implementation contracts or tested system behaviour.

ADR-008 and later remain the formal Git-native ADR series.

GitHub issues and pull requests retain discussion, implementation scope and evidence. External governance or architecture documents may summarize or point to ADRs, but should not maintain a competing copy of the canonical ADR text.

Current implementation milestone:

**M0 + M1 — deterministic foundation, domain models and state machines.**

The immediate engineering objective is to prove one deterministic in-memory Strategy V1 lifecycle from qualification through `CLOSED` before introducing live OpenAlgo connectivity.

## Project Principles

- Strategy first.
- No silent strategy changes.
- Configuration over hard-coding.
- No custom trading-rule DSL for the MVP.
- Completed candles drive indicator decisions.
- Backtest, replay, paper and live semantics should remain aligned.
- Auditability and deterministic recovery are first-class requirements.
- Build incrementally and avoid premature distributed infrastructure.

## Repository Hygiene

Do not commit:

- broker/API credentials;
- access tokens or secrets;
- `.env` files containing credentials;
- private keys;
- account-specific configuration;
- large raw market datasets.

Small deterministic fixtures and golden datasets used by automated tests should remain version-controlled under `tests/fixtures/`.
