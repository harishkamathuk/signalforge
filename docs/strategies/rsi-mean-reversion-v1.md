# RSI Mean-Reversion V1 Reference Strategy

## Status

**EXPERIMENTAL / REFERENCE**

`rsi_mean_reversion_v1 / 1.0.0` exists to exercise SignalForge's multi-strategy
runtime boundary. It is not an accepted production strategy, has no profitability
claim, and is not approved for live capital.

## Exact fixture semantics

The strategy is long-only, single-security, completed-5-minute-candle, paper
execution. It declares only canonical RSI(14).

A completed candle qualifies when RSI(14) is ready and **strictly below 30**.
RSI equal to 30 does not qualify.

For an actionable signal:

- raw entry trigger = signal-candle close;
- shared core normalizes the trigger to the active NSE tick;
- initial stop = signal-candle low;
- the opportunity is valid only during the immediately following 5-minute candle;
- a pre-entry move at or below the signal low does **not** invalidate the setup;
- shared compulsory intraday/session safety remains authoritative.

After an authoritative Fill:

```text
risk/share = actual fill - stop
raw target = actual fill + 1.0 × risk
```

Non-positive risk uses the shared explicit position-open rejection path. Shared
core normalizes a positive raw target to a valid tradable NSE price.

Open positions use only the shared stop, target, and compulsory intraday-exit
mechanisms. There is no trailing stop, scale-out, pyramiding, or discretionary
strategy exit.

## Configuration governance

Version `1.0.0` intentionally freezes the architecture fixture:

- timeframe: 5 minutes;
- RSI period: 14;
- threshold: 30;
- comparison: strictly below;
- target: 1.0R;
- validity: one following candle.

These values are not exposed as an optimisation surface under the same strategy
version. The configuration identity is deterministic and carries
`EXPERIMENTAL` governance status.

## Architecture role

The strategy is implemented as ordinary typed Python strategy code and is
registered through the same explicit registry used by Strategy V1. Shared
ReplayRuntime, lifecycle, execution, tick normalization, Trade/Position models,
and broker/data boundaries do not branch on this strategy identity.

SF-066 owns the final cross-strategy replay, persistence, recovery-readiness,
and Strategy V1 non-regression proof.
