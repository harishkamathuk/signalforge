# Chapter 5 — Source Verification Record

**Chapter:** The Trading Time Machine
**Editorial stage:** Owner AAS approved — 13 November 2026
**Verification date:** 13 November 2026
**Repository:** `harishkamathuk/signalforge`
**Immutable source revision:** `558d1969baf51c98f5db180552593b4ba23b7828`

## 1. Verification basis

The chapter's supporting material was verified against GitHub `develop` and the immutable source revision identified above. The relevant normative, implementation and documentation sources matched at that revision during the Chapter 5 review.

This source record distinguishes:

- Accepted normative architecture;
- Implemented research behaviour;
- Educational illustrations;
- Historical facts versus modeled execution assumptions;
- Reproducibility evidence versus strategy validation.

The record does not independently establish data qualification, real-world profitability or permission to trade live capital.

## 2. Source-to-claim register

| Chapter assertion | Evidence classification | Immutable source |
|---|---|---|
| Historical experiments must preserve completed-candle chronology and avoid future information entering earlier decisions | Implemented research and execution contract | [Historical-bar research](https://github.com/harishkamathuk/signalforge/blob/558d1969baf51c98f5db180552593b4ba23b7828/docs/api/historical-bar-research.md), [Backtest runner](https://github.com/harishkamathuk/signalforge/blob/558d1969baf51c98f5db180552593b4ba23b7828/docs/api/backtest-runner.md) |
| A completed signal candle's constituent one-minute bars cannot become later execution evidence for the opportunity created by that signal | Accepted historical-execution chronology boundary | [Historical execution](https://github.com/harishkamathuk/signalforge/blob/558d1969baf51c98f5db180552593b4ba23b7828/docs/api/historical-execution.md), [ADR-011](https://github.com/harishkamathuk/signalforge/blob/558d1969baf51c98f5db180552593b4ba23b7828/docs/architecture/decisions/ADR-011-historical-execution-and-ambiguity-semantics.md) |
| Event-based backtesting uses canonical ReplaySource and ReplayRuntime instead of defining a new historical strategy | Implemented research boundary | [Backtest runner](https://github.com/harishkamathuk/signalforge/blob/558d1969baf51c98f5db180552593b4ba23b7828/docs/api/backtest-runner.md), [Backtest implementation](https://github.com/harishkamathuk/signalforge/blob/558d1969baf51c98f5db180552593b4ba23b7828/signalforge/research/backtest.py) |
| Replay input identity must describe the exact bounded canonical event stream, not merely a mutable filename | Implemented provenance requirement | [Backtest runner](https://github.com/harishkamathuk/signalforge/blob/558d1969baf51c98f5db180552593b4ba23b7828/docs/api/backtest-runner.md), [Backtest implementation](https://github.com/harishkamathuk/signalforge/blob/558d1969baf51c98f5db180552593b4ba23b7828/signalforge/research/backtest.py) |
| Canonical event inputs and repeatable source identities do not independently establish complete, authenticated exchange history | Evidence limitation arising from canonical replay provenance requirements and historical source qualification boundaries | [Backtest runner](https://github.com/harishkamathuk/signalforge/blob/558d1969baf51c98f5db180552593b4ba23b7828/docs/api/backtest-runner.md), [ADR-010](https://github.com/harishkamathuk/signalforge/blob/558d1969baf51c98f5db180552593b4ba23b7828/docs/architecture/decisions/ADR-010-canonical-historical-ohlcv-dataset-boundary.md) |
| Historical-bar signal research uses canonical one-minute bars, deterministic aggregation, completed candles, indicators and registered strategy evaluation | Implemented research boundary | [Historical-bar research](https://github.com/harishkamathuk/signalforge/blob/558d1969baf51c98f5db180552593b4ba23b7828/docs/api/historical-bar-research.md), [Historical-bar implementation](https://github.com/harishkamathuk/signalforge/blob/558d1969baf51c98f5db180552593b4ba23b7828/signalforge/research/historical_bars.py) |
| Historical-bar signal research alone does not simulate entry, stop, target, fill or exit chronology | Implemented scope restriction | [Historical-bar research](https://github.com/harishkamathuk/signalforge/blob/558d1969baf51c98f5db180552593b4ba23b7828/docs/api/historical-bar-research.md) |
| Historical OHLCV must not be converted into fabricated event chronology | Accepted normative architecture | [ADR-010](https://github.com/harishkamathuk/signalforge/blob/558d1969baf51c98f5db180552593b4ba23b7828/docs/architecture/decisions/ADR-010-canonical-historical-ohlcv-dataset-boundary.md) |
| Non-VALID derived candles fail the historical-bar signal research run rather than silently advancing indicators | Implemented research continuity restriction | [Historical-bar research](https://github.com/harishkamathuk/signalforge/blob/558d1969baf51c98f5db180552593b4ba23b7828/docs/api/historical-bar-research.md), [Historical-bar implementation](https://github.com/harishkamathuk/signalforge/blob/558d1969baf51c98f5db180552593b4ba23b7828/signalforge/research/historical_bars.py) |
| One-minute OHLCV can establish price-level reachability but not arbitrary intrabar ordering | Accepted normative execution semantics | [ADR-011](https://github.com/harishkamathuk/signalforge/blob/558d1969baf51c98f5db180552593b4ba23b7828/docs/architecture/decisions/ADR-011-historical-execution-and-ambiguity-semantics.md) |
| Historical bar-evidence execution is distinct from event replay and does not create authoritative PAPER/LIVE fills or lifecycle facts | Implemented historical execution boundary | [Historical execution](https://github.com/harishkamathuk/signalforge/blob/558d1969baf51c98f5db180552593b4ba23b7828/docs/api/historical-execution.md), [Historical execution implementation](https://github.com/harishkamathuk/signalforge/blob/558d1969baf51c98f5db180552593b4ba23b7828/signalforge/research/historical_execution.py) |
| Historical execution uses strategy-owned policy, modeled assumptions and effective-dated tick rules | Accepted normative architecture and implementation | [ADR-011](https://github.com/harishkamathuk/signalforge/blob/558d1969baf51c98f5db180552593b4ba23b7828/docs/architecture/decisions/ADR-011-historical-execution-and-ambiguity-semantics.md), [Historical execution](https://github.com/harishkamathuk/signalforge/blob/558d1969baf51c98f5db180552593b4ba23b7828/docs/api/historical-execution.md) |
| DETERMINATE, BOUNDED_AMBIGUOUS and UNRESOLVED are distinct historical outcome classes | Accepted normative architecture and implemented domain vocabulary | [ADR-011](https://github.com/harishkamathuk/signalforge/blob/558d1969baf51c98f5db180552593b4ba23b7828/docs/architecture/decisions/ADR-011-historical-execution-and-ambiguity-semantics.md), [Historical execution implementation](https://github.com/harishkamathuk/signalforge/blob/558d1969baf51c98f5db180552593b4ba23b7828/signalforge/research/historical_execution.py) |
| Bounded stop-versus-target ambiguity may permit continuation because all supported branches are CLOSED | Implemented conditional continuation semantics | [Historical execution](https://github.com/harishkamathuk/signalforge/blob/558d1969baf51c98f5db180552593b4ba23b7828/docs/api/historical-execution.md) |
| Ambiguity leaving different possible future lifecycle states prevents continuation along one invented branch | Implemented termination boundary | [Historical execution](https://github.com/harishkamathuk/signalforge/blob/558d1969baf51c98f5db180552593b4ba23b7828/docs/api/historical-execution.md), [Historical execution implementation](https://github.com/harishkamathuk/signalforge/blob/558d1969baf51c98f5db180552593b4ba23b7828/signalforge/research/historical_execution.py) |
| Required missing historical execution evidence during ARMED or OPEN produces UNRESOLVED / MISSING_EXECUTION_EVIDENCE and terminates the initial runner | Implemented fail-closed lifecycle boundary | [Historical execution](https://github.com/harishkamathuk/signalforge/blob/558d1969baf51c98f5db180552593b4ba23b7828/docs/api/historical-execution.md) |
| Modeled fills, slippage and tick-size calculations are research constructs, not observed broker executions | Accepted normative architecture | [ADR-011](https://github.com/harishkamathuk/signalforge/blob/558d1969baf51c98f5db180552593b4ba23b7828/docs/architecture/decisions/ADR-011-historical-execution-and-ambiguity-semantics.md), [Historical execution](https://github.com/harishkamathuk/signalforge/blob/558d1969baf51c98f5db180552593b4ba23b7828/docs/api/historical-execution.md) |
| Research experiment identity covers strategy/configuration, dataset, universe, engine and material execution inputs | Implemented provenance contract | [Research identity contracts](https://github.com/harishkamathuk/signalforge/blob/558d1969baf51c98f5db180552593b4ba23b7828/docs/api/research-contracts.md) |
| Historical execution result provenance includes the assumption profile, effective-dated tick schedule and calculation version | Implemented research provenance | [Historical execution](https://github.com/harishkamathuk/signalforge/blob/558d1969baf51c98f5db180552593b4ba23b7828/docs/api/historical-execution.md) |
| Golden research experiments demonstrate deterministic infrastructure, not real-world profitability | Implemented validation and evidence boundary | [Research CLI](https://github.com/harishkamathuk/signalforge/blob/558d1969baf51c98f5db180552593b4ba23b7828/docs/research-cli.md) |
| Event-replay research CLI economics are gross, excluding brokerage, taxes and other costs | Documented limitation | [Research CLI](https://github.com/harishkamathuk/signalforge/blob/558d1969baf51c98f5db180552593b4ba23b7828/docs/research-cli.md) |
| Historical-execution statistics require determinate coverage qualifications where not every outcome is known | Implemented research reporting contract | [Historical execution](https://github.com/harishkamathuk/signalforge/blob/558d1969baf51c98f5db180552593b4ba23b7828/docs/api/historical-execution.md) |
| Chapter 4 introduces historical information quality, missing evidence and OHLCV limitations | Approved book continuity | [Chapter 4](https://github.com/harishkamathuk/signalforge/blob/558d1969baf51c98f5db180552593b4ba23b7828/Books/Dummies%20Guide%20to%20SignalForge/Chapters/04-teaching-the-robot-about-markets.md) |

## 3. Authority and source precedence

### Accepted architecture

ADR-010 governs canonical historical OHLCV observations, source completeness, provenance and prohibition of fabricated MarketEvent chronology.

ADR-011 governs the accepted strict historical bar-evidence execution model, including observed facts, strategy intent, modeled execution assumptions, determinate conclusions and uncertainty.

These accepted ADRs are normative within their defined scopes.

### Implementation corroboration

The following source files are included to corroborate documented current behaviour:

- `signalforge/research/backtest.py` — event-based historical backtesting;
- `signalforge/research/historical_bars.py` — canonical historical-bar research and continuity processing;
- `signalforge/research/historical_execution.py` — historical execution and outcome classifications.

These source files demonstrate implementation context. Their inclusion does not give them authority to silently modify accepted architecture or strategy semantics.

### Non-normative proposals

The repository also contains the ADR-011 scenario-execution proposed amendment.

It explicitly remains a proposal, not accepted normative or operative historical-execution behaviour.

[ADR-011 proposed scenario-execution amendment](https://github.com/harishkamathuk/signalforge/blob/558d1969baf51c98f5db180552593b4ba23b7828/docs/architecture/decisions/ADR-011-scenario-execution-proposed-amendment.md)

The Chapter 5 manuscript does not present scenario-conditioned historical price paths as observed events or incorporate the proposed amendment into strict execution semantics.

## 4. No-look-ahead and completed-signal boundary

The chapter's 10:00–10:05 classroom example illustrates two distinct restrictions.

First, a strategy cannot use a candle's final values before that candle has completed.

Second, after that completed candle creates an opportunity, the historical executor cannot retrospectively use constituent one-minute bars from the signal candle as later entry, stop, target or exit evidence.

A signal derived from the completed 10:00–10:05 candle cannot claim subsequent execution because a trigger was touched at 10:03.

This is an existing accepted historical-execution boundary, not a new trading or lifecycle rule introduced by the book.

The actual execution evidence and outcome remain subject to the accepted strategy validity, lifecycle timing, instrument tick and simulation contracts.

## 5. Event replay and historical-bar research

### Canonical event replay

Event-based backtesting consumes appropriately structured and ordered canonical replay inputs through the existing replay runtime.

The canonical source identity describes the exact bounded replay stream used in the experiment.

It does not independently establish that every real exchange trade was captured or that an external market-data provider's records have been authenticated.

Synthetic event files can be legitimate software fixtures, but they must not be represented as observed qualified market data.

### Historical-bar signal research

The historical-bar research path uses canonical historical one-minute OHLCV data, expected coverage and deterministic five-minute aggregation.

Its completed-candle evaluations can establish historical indicator and signal outcomes under the applicable research contract.

That signal-only path does not itself create historical entry or exit execution evidence.

The separate bar-evidence execution path does not convert OHLCV bars into invented replay events.

## 6. Ambiguity and continuation

ADR-011 distinguishes:

- `DETERMINATE` — one supported lifecycle and economic outcome;
- `BOUNDED_AMBIGUOUS` — a defined set or range of materially different possible outcomes;
- `UNRESOLVED` — no safely supportable complete outcome set under the current contract.

A bounded stop-versus-target case can permit later simulation to continue because every supported branch may leave the position CLOSED. The possible economic outcomes remain distinct and are not converted into one result.

If the supported branches leave materially different future lifecycle states, continuing along one state would amount to inventing history. The current historical runner terminates instead.

When required historical execution evidence is absent during an active ARMED or OPEN lifecycle, the runner records the applicable unresolved missing-evidence result and terminates.

None of these behaviours authorises synthetic OHLC traversal, fake timestamps or authoritative PAPER/LIVE trade facts.

## 7. Fictional OHLC example

The classroom example contains the following hypothetical prices:

| Field | Price |
|---|---:|
| Open | ₹100 |
| High | ₹104 |
| Low | ₹96 |
| Close | ₹100 |
| Hypothetical stop | ₹97 |
| Hypothetical target | ₹103 |

The example assumes a hypothetical position was already OPEN before the one-minute interval.

The observed OHLC range, if genuine and qualified, would establish reachability of both the stop and target levels.

It would not establish whether the stop or target was reached first.

The exact historical-execution outcome classification additionally depends on the accepted lifecycle policy, effective-dated tick rules, execution assumptions and qualifying evidence.

These numbers are fictional. They are not observed NSE market data, broker fills, an actual SignalForge historical result or profitability evidence.

## 8. Reproducibility and research limitations

SignalForge's research identity contracts track material inputs such as registered strategy identity, typed configuration, dataset/source content, universe, engine version and relevant execution settings.

Historical execution additionally preserves identified execution assumptions, effective-dated tick schedule identity and simulator calculation version.

A reproducible calculation establishes consistency for those specific inputs and rules, not the quality of the underlying market evidence or future profitability.

The golden research experiment is an infrastructure fixture. Its purpose is to demonstrate deterministic repeatability, not to qualify an investment strategy.

The event-based research CLI's economics are gross and do not establish net profitability.

Historical bar-execution statistics computed for determinate outcomes must retain their determinate-subset labels and coverage information. Ambiguous and unresolved outcomes must not be silently reported as known wins or losses.

## 9. RIA findings and CURATE dispositions

| Finding | Severity | Incorporated correction |
|---|---|---|
| RIA-01 — Signal-candle chronology not explicit | Moderate | Added a 10:00–10:05 classroom example explaining why a 10:03 movement cannot trigger an opportunity formed at candle completion; added direct historical-execution sources |
| RIA-02 — Ambiguous lifecycle continuation insufficiently explained | Moderate | Added a distinct subsection explaining CLOSED-versus-CLOSED continuation and different-state termination without inventing one future branch |
| RIA-03 — Event-replay evidence could imply complete exchange history | Minor | Reworded the first notebook as accepted event-level replay inputs; distinguished reproducible source identity from independently qualified exchange coverage |
| RIA-04 — Source provenance too indirect | Minor | Expanded the source-to-claim register with exact chronology and ambiguity claims, plus immutable implementation references for historical execution, historical bars and backtesting |

The dispositions describe corrections incorporated into this revised draft. They do not constitute an independent second RIA assessment.

## 10. Governance and editorial status

This dated record accompanies the complete CURATE revision of Chapter 5, *The Trading Time Machine*.

The classroom time machine, teacher, dialogue, fictional OHLC figures and hypothetical stop and target are educational illustrations.

Chapter 5 deliberately defers detailed statistical validation, generalisation, overfitting, walk-forward testing and other trustworthiness questions to Chapters 6 and 7.

No existing SignalForge signal, entry, exit, sizing, recovery, source qualification, ambiguity or historical execution semantics are changed by this educational manuscript.

**Owner AAS approved: 13 November 2026.** This is editorial approval only, not research, strategy, engineering, PAPER or live trading permission.

This record is submitted for GitHub PR review; merge remains gated by REV, COR if needed, and FIN.
