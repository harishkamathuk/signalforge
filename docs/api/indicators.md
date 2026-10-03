# Indicator API

The indicator API is generated from the typed requirement catalogue, immutable completed-candle readings, and requirement-driven engine/checkpoint state.

## Requirement and snapshot contracts

::: signalforge.domain.indicators

## Indicator engine

::: signalforge.runtime.indicators


## Indicator recovery reconciliation

Restart reconciliation is strategy-neutral and consumes the persisted self-describing
indicator checkpoint plus authoritative post-checkpoint completed candles.

The recovery layer does not infer strategy identity from indicator shape and does not
perform strategy evaluation or lifecycle actions while catching indicator state up.

::: signalforge.runtime.indicator_recovery
