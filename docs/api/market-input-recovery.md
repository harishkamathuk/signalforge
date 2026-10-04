# Market-Input Recovery API

SF-067 introduces the strategy-neutral restart boundary for canonical market input and
forming-candle state. These APIs belong to the shared runtime/recovery mechanism; they do not
encode strategy signal, entry, stop, target or exit policy.

## Candle engine state

::: signalforge.runtime.candles.CandleEngineState

## Canonical input and checkpoint

::: signalforge.runtime.market_input.CanonicalMarketInput

::: signalforge.runtime.market_input.MarketInputCheckpoint

::: signalforge.runtime.market_input.MarketInputGuard

## Restart-safe replay runtime

::: signalforge.runtime.restart_safe_replay.RestartSafeReplayRuntime
