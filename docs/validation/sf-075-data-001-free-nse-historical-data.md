# SF-075 / DATA-001 — Free NSE Historical Data Evaluation

**Status:** In progress — source/API evidence captured; live runtime probes pending  
**Issue:** #186  
**Research identifier:** DATA-001  
**Date:** 2026-10-11  
**Strategy semantics changed:** No  
**Runtime/replay semantics changed:** No  
**Schema/migrations changed:** No

## Purpose

Evaluate free NSE intraday historical-data sources for SignalForge's existing Research Harness
without introducing a second backtester or manufacturing event chronology that an OHLCV source
does not contain.

This document deliberately separates:

1. evidence verified from package/repository source and published package metadata; and
2. empirical runtime/network evidence, which must be captured before DATA-001 can close.

A candidate is not selected merely because its README advertises the required interval.

## Existing SignalForge boundary

The current research path consumes canonical historical inputs through:

```text
ReplaySource
    ↓
ReplayInput
    ↓
MarketEvent
```

`MarketEvent` is event-level data with an exchange timestamp, receive timestamp, price,
quantity, source and optional source-event identity.

An OHLCV bar does not encode the order in which its high and low occurred. Therefore DATA-001
must not expand an OHLCV bar into synthetic ticks/events merely to satisfy `ReplaySource`.
Doing so could change entry, stop, target and realised-R outcomes.

The existing Research Harness, dataset identities, backtest runner and orchestration remain
authoritative and are reused unchanged by this work item.

## Evidence method and current limitation

Repository/package source was inspected for all three initial candidates. Published PyPI metadata
was also checked for current versions and licences.

The current implementation environment cannot establish outbound package-install/provider
sessions, so the required bounded live retrieval tests have **not** yet been executed here.
Those checks remain acceptance criteria and must be run in a normal developer environment before
a final SELECT/REJECT decision is recorded.

No source-level claim below is presented as successful runtime proof.

## Candidate comparison — preliminary

| Dimension | nsepython | OpenChart | nsemine |
| --- | --- | --- | --- |
| Published version inspected | 2.101 | 0.2.0 | 2.2.1 |
| Licence | GPL-3.0 | MIT | MIT |
| Historical equity representation | Aggregated historical records | OHLCV bars | OHLCV bars |
| 5-minute historical API in inspected source | Not established | Advertised/implemented | Advertised/implemented |
| 1-minute historical API in inspected source | Not established | Advertised/implemented | Advertised/implemented |
| Historical event/tick chronology | Not established | No — historical path is bars | No — historical path is bars |
| Current-session tick API | Not material to historical requirement | Not established | Yes, current-session tick-by-tick API |
| ReplaySource compatibility | INSUFFICIENT / BAR-LEVEL only if history works | BAR_ONLY | BAR_ONLY |
| Timestamp/timezone risk | Runtime evidence required | High-priority runtime check | High-priority runtime check |
| Runtime repeatability | Pending | Pending | Pending |
| Preliminary disposition | PROVISIONAL REJECT | CANDIDATE | CANDIDATE |

`PROVISIONAL REJECT` and `CANDIDATE` are not final DATA-001 verdicts.

## nsepython findings

Current published package metadata identifies nsepython 2.101 and the repository licence is
GPL-3.0.

The inspected `equity_history()` implementation still delegates to the historical cash-market
equity API path via `equity_history_virgin()`. A January 2026 repository issue documents that
NSE removed the underlying `/api/historical/cm/equity` endpoint and that the call returned HTTP
404. The current source inspection did not establish a replacement 1-minute or 5-minute
historical equity path.

### Preliminary assessment

For DATA-001's mandatory intraday requirement, nsepython is a **provisional rejection** unless a
runtime test of 2.101 demonstrates a newer working intraday mechanism not identified in the
inspected source.

Required local confirmation:

- install exactly 2.101;
- attempt the historical equity function on a bounded liquid-equity range;
- identify any current intraday-equity API not found by source inspection;
- capture response/failure classification without retaining credentials/cookies.

Do not adopt nsepython merely because the package received a recent release.

## OpenChart findings

Published package metadata identifies OpenChart 0.2.0 under the MIT licence.

The inspected implementation uses NSE's charting service:

```text
https://charting.nseindia.com/v1/exchanges/symbolsDynamic
https://charting.nseindia.com/v1/charts/symbolHistoricalData
```

The historical API maps `1m` and `5m` to intraday chart requests and returns aggregated
OHLCV.

The transformation code converts millisecond timestamps with `utc=True` and then removes
timezone information. Intraday filtering is subsequently performed on the resulting naive
timestamp. The actual provider timestamp convention must therefore be established empirically
before SignalForge can rely on these values.

### Preliminary assessment

OpenChart is a serious free candidate for **historical OHLCV acquisition**, but its historical
path is `BAR_ONLY`; it cannot legitimately enter the existing event-level `ReplaySource` by
inventing intra-bar chronology.

Required runtime evidence:

- RELIANCE or the configured Strategy V1 instrument;
- 1-minute and 5-minute bounded recent range;
- longer-range retention/window test;
- actual timestamp/timezone interpretation;
- duplicate/missing intervals;
- same-range repeat retrieval;
- bounded 1-minute → 5-minute aggregation reconciliation.

## nsemine findings

Current published package metadata identifies nsemine 2.2.1 under the MIT licence.

The inspected historical API accepts minute intervals including 1 and 5 and calls NSE chart
data after resolving an instrument token. Returned historical data is OHLCV.

The source contains non-trivial timestamp handling:

- an explicit +05:30 offset is applied to intraday request epoch values;
- returned timestamps are processed as naive datetimes;
- intraday session filtering and bar-time adjustment are performed by library utilities;
- duplicates are dropped by datetime.

These are precisely the kinds of transformations SignalForge must independently validate rather
than inherit as unquestioned truth.

nsemine also exposes a current-session tick-by-tick function. That does **not** establish
historical event/tick availability and therefore does not solve the historical
`MarketEvent`/ReplaySource compatibility requirement.

### Preliminary assessment

nsemine is a serious free candidate for **historical OHLCV acquisition** and merits runtime
comparison with OpenChart.

Its historical path is currently classified `BAR_ONLY`.

Required runtime evidence is the same bounded test matrix used for OpenChart, with particular
attention to timestamp alignment and any library-level timestamp adjustment.

## Replay compatibility conclusion

Based on source inspection:

```text
nsepython historical equity
    → no proven usable intraday source
    → INSUFFICIENT pending runtime confirmation

OpenChart historical
    → aggregated OHLCV
    → BAR_ONLY

nsemine historical
    → aggregated OHLCV
    → BAR_ONLY
```

Neither OpenChart nor nsemine historical data should be converted to a fake sequence such as
`open → high → low → close` or `open → low → high → close`.

Five-minute bars can support candle/indicator/signal validation. One-minute bars can reduce
execution uncertainty, but they remain ambiguous when entry/stop/target levels are all reachable
inside the same minute.

A separate historical-bar research boundary may therefore be required after DATA-001 if a free
bar source is selected. That work must be a separately reviewed SF item because the chosen
execution treatment can change trades.

## Dataset provenance contract — proposed minimum

A selected acquisition path should preserve at least:

- provider/source;
- package/library and exact version;
- upstream endpoint/source;
- instrument identity;
- interval;
- requested start/end;
- actual returned start/end;
- acquisition timestamp;
- provider timestamp representation and SignalForge interpretation;
- row count;
- known missing/duplicate intervals;
- content digest;
- canonicalisation version;
- known corporate-action limitations;
- known retention/window limitations.

Acquisition time is provenance but should not make semantically identical market content obtain
a different content identity unless the accepted dataset identity contract explicitly requires
that.

## Local persistence assessment

No new persistence subsystem is justified by the source-level evidence alone.

Parquet remains a suitable project direction for immutable analytical datasets, but DATA-001
should first prove a provider and freeze the canonical bar/provenance schema. A meaningful Parquet
or historical-bar integration should become a follow-up issue rather than being smuggled into
this discovery item.

## Runtime probe required to complete DATA-001

Run the following matrix from a normal developer environment with outbound access:

1. use one explicit liquid NSE cash equity;
2. fetch a short recent 5-minute range;
3. fetch the corresponding 1-minute range where supported;
4. fetch a larger range sufficient to expose retention/window limits;
5. repeat an identical bounded request twice;
6. validate ordering, duplicates, gaps, OHLC invariants, volume and session boundaries;
7. determine actual timezone semantics from returned provider data;
8. where both resolutions are trustworthy, aggregate 1-minute → 5-minute and reconcile;
9. record exact package versions, request ranges, row counts and content digests;
10. classify each source as SELECT, RETAIN_AS_FALLBACK or REJECT.

No network-dependent test should be added to normal CI.

## Preliminary recommendation

Do not implement a production adapter yet.

The current evidence supports:

- **nsepython:** likely unsuitable for the required historical intraday path; confirm once with
  current-version runtime evidence.
- **OpenChart:** runtime-test candidate.
- **nsemine:** runtime-test candidate.
- **ReplaySource:** no change in SF-075.
- **Strategy V1:** no change.
- **Execution semantics:** no change.

If OpenChart or nsemine proves adequate, DATA-001 should then recommend the smallest follow-up
engineering item for a canonical historical OHLCV research-source boundary and immutable dataset
format. That follow-up must not fabricate event chronology.

## References

- SF-075 / DATA-001: https://github.com/harishkamathuk/signalforge/issues/186
- nsepython: https://github.com/aeron7/nsepython
- nsepython historical-equity endpoint issue: https://github.com/aeron7/nsepython/issues/74
- OpenChart: https://github.com/marketcalls/openchart
- nsemine: https://github.com/kbizme/nsemine

## Completion status

SF-075 is **not complete** from source inspection alone.

Outstanding blocker: empirical candidate retrieval/repeatability/timestamp/retention evidence
must be captured from an environment able to reach the public NSE/charting endpoints.
