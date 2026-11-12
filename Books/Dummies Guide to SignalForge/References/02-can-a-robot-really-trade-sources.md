# Chapter 2 — Source verification record

**Editorial status:** AAS approved by the book owner on 12 November 2026.
**Chapter:** [Can a Robot Really Trade?](../Chapters/02-can-a-robot-really-trade.md)
**Verification date:** 12 November 2026
**Repository:** `harishkamathuk/signalforge`
**Immutable revision:** [`6e1b5750acf07e9f91a90cc843a5002de8958c32`](https://github.com/harishkamathuk/signalforge/commit/6e1b5750acf07e9f91a90cc843a5002de8958c32)
**Verification method:** Retrieved current `develop` documents and checked the referenced normative/operational files at the immutable revision. This is documentary verification, **not** independent execution, CI validation, a profitable backtest, broker-fill evidence or PAPER/live permission.

| Chapter claim or explanation | Classification | Dated evidence |
|---|---|---|
| Initial NSE equity strategy uses completed five-minute candles | Approved strategy description | [README](https://github.com/harishkamathuk/signalforge/blob/6e1b5750acf07e9f91a90cc843a5002de8958c32/README.md) |
| Qualification, ARMED policy, entry trigger, expiry and fill are distinct; Strategy V1 has immediately-following-candle validity | Accepted normative architecture | [ADR-008 — Strategy Runtime Boundary](https://github.com/harishkamathuk/signalforge/blob/6e1b5750acf07e9f91a90cc843a5002de8958c32/docs/architecture/decisions/ADR-008-strategy-runtime-boundary.md) |
| The initial strategy uses the signal-candle low for its stop and actual-fill-based target economics | Accepted strategy contract | [ADR-008](https://github.com/harishkamathuk/signalforge/blob/6e1b5750acf07e9f91a90cc843a5002de8958c32/docs/architecture/decisions/ADR-008-strategy-runtime-boundary.md) |
| Paper execution does not presume a fill at the trigger price | Historical architectural reference, subordinate to later normative contracts | [ADR-007 — Paper Execution & Fill Model](https://github.com/harishkamathuk/signalforge/blob/6e1b5750acf07e9f91a90cc843a5002de8958c32/docs/architecture/decisions/ADR-007-paper-execution-fill-model.md) |
| Live PAPER operator is explicitly PAPER-only, without broker-order placement; readiness and reconciliation checks apply | Documented software/operational capability; **not** qualification or deployment approval | [Live PAPER operations](https://github.com/harishkamathuk/signalforge/blob/6e1b5750acf07e9f91a90cc843a5002de8958c32/docs/live-paper-operations.md) |
| Deterministic replay accepts historical input with explicitly selected strategy | Documented software capability | [Replay CLI](https://github.com/harishkamathuk/signalforge/blob/6e1b5750acf07e9f91a90cc843a5002de8958c32/docs/replay-cli.md) |
| Recovery, auditability and paper-before-live are project principles | Contextual project intent | `01-signalforge-project-charter.md`; `02-signalforge-technical-context.md` (uploaded sources; not Git-native authority) |
| General broker orders, order acknowledgements, fills, partial fills, price uncertainty and stop-loss concepts | Evergreen market education | General explanation, **not** asserted implemented SignalForge broker execution |
| Robo, security guard, cakes, cinema ticket, flight simulator, ₹1,000/₹1,002/₹990 and 10:05 example | Hypothetical teaching devices | No historical trade, paper evidence, simulated result or realised P&L asserted |
| Eventual real broker execution | Future possibility subject to explicit gates | Project charter / README aspiration; **not** permitted or ready |

## Provenance and limitations

- The immutable Git revision above preserves the versions that were used during this chapter's editorial verification. Consult current `develop` separately for operational status.
- ADR-007 is marked as **historical and retrospectively reconstructed**. It supplies context, not an override of later accepted ADRs, strategy specifications, source/tests or actual runtime contracts.
- A documented command and its prerequisites do not prove multi-session PAPER validation, acceptance of economic research evidence, actual broker fills or live-capital readiness.
- All prices, times and events in Robo's story are fictional teaching illustrations. Do not back-project them as actual SignalForge logs.
- The Chapter 2 draft intentionally defers mathematical strategy details to Chapter 3.

## RIA → CURATE disposition

| RIA finding | CURATE disposition |
|---|---|
| F01 — Qualification versus orders | Clarified qualified opportunity → ARMED → timed trigger → mode-dependent execution |
| F02 — Paper versus real fills | Distinct dedicated examples and explicit model-versus-actual boundary |
| F03 — Opportunity lifetime | Explicit immediately following five-minute candle validity |
| F04 — Stop-loss guarantee | Explained software-monitored stops versus broker orders and non-guaranteed exit price |
| F05 — Repetition with Chapter 1 | Shortened indicators/obedience discussion and emphasised execution |
| F06 — Provenance | Classified claims, dated verification and immutable Git sources |
| F07 — One fictional narrative | Robo through-line; alternate scenarios identified |
| F08 — Bakery/market simplification | Qualified by actual order types, counterparties and venue rules |

**Approval boundary:** Editorial AAS only. No strategy change, software delivery, research gate, PAPER/live approval or trading-performance claim.
