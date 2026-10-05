# Live Runtime

SF-057 assembles SignalForge's single-security PAPER runtime over normalized live market data.

The runtime implements ADR-009. It deliberately separates:

- transport/feed health;
- provable market-history continuity;
- durable lifecycle state.

::: signalforge.runtime.live_runtime

## Persistence boundary

Live OpenAlgo events do not carry replayable provider sequence/event identity. Their synchronous
durable consequences therefore use a live-specific transaction without creating a synthetic
`MarketInputCheckpoint`.

::: signalforge.persistence.coordinator.LiveMarketInputCommit
