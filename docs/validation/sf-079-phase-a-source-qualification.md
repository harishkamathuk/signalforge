# SF-079 Phase A — Historical Source Qualification

## Purpose

This record captures the SF-079 Phase A source-qualification state before any production historical
provider adapter is implemented.

It is data-source evidence, not strategy-performance evidence.

## Gate A contract

A candidate may be marked:

- **SELECT** only when every mandatory qualification criterion is proven and a bounded,
  outcome-blind sample has been pre-registered;
- **REJECT** when at least one mandatory criterion is demonstrably failed;
- **BLOCKED** when evidence is incomplete and at least one mandatory criterion remains pending.

The reusable typed implementation is
`signalforge.research.source_qualification.HistoricalSourceQualification`.

The authoritative current candidate state is the executable
`signalforge.research.sf079_phase_a_report.CURRENT_SF079_PHASE_A_REPORT`. CI imports and validates
that report directly; this document explains the same state but is not the sole source of truth.

A SELECT decision is deliberately impossible while transport reliability, bounded repeatability,
retention depth, immutable implementation identity or another mandatory criterion remains pending.

## Current candidate state

### nsepython 2.101 — REJECT

Existing DATA-001 evidence found the tested NSE cash-equity historical path suitable only for
daily/EOD data rather than the required one-minute intraday sample.

Gate A consequence:

- one-minute capability: **FAILED**;
- decision: **REJECT**.

No SF-079 adapter should be built for this path.

### OpenChart 0.2.0 — REJECT

Existing DATA-001 evidence found that the tested path did not preserve trustworthy requested
instrument identity and did not produce sufficiently reliable bounded historical retrieval.

Gate A consequence:

- instrument/retrieval trustworthiness: **FAILED**;
- decision: **REJECT**.

No SF-079 adapter should be built for this path.

### nsemine 2.2.1 / SignalForge-nsemine candidate — BLOCKED

DATA-001 demonstrated useful semantics when retrieval succeeded:

- exact BAJAJ-AUTO equity identity was resolved;
- one-minute and five-minute historical OHLCV were observed;
- complete one-minute buckets aggregated deterministically to the provider five-minute OHLCV.

DATA-002 records the unresolved transport problem in the released nsemine path. The user's
SignalForge-nsemine local work is intended to test a repair, but that local validation is not yet
part of SignalForge evidence.

Current Gate A state:

| Criterion | State | Evidence position |
| --- | --- | --- |
| Exact instrument identity | PROVEN | DATA-001 captured BAJAJ-AUTO identity |
| One-minute capability | PROVEN | DATA-001 successful historical retrieval |
| Timestamp semantics | PENDING | prior evidence exists, but the repaired path must be re-observed before SELECT |
| Retention depth | PENDING | transport reliability prevented a defensible measurement |
| Bounded repeatability | PENDING | fresh repeated acquisitions not yet proven |
| Missing/duplicate behavior | PENDING | must be measured on the selected bounded sample |
| Corporate-action policy | PENDING | must be explicit for the eventual sample |
| Volume semantics | PENDING | must be confirmed for the selected path |
| Authentication/session boundary | PENDING | DATA-002 documents prior behavior; repaired path still needs fresh evidence |
| Rate-limit/throttling boundary | PENDING | must be documented during bounded probes |
| Raw/reference retention | PENDING | depends on the selected acquisition path and source terms |
| Data-use constraints | PENDING | must be documented before storing/sharing captured source data |
| Transport reliability | PENDING | local SignalForge-nsemine validation not yet completed |
| Implementation identity | PENDING | exact local repository/commit identity under validation is not yet recorded |

Decision: **BLOCKED_PENDING_LOCAL_VALIDATION**.

The blocked state is intentional. It prevents Phase B adapter implementation from treating a
promising but incompletely validated source as canonical.

The local repaired implementation must be identified by immutable source identity (for example,
repository plus commit SHA or equivalent build/source hash). Reporting only the upstream package
version `2.2.1` is insufficient once local code differs from that release.

## Sample pre-registration

No SF-079 research sample is frozen yet.

That is deliberate rather than incomplete implementation: the source's retention depth and reliable
bounded query behavior are still pending, so selecting exact first/last session dates now would be
speculative.

If nsemine passes the local validation and Gate A moves to SELECT, the Gate A evidence update must
freeze, before any strategy-result inspection:

- exact SignalForge instrument identity;
- exact provider instrument identity;
- first and last regular NSE session dates;
- coverage-led rationale;
- source/library/fork version.

The chosen window must not be extended or shortened because of signal frequency, trade outcomes or
performance.

## Session-calendar evidence required before Phase B completion

The canonical dataset requires explicit `expected_session_dates`.

SF-079 must not infer those dates by:

- assuming all weekdays are trading sessions; or
- treating missing provider rows as exchange holidays.

Before the real dataset is constructed, the implementation must retain the source/snapshot identity
for the NSE regular-session calendar used by the sample.

Exceptional/special sessions remain outside the current 09:15–15:30 canonical session contract
unless separately supported.

## Tick-size evidence required before SF-080

SF-078 consumes an effective-dated `TickSizeSchedule`.

The selected source dataset is not ready for execution research until SF-079 has evidence for the
applicable historical tick-size rule on every included session.

Current tick size must not be projected backwards without evidence.

The eventual smoke-run evidence must retain the actual tick-schedule semantic identity.

## Handoff from local SignalForge-nsemine testing

The local validation should provide evidence sufficient to update the nsemine candidate record,
especially:

1. bootstrap/session reliability;
2. exact symbol/instrument resolution;
3. bounded one-minute historical retrieval;
4. two or more independent acquisitions of the same bounded range;
5. equality or explained differences between repeated acquisitions;
6. measured retention/window depth;
7. timestamp and interval-label semantics;
8. missing/duplicate/correction behavior;
9. provider adjustment and volume semantics where observable;
10. any rate-limit or anti-bot behavior material to reproducibility;
11. exact local repository + commit/build identity for the code under test;
12. dated/versioned probe artifacts or content hashes for every evidence item promoted to PROVEN.

If the repaired path satisfies every mandatory criterion, update the qualification to SELECT and
freeze the sample before Phase B implementation.

If it fails a mandatory criterion, update it to REJECT.

If important evidence remains unknowable, leave it BLOCKED rather than lowering the standard.

## What Phase A implements

Phase A adds:

- typed qualification criteria;
- explicit SELECT / REJECT / BLOCKED semantics;
- deterministic qualification semantic identity including implementation revision and evidence snapshot identity;
- outcome-blind sample pre-registration;
- validation that SELECT cannot occur with pending evidence;
- validation that blocked/rejected decisions have explicit evidence;
- a committed executable current-source report validated by CI;
- repository evidence documenting the current source state.

It does **not** add:

- a nsemine provider adapter;
- network calls in tests;
- real market-data files;
- a canonical real dataset;
- strategy-performance results;
- Phase C historical-execution smoke results.

## Exit state

Phase A framework implementation is complete.

**Gate A is not passed.**

Current actionable state:

`nsemine / SignalForge-nsemine → BLOCKED_PENDING_LOCAL_VALIDATION`

Phase B must not begin until that status becomes SELECT, or another source passes Gate A.
