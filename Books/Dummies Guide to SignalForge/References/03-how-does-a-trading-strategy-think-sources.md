# Chapter 3 — Source verification record

**Chapter:** [How Does a Trading Strategy Think?](../Chapters/03-how-does-a-trading-strategy-think.md)
**Editorial status:** Owner AAS approved 13 November 2026.
**Verification date:** 13 November 2026.
**Repository:** `harishkamathuk/signalforge`
**Immutable source revision:** [`27be32466b42e25d7a5a5dbe2059783939e624aa`](https://github.com/harishkamathuk/signalforge/commit/27be32466b42e25d7a5a5dbe2059783939e624aa)

## Source-to-claim register

| Chapter assertion | Evidence classification | Immutable source |
|---|---|---|
| NSE long-only Strategy V1 and completed five-minute decisions | Accepted strategy description | [Repository README](https://github.com/harishkamathuk/signalforge/blob/27be32466b42e25d7a5a5dbe2059783939e624aa/README.md) |
| EMA20 > EMA50; inclusive RSI14 58–65; strict ADX14 > 22; close > EMA9 | Typed versioned configuration and accepted rule summary | [Strategy V1 configuration](https://github.com/harishkamathuk/signalforge/blob/27be32466b42e25d7a5a5dbe2059783939e624aa/signalforge/config/strategy_v1.py), [README](https://github.com/harishkamathuk/signalforge/blob/27be32466b42e25d7a5a5dbe2059783939e624aa/README.md) |
| Qualification combines trend, momentum and setup, while actionability additionally depends on guards | Implemented evaluator contract | [Strategy evaluator](https://github.com/harishkamathuk/signalforge/blob/27be32466b42e25d7a5a5dbe2059783939e624aa/signalforge/runtime/strategy_evaluator.py) |
| Stale feeds, missing readiness/warmup, invalid candle, broken continuity and outside signal window can prevent action | Implemented guard contract | [Eligibility guards](https://github.com/harishkamathuk/signalforge/blob/27be32466b42e25d7a5a5dbe2059783939e624aa/signalforge/runtime/eligibility.py) |
| ARMED lifecycle, strategy/engine boundaries, tick normalization and actual-fill authority | Accepted normative architecture | [ADR-008](https://github.com/harishkamathuk/signalforge/blob/27be32466b42e25d7a5a5dbe2059783939e624aa/docs/architecture/decisions/ADR-008-strategy-runtime-boundary.md) |
| Trigger uses raw signal close × 1.001, one-following-candle opportunity, signal-low stop, positive risk and 1.5R raw target | Strategy implementation | [Strategy V1 policy](https://github.com/harishkamathuk/signalforge/blob/27be32466b42e25d7a5a5dbe2059783939e624aa/signalforge/runtime/strategy_v1.py) |
| MACD is diagnostic and not a qualifying vote; numerical pass/fail, stale-feed block and deterministic evaluator results | Repository unit-test evidence (not independently run for this chapter) | [Strategy evaluator tests](https://github.com/harishkamathuk/signalforge/blob/27be32466b42e25d7a5a5dbe2059783939e624aa/tests/unit/runtime/test_strategy_evaluator.py) |
| Everyday explanations of EMA, RSI and ADX | Pedagogical analogy, not numerical definition | Canonical indicator calculations are controlled by implementation and numerical contracts; the prose is deliberately qualitative |
| Robo detective, recipe, schoolteacher, cyclist and values in the example case files | Explicitly fictional educational examples | Not actual candles, computed indicator snapshots, trading fills, P&L or market validation |
| Profitable or real-money-ready strategy | **Not claimed** | Documentary/code verification is not profitability evidence or live capital authorisation |

## Source integrity and interpretation

The seven named Git files were retrieved at the full immutable revision above during editorial verification. Its referenced content was inspected against the current `develop` version when preparing and reviewing the chapter. The reference is intentionally immutable: consult current `develop` separately for later changes.

The manuscript uses the accepted `intraday_momentum_v1 / 1.0.0` rules without amending their signal, trigger, stop, target, sizing, validity, execution or trade-state semantics. EMA20 and EMA50 denote periods, not a strict last-20/50-candle window; EMA retains recursively decaying older influence. RSI and ADX are different price-behaviour measures. MACD is recorded, not a qualification filter. A qualified numerical result can remain non-actionable because of an independent operational guard.

This is **source-document and implementation-text verification only**. No test suite was executed as part of editorial review. It is not evidence of complete operational validation, observed broker executions, paper-profit quality, or live-capital readiness.

## RIA → CURATE findings disposition

| Finding | Severity in RIA | Disposition in approved CURATE text |
|---|---|---|
| F01 — EMA may imply fixed-length average | Moderate | Clarified weighted recursive history, EMA20 versus EMA50 responsiveness, and period-versus-minute distinction |
| F02 — Eligibility distinction needs concrete example | Moderate | Demonstrated numerically qualified candle with stale market feed that cannot become actionable; separated other guard classes |
| F03 — Source record lacks direct config and guard contracts | Moderate | Added immutable links to typed configuration, eligibility, evaluator, policy, tests and accepted ADR-008 |
| F04 — RSI and ADX metaphors conflated | Minor | Explained RSI's recent price-movement balance versus ADX's direction-neutral trend strength |
| F05 — Entry/stop/target section too dense | Minor | Streamlined explanation while retaining exact 1.001 trigger, immediately following candle, positive-risk check and actual-fill-based 1.5R target |
| F06 — Detective narrative fades in conclusion | Minor | Restored Robo's case-file metaphor in the final summary |

**Governance boundary:** Editorial AAS approves manuscript content and its source record only. It does not approve changes to strategy semantics, market-data qualification, engineering readiness, paper/live operations or trading performance.
