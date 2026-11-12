# Chapter 1 — Source verification record

**Editorial status:** AAS approved by the book owner on 12 November 2026.
**Repository:** `harishkamathuk/signalforge`
**Verification date:** 12 November 2026
**Verification basis:** GitHub `develop` documentation fetched during CURATE, now pinned to immutable repository commit [`3c1b014fb85498dc836cbfdf8ccbc02649cad6a7`](https://github.com/harishkamathuk/signalforge/commit/3c1b014fb85498dc836cbfdf8ccbc02649cad6a7). Editorial source checking is not independent runtime, CI, operational or trading-performance validation.
**Citation policy:** Links in the table below identify the exact historical repository revision used for the approval. For newer status, inspect current `develop` separately; do not treat the pinned revision as current.

| Chapter claim | Classification | Source |
|---|---|---|
| SignalForge is a strategy-driven intraday research and execution framework, initially focused on NSE equities | Verified project description | [README](https://github.com/harishkamathuk/signalforge/blob/3c1b014fb85498dc836cbfdf8ccbc02649cad6a7/README.md) |
| Accepted NSE Strategy V1 is long-only and uses completed five-minute candles | Verified strategy description | [README — Strategy V1](https://github.com/harishkamathuk/signalforge/blob/3c1b014fb85498dc836cbfdf8ccbc02649cad6a7/README.md) |
| Deterministic single-security replay is documented with an explicit registered strategy | Verified documented software capability | [Replay CLI](https://github.com/harishkamathuk/signalforge/blob/3c1b014fb85498dc836cbfdf8ccbc02649cad6a7/docs/replay-cli.md) |
| Accepted NSE strategy and experimental reference strategy share the replay runtime | Verified engineering proof document, not profitability proof | [Cross-strategy proof](https://github.com/harishkamathuk/signalforge/blob/3c1b014fb85498dc836cbfdf8ccbc02649cad6a7/docs/validation/cross-strategy-proof.md) |
| An NSE live PAPER operator is documented; the command has no broker-order placement option | Verified documented software capability; not proof of operational gate completion | [Live PAPER operations](https://github.com/harishkamathuk/signalforge/blob/3c1b014fb85498dc836cbfdf8ccbc02649cad6a7/docs/live-paper-operations.md) |
| Paper-before-controlled-live and evidence-led research are project principles | Project intent, not readiness claim | Project charter `01-signalforge-project-charter.md` (supplied project source; contextual rather than Git authority) |
| Real-money execution is a potential future stage | Planned capability only | Project charter and repository README; no live-money permission asserted |

## Editorial distinctions

- **Evergreen explanations:** mangoes, cake recipe, driving simulator, exam analogy and the five-minute illustrative sequence are conceptual teaching devices.
- **Hypothetical outcomes:** the £1,000 → £10,000 example is explicitly hypothetical; it is not a SignalForge backtest, fill or realised return.
- **Historical snapshots:** milestone text in the repository README may lag later operator documentation. Do not reuse the README's immediate-engineering-objective passage as today's status.
- **Planned capabilities:** real-money trading is not represented as ready, authorised or profitable.
- **Personal motivation:** owner explicitly accepted a documented project-purpose explanation without autobiographical claims at AAS.
- **Status-sensitive reuse:** re-verify operational and implementation claims against then-current GitHub sources before subsequent publication editions. A reference date is not a perpetual freshness guarantee.

## RIA / CURATE disposition

- F01 personal motivation — accepted without invented autobiography, by owner AAS.
- F02 capability/readiness boundaries — revised.
- F03 source provenance — dated references recorded here.
- F04 unnecessary repetition — revised.
- F05 concrete five-minute-candle example — added, expressly hypothetical.
- F06 initial NSE market context — clarified.
- F07 AI-assistant analogy — qualified.

**Approval scope:** editorial content only; no engineering, strategy, research-gate or paper/live authorisation.
