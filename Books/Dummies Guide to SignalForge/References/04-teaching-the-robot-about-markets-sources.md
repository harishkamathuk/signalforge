# Chapter 4 — Source Verification Record

**Chapter:** [Teaching the Robot About Markets](../Chapters/04-teaching-the-robot-about-markets.md)
**Editorial stage:** Owner AAS approved — 13 November 2026
**Verification date:** 13 November 2026
**Repository:** `harishkamathuk/signalforge`
**Immutable Git revision:** [`79ebf2e5296d71dc75f492743e056206ef4f4f4c`](https://github.com/harishkamathuk/signalforge/commit/79ebf2e5296d71dc75f492743e056206ef4f4f4c)

## Source-to-claim register

| Chapter assertion | Evidence classification | Immutable source |
|---|---|---|
| Initial NSE strategy uses completed five-minute candles | Approved strategy orientation | [Repository README](https://github.com/harishkamathuk/signalforge/blob/79ebf2e5296d71dc75f492743e056206ef4f4f4c/README.md) |
| Exchange/market event time and received time are distinct recorded concepts | Implemented domain model | [Market domain](https://github.com/harishkamathuk/signalforge/blob/79ebf2e5296d71dc75f492743e056206ef4f4f4c/signalforge/domain/market.py) |
| Live OpenAlgo messages may be quote snapshots without stable provider event IDs or replayable sequences | Accepted normative architecture | [ADR-009](https://github.com/harishkamathuk/signalforge/blob/79ebf2e5296d71dc75f492743e056206ef4f4f4c/docs/architecture/decisions/ADR-009-live-market-data-continuity-reconciliation-boundary.md) |
| Historical source timestamps require explicit interpretation, and canonical bar interval identity is separate from raw provider timestamps | Accepted normative architecture | [ADR-010](https://github.com/harishkamathuk/signalforge/blob/79ebf2e5296d71dc75f492743e056206ef4f4f4c/docs/architecture/decisions/ADR-010-canonical-historical-ohlcv-dataset-boundary.md) |
| Canonical historical OHLCV bars have explicit price, volume, quality, ordering and provenance invariants | Accepted normative architecture | [ADR-010](https://github.com/harishkamathuk/signalforge/blob/79ebf2e5296d71dc75f492743e056206ef4f4f4c/docs/architecture/decisions/ADR-010-canonical-historical-ohlcv-dataset-boundary.md) |
| Five-minute historical aggregate is VALID only when all five required canonical one-minute constituents are present and valid | Accepted aggregation contract | [ADR-010](https://github.com/harishkamathuk/signalforge/blob/79ebf2e5296d71dc75f492743e056206ef4f4f4c/docs/architecture/decisions/ADR-010-canonical-historical-ohlcv-dataset-boundary.md), [Historical-bar research](https://github.com/harishkamathuk/signalforge/blob/79ebf2e5296d71dc75f492743e056206ef4f4f4c/docs/api/historical-bar-research.md) |
| A non-VALID derived candle fails the implemented historical research run rather than silently skipping a gap | Implemented research boundary | [Historical-bar research](https://github.com/harishkamathuk/signalforge/blob/79ebf2e5296d71dc75f492743e056206ef4f4f4c/docs/api/historical-bar-research.md) |
| VALID, INCOMPLETE, MISSING and CORRUPT are distinct classifications; missing provider rows must not be assumed to represent zero trading | Accepted historical-data contract | [ADR-010](https://github.com/harishkamathuk/signalforge/blob/79ebf2e5296d71dc75f492743e056206ef4f4f4c/docs/architecture/decisions/ADR-010-canonical-historical-ohlcv-dataset-boundary.md), [Market domain](https://github.com/harishkamathuk/signalforge/blob/79ebf2e5296d71dc75f492743e056206ef4f4f4c/signalforge/domain/market.py) |
| A structurally valid record does not automatically establish dataset provenance, complete coverage, research suitability or executable historical fills | Accepted historical-data contract | [ADR-010](https://github.com/harishkamathuk/signalforge/blob/79ebf2e5296d71dc75f492743e056206ef4f4f4c/docs/architecture/decisions/ADR-010-canonical-historical-ohlcv-dataset-boundary.md), [Historical-bar research](https://github.com/harishkamathuk/signalforge/blob/79ebf2e5296d71dc75f492743e056206ef4f4f4c/docs/api/historical-bar-research.md) |
| Live feed health, market-history continuity and durable trading state are separate; an unprovable gap blocks same-run price-sensitive continuation | Accepted normative architecture | [ADR-009](https://github.com/harishkamathuk/signalforge/blob/79ebf2e5296d71dc75f492743e056206ef4f4f4c/docs/architecture/decisions/ADR-009-live-market-data-continuity-reconciliation-boundary.md) |
| ARMED and OPEN PAPER states are preserved for reconciliation rather than silently triggered, expired, closed or erased across an unprovable gap | Accepted normative architecture | [ADR-009](https://github.com/harishkamathuk/signalforge/blob/79ebf2e5296d71dc75f492743e056206ef4f4f4c/docs/architecture/decisions/ADR-009-live-market-data-continuity-reconciliation-boundary.md) |
| Strategy V1 minimum warmup is 250 completed regular-session candles | Versioned strategy configuration | [Strategy V1 configuration](https://github.com/harishkamathuk/signalforge/blob/79ebf2e5296d71dc75f492743e056206ef4f4f4c/signalforge/config/strategy_v1.py) |
| Warmup threshold, indicator readiness, continuity, candle quality and feed health are distinct evaluation guards | Implemented eligibility/actionability contract | [Eligibility guards](https://github.com/harishkamathuk/signalforge/blob/79ebf2e5296d71dc75f492743e056206ef4f4f4c/signalforge/runtime/eligibility.py) |
| Live PAPER preparation uses historical candles for indicator readiness without generating historical trading lifecycle events | Implemented operating procedure | [Live PAPER operations](https://github.com/harishkamathuk/signalforge/blob/79ebf2e5296d71dc75f492743e056206ef4f4f4c/docs/live-paper-operations.md) |
| Historical OHLCV research and market-event replay have different evidence boundaries; OHLCV alone cannot establish intrabar trigger/stop/target ordering | Accepted architecture and implemented research documentation | [ADR-010](https://github.com/harishkamathuk/signalforge/blob/79ebf2e5296d71dc75f492743e056206ef4f4f4c/docs/architecture/decisions/ADR-010-canonical-historical-ohlcv-dataset-boundary.md), [Historical-bar research](https://github.com/harishkamathuk/signalforge/blob/79ebf2e5296d71dc75f492743e056206ef4f4f4c/docs/api/historical-bar-research.md) |
| Completed-candle and indicator continuity principles | Historical architectural reference, subordinate to later accepted decisions | [ADR-005](https://github.com/harishkamathuk/signalforge/blob/79ebf2e5296d71dc75f492743e056206ef4f4f4c/docs/architecture/decisions/ADR-005-market-data-candle-contract.md), [ADR-006](https://github.com/harishkamathuk/signalforge/blob/79ebf2e5296d71dc75f492743e056206ef4f4f4c/docs/architecture/decisions/ADR-006-indicator-engine-contract.md) |

## Source authority

ADR-009 and ADR-010 are accepted normative architecture decisions in their respective domains.

ADR-005 and ADR-006 are retrospectively reconstructed historical references. They are retained for architectural context, not to override later accepted ADRs or current source behaviour.

The explicit 250-candle threshold comes from the versioned Strategy V1 configuration. The implementation separately checks indicator readiness and continuity; meeting the count alone does not guarantee actionability.

The accepted live PAPER contract treats feed health, market-history continuity and durable lifecycle state as distinct concepts. Reconnection does not prove uninterrupted chronology, and recovery of saved lifecycle state does not independently authorise the resumption of price-sensitive actions.

## Historical-data boundary

The fictional missing-minute example illustrates the canonical historical one-minute-to-five-minute aggregation process.

With four of five expected valid one-minute constituents, the derived five-minute candle is INCOMPLETE. The implemented historical-bar research runner reports a continuity error for non-VALID derived candles rather than silently skipping them or advancing indicators as if the gap did not exist.

This rule must not be represented as a universal requirement for a live five-minute candle to contain one trade in every constituent minute.

A historically VALID source bar has passed the relevant structural requirements for that bar. The wider dataset's provenance, expected coverage and suitability for any specific research purpose still require their own evidence.

## Live-provider boundary

The accepted OpenAlgo live PAPER path may receive quote snapshots rather than uniquely identified, replayable provider trade events.

The presence of market or received timestamps does not create a genuine provider sequence or a stable provider event ID.

When a genuine interruption leaves live market chronology unprovable, SignalForge preserves its last trusted durable ARMED or OPEN state and blocks further same-run price-sensitive progression pending reconciliation.

The chapter does not imply that reconnecting reconstructs missed events or that automatic broker-position reconciliation and emergency live-capital protections are already provided.

## Illustrations and evidence limitations

Robo, the teacher, report cards, classroom radio, hypothetical marks, OHLCV examples and historical missing-minute exercise are fictional educational devices.

They are not observed NSE data, independently qualified historical datasets, broker fills, executed trading experiments or profitability evidence.

The cited material establishes documentary and source-code provenance. This chapter has not independently executed the referenced test suites. No live-capital readiness or profitable strategy claim is made.

## RIA findings and CURATE dispositions

| Finding | Original severity | Disposition |
|---|---|---|
| F01 — Live observations need clearer provenance | Moderate | Distinguished exchange activity, provider quote snapshots and message delivery; explained limitations of provider event IDs, ordering and timestamp interpretation |
| F02 — VALID could imply full dataset trustworthiness | Moderate | Narrowed VALID to the relevant record/aggregate checks and introduced separate coverage, provenance and research-suitability questions |
| F03 — Historical continuity consequence omitted | Minor | Explained that a non-VALID derived candle causes the historical research run to fail explicitly rather than silently skip the missing period |
| F04 — Source support for 250-candle threshold incomplete | Minor | Added the immutable Strategy V1 configuration and separated the warmup count from readiness and continuity guards |
| F05 — Historical research versus replay too technical | Minor | Simplified the report-card analogy and used the high/low ordering example before introducing the two research paths |

## Governance and editorial status

Owner AAS approved this revised Chapter 4 manuscript and its source record on 13 November 2026. This approval is editorial only and does not endorse real-capital trading, historical profitability claims or a different data/execution contract.

No approved SignalForge strategy, execution, market-data qualification, historical-data research or recovery contract is changed by the manuscript.
