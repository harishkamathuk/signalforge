# BTC Momentum Baseline V0 Strategy Specification

## Status

**APPROVED — EXPERIMENTAL RESEARCH STRATEGY**

- Strategy ID: `btc_momentum_baseline_v0`
- Version: `0.1.0-experimental`
- Approved: 2026-11-05
- Strategy-definition authority: SF-094 / GitHub #233
- Instrument: Delta Exchange India BTCUSD perpetual
- Decision price series: traded price
- Canonical chronology: UTC
- Live-capital approval: **No**
- Delta live PAPER approval: **No — downstream readiness remains owned by SF-092**

This specification does not modify or supersede
`intraday_momentum_v1 / 1.0.0`. The accepted NSE strategy remains unchanged.

## Purpose and hypothesis

This strategy is the first controlled BTCUSD perpetual research baseline.

The hypothesis is:

> Test whether the existing long momentum/continuation hypothesis exhibits useful
> behaviour on Delta BTCUSD perpetual when its indicator, entry, stop and target
> parameters are transferred unchanged as a baseline.

The inherited parameters are deliberately **not** claimed to be validated or
appropriate for BTC. They are frozen to establish an unbiased baseline before
any BTC-specific parameter changes are considered.

No parameter tuning is permitted before the predeclared baseline evidence is
obtained.

## Instrument and market-data basis

The strategy applies only to the explicitly identified Delta Exchange India
BTCUSD perpetual contract.

Strategy decisions use the **traded-price** series. Mark price, index price,
spot BTC, another venue, or another Delta product must not be substituted
silently.

Historical research must preserve the qualified source/provenance contract
established by SF-087/SF-088 as applicable. Canonical event/candle chronology is
timezone-aware UTC.

Continuous market-data coverage does not itself define a daily strategy
session. UTC calendar boundaries are not trading boundaries.

## Direction and timeframe

- Direction: long only.
- Decision timeframe: completed 5-minute candles.
- No short-side policy exists under this version.
- Unfinished/forming candles cannot qualify.

## Indicator requirements and readiness

Reuse the existing canonical SignalForge indicator implementations and numerical
contracts without reinterpretation:

- EMA(9)
- EMA(20)
- EMA(50)
- RSI(14)
- ADX(14)
- MACD(12, 26, 9)

MACD is calculated and recorded but is not a mandatory qualification filter.

The canonical indicator engine remains authoritative for seeding, recursion,
readiness, precision and missing-data behaviour. This strategy does not define a
second BTC-specific indicator implementation.

At least **250 completed 5-minute candles** must be processed before strategy
evaluation is eligible. Warm-up candles cannot generate research trades.

For controlled research, the preferred arrangement is to provide the required
warm-up as pre-roll before the declared measured evaluation window so the
measured window is not silently shortened by bootstrap.

## Signal qualification

A completed 5-minute candle qualifies only when all of the following are true:

```text
EMA20 > EMA50
Close > EMA9
58 <= RSI14 <= 65
ADX14 > 22
```

The RSI boundaries are inclusive. The ADX and EMA comparisons are strict.

Qualification uses the unrounded canonical indicator values. Display rounding
must not affect a decision.

The strategy should retain explicit diagnostic/rejection evidence for the
individual qualification conditions.

## Entry and ARMED lifecycle

After a qualifying signal candle completes, an actionable opportunity may become
ARMED if no conflicting actionable state exists.

Raw entry trigger:

```text
raw_trigger = signal_close × 1.001
```

The raw formula is strategy-owned. Conversion to a valid tradable price is an
execution/shared-engine responsibility using the applicable effective tick-size
rule.

The opportunity is valid only during the **immediately following 5-minute
candle**.

While ARMED:

- first chronological observation at or above the tradable trigger triggers entry;
- first chronological observation at or below the signal-candle low invalidates
  and expires the setup if it occurs before entry;
- if neither occurs before the immediately following 5-minute candle completes,
  the setup expires;
- an expired setup cannot later trigger.

Existing deterministic lifecycle ordering remains authoritative. If the next
completed candle itself qualifies after the previous setup expires, it may
create a fresh independent opportunity.

## Actionable-position constraint

For the configured instrument, this baseline permits at most:

```text
one actionable ARMED setup
OR
one OPEN position
```

No pyramiding is allowed.

While a position is OPEN, later qualifying candles may be retained as
non-actionable research/audit observations, but they cannot create another
actionable trade.

## Stop, risk and target

Initial stop:

```text
stop = signal_candle_low
```

After an accepted entry fill:

```text
risk = actual_fill - stop
```

A non-positive risk value is invalid and must follow the shared explicit
position-open rejection path.

Raw target:

```text
raw_target = actual_fill + 1.5 × risk
```

The target formula is strategy-owned. Tradable-price normalization remains a
shared execution responsibility.

The first research contract expresses risk primarily as **price-distance R**.
Position quantity, contract multiplier/value, leverage, margin and monetary
capital sizing are not strategy semantics in this version.

## Continuous-market time policy

This strategy operates on a continuous 24x7 basis.

There is:

- no strategy-specific time-of-day trading window;
- no daily entry cutoff;
- no compulsory daily exit;
- no UTC-midnight reset;
- no maximum holding period.

Signals and OPEN positions may cross UTC calendar-day boundaries without any
strategy transition.

UTC midnight may be used for storage/reporting partitioning, but must not become
an implicit trading boundary.

## Exit policy

Normal position closure occurs only through:

- STOP; or
- TARGET.

This version defines no:

- compulsory session exit;
- time-based exit;
- maximum-holding exit;
- indicator-reversal exit;
- trailing stop;
- scale-out;
- discretionary exit.

If a historical dataset ends while a position is OPEN, the simulator must not
manufacture an exit. The outcome remains explicitly open/unresolved for that
experiment according to the accepted historical research contract.

## Historical execution and ambiguity

Historical execution reuses the accepted SignalForge historical execution and
ambiguity semantics in ADR-011.

In particular:

- historical OHLCV must not be converted into fabricated tick chronology;
- favourable intra-bar ordering must not be assumed;
- trigger/invalidation or stop/target ordering ambiguity remains first-class
  research evidence;
- missing or invalid evidence cannot be interpreted as "nothing happened";
- post-fill target economics use the modeled historical actual fill, not the
  theoretical trigger.

The initial historical baseline may use the existing deterministic complete-fill
execution model. Partial-fill and external asynchronous-order semantics remain
outside this strategy specification and are owned by later execution work such
as SF-092.

## Tick-size policy and historical uncertainty

Keep strategy intent and executable normalization distinct:

```text
raw strategy level -> tradable tick-normalized level
```

The strategy owns raw trigger and target formulas. The execution/research layer
owns tick normalization.

For historical periods:

- use an evidence-backed effective tick size for the relevant instrument and
  period when available;
- do not apply today's tick size retrospectively without evidence that it was
  effective for the historical period;
- do not fabricate an effective-dated tick schedule.

If an evidence-backed effective tick size is unavailable, raw-level diagnostic
analysis may be retained, but the affected results are **not eligible for
execution-valid strategy-performance conclusions**.

A normal historical execution result that depends on tradable trigger/target
levels therefore requires an accepted effective tick-size rule.

## Perpetual-specific economics and limits on claims

Fees, funding, spread/slippage, margin and liquidation mechanics are not strategy
signal rules and must remain separate research/execution assumptions.

The initial baseline may report gross price-distance R under explicitly
identified execution assumptions.

However:

- gross R must not be presented as net profitability;
- no deployment-relevance PASS may be claimed until applicable fees and funding
  are accounted for;
- reasonable adverse execution/slippage sensitivity is required before a
  deployment-relevance conclusion;
- margin/leverage/liquidation assumptions must be explicit before monetary or
  capital-exposure conclusions are made.

Funding is especially material because this strategy permits positions to remain
open indefinitely across UTC dates.

## Reuse of existing SignalForge components

Reuse existing tested components wherever compatible, including:

- canonical 5-minute candle and aggregation contracts;
- canonical EMA/RSI/ADX/MACD implementations;
- strategy registry/runtime boundary;
- ARMED/trigger/expiry lifecycle mechanics;
- actual-fill-based post-fill economics boundary;
- historical bar execution mechanics;
- ambiguity and missing-evidence handling;
- deterministic experiment/config/run provenance.

Do not import NSE-specific:

- regular-session hours;
- NSE entry cutoff;
- compulsory 15:15 exit;
- NSE tick-size schedules;
- NSE transaction-cost assumptions.

## Governance and validation boundary

This strategy is approved as an **experimental research specification**, not as a
profitable or deployable trading strategy.

Before strategy-performance backtesting, the Backtesting & Validation workstream
must freeze a predeclared validation contract covering at minimum:

- eligible dataset identity and fixed research windows;
- strategy/config/calculation/execution-assumption identities;
- sample and continuity requirements;
- ambiguity/unresolved-outcome reporting;
- cost/funding/slippage sensitivity;
- out-of-sample controls;
- PASS / FAIL / INCONCLUSIVE interpretation.

Do not change baseline parameters after observing performance and continue to
call the result this same baseline.

Any later material change to signal, entry, stop, target, validity, direction,
time policy or exit behaviour requires a separately identifiable strategy
version or strategy identity as appropriate. Parameter experiments must use
separately identifiable experimental configuration/version provenance and must
not overwrite this baseline.

## Explicit non-goals

This version does not define or authorize:

- short trading;
- parameter optimization;
- BTC-specific parameter tuning;
- portfolio/risk-based sizing;
- pyramiding;
- live-capital trading;
- Delta Demo/Testnet order placement;
- partial-fill order semantics;
- funding/fee models inside strategy logic;
- market/mark/index-price substitution;
- changes to `intraday_momentum_v1 / 1.0.0`.

## Approval record

The strategy definition and the adversarial refinements above were explicitly
approved in Conversation 01 on 2026-11-05 under SF-094.

The next decision is the predeclared validation contract. No strategy-performance
backtest is authorized by this document alone.
