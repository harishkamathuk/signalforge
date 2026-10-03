# Cross-Strategy Proof

SF-066 is the exit evidence for the multi-strategy runtime-boundary correction defined by
[ADR-008](../architecture/decisions/ADR-008-strategy-runtime-boundary.md).

The proof covers both production registrations:

- `intraday_momentum_v1 / 1.0.0` — accepted Strategy V1;
- `rsi_mean_reversion_v1 / 1.0.0` — experimental/reference strategy.

Both resolve through the same strategy registry and execute through the same ReplayRuntime,
lifecycle, indicator, persistence and recovery-readiness mechanisms. Shared orchestration does
not dispatch on strategy identity.

## Strategy-decision persistence

SF-066 replaces the remaining V1-shaped persistence contract with immutable
`StrategyDecisionFact` audit facts. The common record stores:

- instrument and completed-candle interval;
- a deterministic decision schema/kind;
- qualified/actionable state;
- stable reason codes;
- deterministic structured diagnostics.

Diagnostics are audit data only. They contain no formulas or executable expressions. Decimal
diagnostics are persisted using SignalForge's canonical Decimal text representation.

Legacy V1 evaluation rows are migrated into the generic representation without discarding the
historical trend, momentum, RSI, ADX, MACD and setup evidence. Downgrade is permitted only when
all decision facts can be represented losslessly by the historical V1 schema; reference-strategy
facts block downgrade explicitly.

## Recovery readiness

Recovery continues to use persisted RunIdentity/ConfigIdentity as the authority for strategy
identity. Indicator requirement shape is validated only after identity is known. Recovery does
not infer Strategy V1 from EMA/MACD state or the reference strategy from RSI-only state, and it
does not infer strategy identity from decision diagnostics.

SF-066 proves the persisted state is sufficient and self-describing for the later SF-050 recovery
work. It does not implement SF-050 reconciliation or live restart orchestration.

## Extensibility result

A test-only third no-op strategy uses already-supported engine capabilities, registers through a
test-local StrategyRegistry, and runs through ReplayRuntime without production changes to
ReplayRuntime, CandleEngine, LifecycleCoordinator, PositionManager, Trade/Position models,
RecoveryBootstrap, broker/data adapters or persistence repository interfaces.

This demonstrates the epic exit criterion: a new strategy using already-supported capabilities
can normally be added through strategy code, typed configuration, registration and tests rather
than by modifying the SignalForge engine.

The RSI mean-reversion strategy remains **experimental/reference**. This document makes no
profitability or production-readiness claim.
