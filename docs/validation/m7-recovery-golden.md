# M7 Recovery Golden Vertical

SF-053 is the M7 exit proof for the durable single-security paper runtime.

It validates composition of the recovery mechanisms delivered by SF-050 through SF-052 and
SF-067. It does not introduce new recovery architecture, schema or strategy semantics.

## Authority

- ADR-003 — Persistence, Recovery & Idempotency Contract
- ADR-008 — Strategy Runtime Boundary
- SF-050 — indicator recovery
- SF-051 — lifecycle recovery
- SF-052 — crash consistency and idempotency
- SF-067 — forming-candle and canonical-input recovery

## Golden matrix

| Scenario | Evidence |
|---|---|
| Indicator warm-up restart | checkpoint is restored and authoritative post-checkpoint candles converge to exact full recursive indicator state |
| Mid-candle restart | SF-067 golden proof restores exact CandleEngineState and converges to the uninterrupted completed candle |
| ARMED restart → trigger/open | fresh bootstrap/reconcile/hydrate chain continues to OPEN and persists trigger/fill/trade/position facts |
| ARMED restart → expiry | fresh hydrated ARMED state expires through accepted policy and persists terminal setup/transition |
| OPEN restart → target | recovered OPEN economics close at TARGET and durable graph remains terminal |
| OPEN restart → stop | recovered OPEN economics close at STOP and durable graph remains terminal |
| OPEN restart → compulsory exit | recovered OPEN economics close at FORCED_SESSION_EXIT and durable graph remains terminal |
| Terminal EXPIRED/CLOSED | authoritative terminal history hydrates to non-actionable IDLE and does not reopen |
| Pending EntryIntent without Fill | RecoveryBootstrap fails closed |
| RSI reference strategy | SF-067 cross-strategy proof uses the same market-input/checkpoint and requirement-driven recovery seam |

The SF-053 tests deliberately reuse the merged production contracts rather than introducing a
separate recovery host.

## Equivalence contract

Recoverable cases compare durable logical evidence, including:

- run/config provenance;
- full recursive indicator state;
- deterministic lifecycle identities;
- entry/stop/target/exit economics;
- Trade/Position terminal state;
- StateTransition evidence;
- generic StrategyDecisionFact output where the scenario contains completed evaluation;
- SF-067 MarketInputCheckpoint/CandleEngineState evidence for mid-candle restart.

Python object identity is not an equivalence criterion.

## Preserved fail-closed state

The accepted state:

```text
TRIGGERED
+ TriggerEvent
+ EntryIntent
- Fill
```

remains non-resumable and must raise an explicit recovery contradiction.

## Cross-strategy boundary

Recovery identity remains derived from RunIdentity/config provenance, exact IndicatorRequirements
and durable lifecycle/checkpoint facts. StrategyDecisionFact diagnostics are audit evidence only.

No strategy-ID dispatch or V1-shaped inference is introduced by SF-053.

## V1 deterministic non-regression

The existing pinned replay remains authoritative:

```text
events: 302
evaluations: 300
qualified: 1
actionable: 1
signals: 1
trades: 1
exits: 1
open_rejections: 0
final_lifecycle_state: closed
run_id: ace5ec067a78720d3f0d4ab28dd47cc05924e6143a54ba8192690a9944cac80a
source_id: b00a6d65ded8d5449a48ed012eb04e00b4bf65621e9939cd3f5b344940b3acbb
```

## Scope exclusions

SF-053 does not add:

- schema or migrations;
- new durable recovery mechanisms;
- strategy-semantic changes;
- OpenAlgo/live broker work;
- portfolio or multi-security behavior;
- a strategy DSL;
- M8 implementation.
