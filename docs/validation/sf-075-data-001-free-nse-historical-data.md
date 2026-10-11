# SF-075 / DATA-001 — Free NSE Historical Data Evaluation

**Status:** Complete — no source selected; nsemine retained as fallback pending transport remediation  
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

The original implementation environment could not establish outbound package-install/provider
sessions. Runtime probing has therefore moved to a normal local developer environment with
outbound NSE/charting access.

OpenChart 0.2.0 has now been exercised empirically. nsemine 2.2.1 has passed the first bounded
5-minute retrieval/identity gate. Its 1-minute path has also returned a substantial BAJAJ-AUTO session with clean one-minute grid semantics for the rows received, although seven expected minute slots were absent. Provider timezone semantics, repeatability and retention remain open. nsepython 2.101 still requires its intentional bounded confirmation probe
before DATA-001 can close.

Source-inspection claims and runtime observations are kept distinct below.

## Candidate comparison — final

| Dimension | nsepython | OpenChart | nsemine |
| --- | --- | --- | --- |
| Published version inspected | 2.101 | 0.2.0 | 2.2.1 |
| Licence | GPL-3.0 | MIT | MIT |
| Historical equity representation | Daily/EOD historical records | OHLCV bars | OHLCV bars |
| 5-minute historical API in inspected source | No historical intraday cash-equity path found | Advertised/implemented | Advertised/implemented |
| 1-minute historical API in inspected source | No historical intraday cash-equity path found | Advertised/implemented | Proven at runtime for BAJAJ-AUTO; 368 rows returned for one regular session |
| Historical event/tick chronology | Not established | No — historical path is bars | No — historical path is bars |
| Current-session tick API | Not material to historical requirement | Not established | Yes, current-session tick-by-tick API |
| ReplaySource compatibility | INSUFFICIENT / BAR-LEVEL only if history works | BAR_ONLY | BAR_ONLY |
| Timestamp/timezone risk | Runtime evidence required | High-priority runtime check | High-priority runtime check |
| Runtime repeatability | Pending | Not reached — valid instrument-specific bars were not obtained | Inconclusive — fresh acquisitions are blocked by curl_cffi/BoringSSL TLS failures before symbol/history requests |
| Final disposition | REJECT — daily-only, insufficient for mandatory intraday requirement | REJECT — observed 0.2.0 runtime path failed retrieval/identity requirements | RETAIN_AS_FALLBACK — promising captured 1m/5m data quality, but repeatability and retention cannot be established because released transport is unreliable |

These are the final DATA-001 dispositions for the versions tested. No candidate is `SELECT`.

## nsepython findings

Current published package metadata identifies nsepython 2.101 and the repository licence is
GPL-3.0.

The inspected `equity_history()` implementation still delegates to the historical cash-market
equity API path via `equity_history_virgin()`. A January 2026 repository issue documents that
NSE removed the underlying `/api/historical/cm/equity` endpoint and that the call returned HTTP
404. The current source inspection did not establish a replacement 1-minute or 5-minute
historical equity path.

### Runtime confirmation — nsepython 2.101

Installed-source inspection confirmed:

- `equity_history()` delegates to `equity_history_virgin()`;
- the active cash-equity historical endpoint is `/api/historicalOR/cm/equity`;
- the older `/api/historical/cm/equity` path remains only as commented legacy code;
- `security_wise_archive()` uses `/api/historicalOR/generateSecurityWiseHistoricalData` for daily price/volume/deliverables;
- `nse_mcp_get_stock_history()` explicitly supplies daily OHLCV;
- no 1-minute or 5-minute historical cash-equity replacement/fallback was found in installed 2.101 source.

The bounded public call was:

```python
nsepython.equity_history(
    "BAJAJ-AUTO", "EQ", "09-10-2026", "09-10-2026"
)
```

It requested:

```text
https://www.nseindia.com/api/historicalOR/cm/equity?symbol=BAJAJ-AUTO&series=["EQ"]&from=09-10-2026&to=09-10-2026
```

and returned HTTP 200 with exact identity `CH_SYMBOL=BAJAJ-AUTO`, `CH_SERIES=EQ`.

One daily record was returned for 2026-10-09:

| Open | High | Low | Close | Traded quantity |
| ---: | ---: | ---: | ---: | ---: |
| 9663 | 9968 | 9645 | 9778 | 249546 |

The returned schema is daily/EOD-oriented and includes fields such as opening price, trade high/low,
closing price, total traded quantity/value and total trades. No intraday granularity was exposed.

The homepage warm-up experienced a curl/TLS error, but the actual historical request succeeded.
No retry was performed.

### DATA-001 assessment

nsepython 2.101 is classified **DAILY_ONLY / INSUFFICIENT** for DATA-001.

The replacement `historicalOR` endpoint proves that current daily cash-equity history still works,
but no 1-minute or 5-minute historical equity path was found in the installed package. This does
not satisfy DATA-001's mandatory intraday requirement.

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

Required runtime evidence was originally:

- RELIANCE or the configured Strategy V1 instrument;
- 1-minute and 5-minute bounded recent range;
- longer-range retention/window test;
- actual timestamp/timezone interpretation;
- duplicate/missing intervals;
- same-range repeat retrieval;
- bounded 1-minute → 5-minute aggregation reconciliation.

### Runtime evidence — OpenChart 0.2.0

Runtime probing used **BAJAJ-AUTO** as the explicit NSE cash-equity proof instrument.

The direct historical path reached:

```text
POST https://charting.nseindia.com/v1/charts/symbolHistoricalData
```

with HTTP 200 but returned:

```json
{"status": true, "data": []}
```

for a bounded 5-minute request using token `16669`. The initial request used
`symbol="BAJAJ-AUTO"`; a controlled correction using the exchange-style
`symbol="BAJAJ-AUTO-EQ"` produced the same empty result.

The corrected payload was:

```json
{
  "token": "16669",
  "symbol": "BAJAJ-AUTO-EQ",
  "symbolType": "Equity",
  "fromDate": 1791517500,
  "toDate": 1791521100,
  "chartType": "I",
  "timeInterval": 5
}
```

Those epochs corresponded to:

- `fromDate`: 2026-10-09 03:45:00 UTC / 2026-10-09 09:15:00 Asia/Kolkata;
- `toDate`: 2026-10-09 04:45:00 UTC / 2026-10-09 10:15:00 Asia/Kolkata.

A controlled HTTP-method comparison changed only the transport from POST-with-JSON to
GET-with-query-parameters. The endpoint again returned HTTP 200 with `status=true` and zero
data entries. The failure therefore cannot be attributed to POST alone.

A final high-level library probe used:

```python
NSEData().historical(
    symbol="BAJAJ-AUTO-EQ",
    segment="EQ",
    start=datetime(2026, 10, 5, 9, 15),
    end=datetime(2026, 10, 9, 15, 30),
    interval="5m",
)
```

The symbol-search step returned 20 index results with **no BAJAJ-AUTO match**. OpenChart then
silently selected the first result:

```text
symbol:     NIFTY 50
scripcode:  26000
type:       Index
```

and issued the historical request for NIFTY 50 rather than BAJAJ-AUTO. That request also returned
HTTP 200 with `status=true` and an empty data array.

The high-level probe used naive datetimes, which Python converted using the host
`Europe/London` timezone. No timezone correction was attempted because the more fundamental
instrument-identity and retrieval requirements had already failed.

### Runtime assessment

OpenChart 0.2.0 is **REJECTED for DATA-001 in its observed form**.

The decisive failure is not merely that historical requests returned zero bars. The public
high-level equity path failed to preserve the requested instrument identity and silently fell back
from BAJAJ-AUTO to NIFTY 50. That is incompatible with SignalForge's reproducibility and
auditability requirements because downstream research could otherwise operate on the wrong
security without an explicit failure.

Because no trustworthy BAJAJ-AUTO historical bars were obtained, the following checks were not
meaningful and remain unproven for OpenChart:

- 1-minute depth;
- larger retention/window limits;
- provider timestamp semantics;
- missing/duplicate intervals;
- repeat-download equality;
- 1-minute → 5-minute reconciliation.

No additional payload, epoch, timezone or HTTP-method permutations are justified for SF-075
without new evidence that the current OpenChart path can first preserve instrument identity and
return instrument-specific historical bars.

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

### Runtime evidence — nsemine 2.2.1 initial 5-minute probe

The first bounded runtime probe used **BAJAJ-AUTO** and required exact instrument identity before
historical retrieval was allowed.

The public call was:

```python
get_stock_historical_data(
    "BAJAJ-AUTO",
    datetime(2026, 10, 9, 9, 15, tzinfo=ZoneInfo("Asia/Kolkata")),
    datetime(2026, 10, 9, 15, 30, tzinfo=ZoneInfo("Asia/Kolkata")),
    interval=5,
    raw=False,
)
```

The resolved provider identity was:

```text
symbol:         BAJAJ-AUTO-EQ
scripcode:      16669
type:           Equity
exchange:       NSE
description:    BAJAJ AUTO LIMITED
fullname:       NSE:BAJAJ-AUTO-EQ
instrumentType: 1
```

The historical request used:

```text
GET https://charting.nseindia.com/v1/charts/symbolHistoricalData
```

with parameters:

```json
{
  "chartType": "I",
  "fromDate": 1791537300,
  "symbol": "BAJAJ-AUTO",
  "symbolType": "Equity",
  "timeInterval": 5,
  "toDate": 1791559800,
  "token": "16669"
}
```

Both the symbol lookup and historical request returned HTTP 200 with provider `status=true`.
The raw and processed historical counts were both **75 rows**.

The returned schema was:

```text
datetime, open, high, low, close, volume
```

with `datetime64[us]` naive datetimes, integer OHLCV columns and a `RangeIndex`.

Representative processed rows included:

```text
09:15  O=9662 H=9706 L=9645 C=9663 V=7909
09:20  O=9662 H=9670 L=9654 C=9658 V=3595
09:25  O=9658 H=9715 L=9654 C=9690 V=5080
...
15:10  O=9815 H=9823 L=9801 C=9803 V=6426
15:11  O=9820 H=9820 L=9820 C=9820 V=8
15:20  O=9820 H=9820 L=9820 C=9820 V=821
15:25  O=9820 H=9820 L=9778 C=9778 V=245658
```

The 75-row count is consistent with a complete 375-minute regular NSE session at five-minute
resolution, but the processed timestamp **15:11** is off the expected five-minute grid. Retrieval
success therefore does not establish timestamp correctness or bar-label semantics.

Source inspection also established that nsemine 2.2.1:

- resolves symbols through `symbolsDynamic`, strips the final hyphen suffix and attempts exact
  matching before fallback behaviour;
- adds 19,800 seconds (+05:30) to intraday input epochs;
- filters returned timestamps to regular-session clock times;
- subtracts 299 seconds for five-minute bars and rounds to minute boundaries;
- returns naive datetimes;
- drops duplicate datetime values internally and resets the index.

### Final nsemine assessment

nsemine 2.2.1 is **RETAIN_AS_FALLBACK** for DATA-001. It passed the identity/retrieval gate that
OpenChart failed and produced the strongest intraday data-quality evidence of the tested candidates.

A focused raw-to-processed reconciliation established the cause of the off-grid 15:11 label.

For the same BAJAJ-AUTO 5-minute session:

- raw rows: **75**;
- processed rows before/after deduplication: **75 / 75**;
- duplicate raw timestamps: **0**;
- duplicate processed timestamps before/after deduplication: **0 / 0**.

Around the anomalous interval, raw provider timestamps (interpreted mechanically as Unix
milliseconds for inspection only) mapped as follows:

| Raw timestamp (ms) | UTC rendering | Asia/Kolkata rendering | Processed label | OHLCV |
| --- | --- | --- | --- | --- |
| 1791558597000 | 15:09:57 | 20:39:57 | 15:05 | 9823 / 9827 / 9799 / 9817 / 7276 |
| 1791558897000 | 15:14:57 | 20:44:57 | 15:10 | 9815 / 9823 / 9801 / 9803 / 6426 |
| **1791558910000** | **15:15:10** | **20:45:10** | **15:11** | **9820 / 9820 / 9820 / 9820 / 8** |
| 1791559496000 | 15:24:56 | 20:54:56 | 15:20 | 9820 / 9820 / 9820 / 9820 / 821 |
| 1791559783000 | 15:29:43 | 20:59:43 | 15:25 | 9820 / 9820 / 9778 / 9778 / 245658 |

These UTC/Asia-Kolkata renderings do **not** establish the provider's intended timezone
convention; they are only mechanical interpretations of the raw integer timestamps.

For the anomalous raw value, nsemine's installed transformation is:

```text
1791558910000 - 299000 = 1791558611000
naive datetime conversion -> 2026-10-09 15:10:11
seconds 11 > 1:
  truncate seconds -> 15:10:00
  add one minute   -> 15:11:00
```

The raw value itself is already irregular relative to neighbouring five-minute endpoint patterns:
it is only 13 seconds after the preceding raw row. nsemine's fixed `-299 seconds` adjustment and
rounding then converts that irregular raw timestamp into the specific off-grid `15:11` label.

Session filtering retained the row. Duplicate handling removed nothing and did not contribute to
the anomaly. On the expected 15:05 / 15:10 / 15:15 / 15:20 / 15:25 grid, the processed output has
one missing expected label (**15:15**) and one off-grid label (**15:11**).

This establishes that nsemine's processed labels cannot be accepted as canonical bar timestamps
without an independent timestamp interpretation/canonicalisation rule.

### Runtime evidence — nsemine 2.2.1 one-minute probe

The same BAJAJ-AUTO session was then requested at one-minute resolution using the exact same
instrument identity and date range:

```python
get_stock_historical_data(
    "BAJAJ-AUTO",
    datetime(2026, 10, 9, 9, 15, tzinfo=ZoneInfo("Asia/Kolkata")),
    datetime(2026, 10, 9, 15, 30, tzinfo=ZoneInfo("Asia/Kolkata")),
    interval=1,
    raw=False,
)
```

The provider again resolved exactly to `BAJAJ-AUTO-EQ / 16669 / Equity / NSE`. The historical
request returned HTTP 200 with provider `status=true`.

Observed one-minute quality:

| Check | Result |
| --- | --- |
| Expected regular-session minute slots | 375 |
| Raw rows | 368 |
| Processed rows before / after deduplication | 368 / 368 |
| Duplicate raw timestamps | 0 |
| Duplicate processed timestamps before / after deduplication | 0 / 0 |
| Processed ordering | Monotonic |
| Off-grid processed timestamps | None |
| OHLC invariant violations, raw / processed | 0 / 0 |
| Negative-volume rows, raw / processed | 0 / 0 |

The processed one-minute labels were regular for all returned rows, but seven expected session
labels were absent:

```text
15:16, 15:17, 15:18, 15:19, 15:26, 15:27, 15:28
```

No missing bars were synthesized.

The previously anomalous 5-minute raw row had an exact one-minute counterpart:

```text
raw timestamp: 1791558910000
processed 1m label: 15:15
OHLCV: 9820 / 9820 / 9820 / 9820 / 8
```

At five-minute resolution, the same raw timestamp and identical OHLCV had been transformed by
nsemine into the off-grid label `15:11`. At one-minute resolution, nsemine labels the same raw row
`15:15`.

This is strong evidence that the nsemine transformation itself is interval-dependent and that its
processed five-minute timestamps cannot be treated as authoritative even when the underlying raw
row is the same.

The 1-minute series is materially more regular than the processed 5-minute series, but the seven
missing expected one-minute labels mean it cannot yet be described as complete. It remains unknown
whether those absent slots represent genuine no-trade/no-update intervals in the provider source or
missing provider data.

### Runtime evidence — deterministic one-minute to five-minute reconciliation

No new provider requests were made. The previously captured BAJAJ-AUTO one-minute and five-minute
datasets for 2026-10-09 were reconciled by fixed five-minute session buckets anchored at
09:15, 09:20, 09:25, ..., 15:25.

Each derived bucket was classified independently as:

- **COMPLETE** when all five expected one-minute labels were present;
- **INCOMPLETE** otherwise.

No missing one-minute bars were synthesized.

Provider five-minute rows were associated to intended session buckets using an explicit
interpretation rule: mechanically decode each raw provider five-minute timestamp and floor the
resulting clock time to its containing five-minute session bucket. Original provider/nsemine
processed labels were preserved unchanged. This matching rule is evidence-processing only and
does **not** establish the provider's intended timezone or bar-label semantics.

Summary:

| Measure | Count |
| --- | ---: |
| Expected five-minute buckets | 75 |
| COMPLETE derived buckets | 73 |
| INCOMPLETE derived buckets | 2 |
| Exact OHLCV matches among COMPLETE buckets | 73 |
| OHLC mismatches among COMPLETE buckets | 0 |
| Volume mismatches among COMPLETE buckets | 0 |
| Unmatched/ambiguous provider rows under the stated rule | 0 |
| Canonical buckets without a provider counterpart | 0 |
| Provider processed labels differing from assigned bucket | 1 |

Therefore **all 73 COMPLETE buckets reproduced provider OHLCV exactly** from the observed
one-minute rows.

The two incomplete late-session buckets were:

| Canonical bucket | Observed minute labels | Quality | Derived OHLCV | Provider processed label | Provider OHLCV |
| --- | --- | --- | --- | --- | --- |
| 15:15 | 15:15 only | INCOMPLETE | 9820 / 9820 / 9820 / 9820 / 8 | 15:11 | identical |
| 15:25 | 15:25, 15:29 | INCOMPLETE | 9820 / 9820 / 9778 / 9778 / 245658 | 15:25 | identical |

The seven missing one-minute labels account for exactly those two incomplete buckets:

- 15:15 bucket: missing 15:16–15:19;
- 15:25 bucket: missing 15:26–15:28.

The numerical equality of those incomplete aggregates with provider five-minute OHLCV is
consistent with the missing minute slots containing no additional provider-recorded activity, but
it does **not** prove complete underlying minute coverage. SignalForge must continue to distinguish
grid completeness from numerical OHLCV equality.

The previously anomalous raw timestamp `1791558910000` maps by the stated reconciliation rule to
the canonical 15:15 session bucket. Its original nsemine processed five-minute label remains
`15:11`. No relabeling or repair was performed in the evidence.

This result materially strengthens the case for using provider one-minute bars as the historical
acquisition layer and deriving SignalForge-owned deterministic five-minute candles, rather than
trusting nsemine's transformed five-minute labels directly. That remains a follow-up architecture
decision; SF-075 itself does not change replay or strategy semantics.

### Runtime evidence — repeatability attempt

A bounded repeatability test was attempted using two fresh, identical nsemine 2.2.1 acquisitions
for BAJAJ-AUTO on 2026-10-09, 09:15–15:30 Asia/Kolkata, interval 1 minute.

Both acquisitions failed before symbol resolution or historical retrieval while establishing the NSE
session. The observed error was a TLS connection closure (`curl` error 35).

A second fresh repeatability run reproduced the same failure mode on both attempts. The failing
request was nsemine's session-bootstrap request to:

```text
https://www.nseindia.com/get-quote/equity/RELIANCE/Reliance-Industries-Limited
```

This bootstrap URL is library infrastructure used to establish the NSE session; it is not a
historical request for RELIANCE and does not indicate instrument substitution in the BAJAJ-AUTO
historical path.

A focused client-stack diagnosis then compared three one-shot requests to the same bootstrap URL:

| Client | Result |
| --- | --- |
| `curl_cffi` using nsemine-equivalent configuration | TLS failure: curl (35), BoringSSL connection closed abruptly |
| Python `requests` with browser-like User-Agent | HTTP 200 |
| command-line `curl` with browser-like User-Agent | HTTP 200, certificate verified |

Installed runtime details for the failing path:

- nsemine 2.2.1;
- `curl_cffi` 0.16.3;
- libcurl 8.21.0-IMPERSONATE;
- BoringSSL;
- Chrome 133a impersonation;
- HTTP/1.1;
- 15-second timeout;
- cookie state cleared before bootstrap and repopulated from the response;
- no certificate-verification override observed.

Control paths used `requests` 2.34.2 / urllib3 2.8.0 / OpenSSL 3.0.13 and command-line
curl 8.5.0 / OpenSSL 3.0.13.

This strongly indicates that the observed bootstrap failure is specific to the nsemine-equivalent
`curl_cffi`/BoringSSL client path or its network/TLS fingerprint rather than an environment-wide
DNS/TCP/TLS outage. The precise root cause remains unresolved because the clients differ in TLS
stack/fingerprint and may reach different resolved IP addresses.

HTTP 200 from the control clients proves endpoint reachability but does not by itself prove that
the returned cookie/session state would be sufficient for nsemine's subsequent API calls.

For both attempts:

- no provider identity was resolved;
- no historical request was sent;
- no HTTP/provider historical status was available;
- no raw or processed market rows were acquired;
- no content digests could be generated;
- logical equality could not be assessed.

This is a transport/session-establishment failure, not an empty-market-data result and not evidence
of differing historical content. Two scoped repeatability runs have now reproduced the same bootstrap
TLS failure before any historical request. Repeatability therefore remains **INCONCLUSIVE** rather
than failed, while transport reliability itself is now an observed operational risk. The risk is specifically associated with the current nsemine-equivalent curl_cffi/BoringSSL path in the tested environment and is not confined to the initial bootstrap host.

The planned canonical comparison format is deterministic SHA-256 over compact UTF-8 JSON arrays of
`[timestamp, open, high, low, close, volume]`, preserving returned row order. That comparison can
be reused when two successful acquisitions are available.

### Runtime evidence — requests bootstrap cookie handoff probe

A minimal workaround probe tested whether Python `requests` could establish the NSE bootstrap
session and transfer its cookies into the nsemine-equivalent `curl_cffi` flow.

The bootstrap request succeeded with HTTP 200 and returned cookie names:

- `browse-url`;
- `_abck`;
- `bm_sz`.

Cookie values were not logged or persisted. Source inspection confirmed that nsemine transfers
bootstrap cookies as a simple name/value dictionary using `session.cookies.update(...)`; the probe
reproduced that behavior in memory.

The subsequent symbol-resolution request attempted:

```text
GET https://charting.nseindia.com/v1/exchanges/symbolsDynamic
params: {"segment":"","symbol":"BAJAJ-AUTO"}
```

using the nsemine-equivalent Chrome 133a / HTTP/1.1 `curl_cffi` session.

That request failed before any HTTP response with:

```text
curl (35): BoringSSL SSL_connect: Connection closed abruptly
(SSL_ERROR_SYSCALL) connecting to charting.nseindia.com:443
```

Therefore:

- requests-bootstrap cookie acquisition succeeded;
- cookie handoff into `curl_cffi` succeeded mechanically;
- exact BAJAJ-AUTO provider identity was not resolved;
- no historical request was sent;
- no authorization/session rejection was observed;
- viability for retention testing was not established.

This demonstrates that the current problem is broader than nsemine's bootstrap call itself: the
nsemine-equivalent `curl_cffi`/BoringSSL path also fails TLS negotiation against
`charting.nseindia.com` in the tested environment. A bootstrap-only transport substitution is
therefore insufficient.

### Runtime evidence — retention-depth attempt

A bounded retention-depth probe was started with the already proven 2026-10-09 BAJAJ-AUTO
one-minute session as the control, followed by progressively older dates.

The control attempt failed during nsemine's NSE session bootstrap before instrument resolution or
historical retrieval:

```text
SSLError, curl (35): BoringSSL SSL_connect:
Connection closed abruptly (SSL_ERROR_SYSCALL)
connecting to www.nseindia.com:443
```

Per the scoped stopping rule, no retries were made and no older dates were attempted.

| Date | Classification |
| --- | --- |
| 2026-10-09 | TRANSPORT_BLOCKED |
| 2026-09-11 | Not attempted |
| 2026-07-10 | Not attempted |
| 2026-04-10 | Not attempted |
| 2026-01-09 | Not attempted |
| 2025-10-10 | Not attempted |

Therefore:

- oldest date proven available **in this probe**: none;
- prior scoped availability evidence remains 2026-10-09;
- no provider-level unavailable date was observed;
- no retention boundary can be inferred;
- retention classification is **RETENTION_INCONCLUSIVE_DUE_TO_TRANSPORT**.

This is not evidence that older data is unavailable. It is evidence that the current released
nsemine transport path is not reliable enough in the tested environment to measure retention
consistently.

Pending work still includes:

- successful repeat acquisition equality;
- retention/window depth, if transport reliability is restored;
- broader duplicate/missing interval analysis across additional sessions;
- provider timezone/bar-label semantics.

No production adapter or replay-semantic change is justified yet.

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

## Final recommendation

Do not implement a production adapter from any of the tested libraries yet.

The final DATA-001 classification is:

- **nsepython 2.101 — REJECT.** Bounded BAJAJ-AUTO daily history works through the active `historicalOR` endpoint, but no 1-minute or 5-minute historical cash-equity path was found in installed source. It therefore fails the mandatory intraday requirement.
- **OpenChart 0.2.0 — REJECT.** Direct historical requests returned empty data, and the public high-level equity path failed exact instrument resolution by substituting NIFTY 50 for BAJAJ-AUTO. That violates SignalForge identity/auditability requirements.
- **nsemine 2.2.1 — RETAIN_AS_FALLBACK.** Exact BAJAJ-AUTO identity plus both 5-minute and 1-minute retrieval are proven. The captured 1-minute series was monotonic and on-grid for returned rows, with no duplicates, OHLC violations or negative volume. Deterministic 1-minute -> 5-minute aggregation reproduced provider OHLCV exactly for all 73 COMPLETE buckets in the tested session. However, processed 5-minute timestamps are not uniformly trustworthy, seven expected one-minute labels were absent, repeatability could not be established, and retention depth could not be measured because fresh acquisitions became blocked by repeatable `curl_cffi` / BoringSSL TLS failures. The released version is therefore not sufficiently reproducible to SELECT.
- **ReplaySource:** no change in SF-075.
- **Strategy V1:** no change.
- **Execution semantics:** no change.

If OpenChart or nsemine proves adequate, DATA-001 should then recommend the smallest follow-up
engineering item for a canonical historical OHLCV research-source boundary and immutable dataset
format. That follow-up must not fabricate event chronology.


## DATA-001 closure decision

DATA-001 closes under **exit condition B**.

The tested free sources do not currently provide one path that is both:

- demonstrably suitable for NSE intraday research at the required 1-minute / 5-minute granularity; and
- sufficiently reproducible and operationally reliable for SignalForge to adopt as the canonical acquisition source.

No source is selected.

nsemine 2.2.1 is retained as a fallback because the captured market-data evidence is materially
better than the other candidates and supports a plausible future path if its transport reliability
is remediated. That remediation is tracked separately in **#188 / DATA-002** and does not change
the DATA-001 verdict retroactively.

For captured nsemine datasets, the evidence supports candle/indicator/signal validation and
provider-bar reconciliation on the persisted data. It does **not** establish unambiguous
intra-minute execution chronology, and no OHLCV source may be expanded into fabricated
`MarketEvent` sequences.

The smallest next research-data item is to define the provider-neutral canonical historical OHLCV
boundary, timestamp/missing-bar quality contract, provenance manifest and immutable dataset format.
That work should remain independent of any one acquisition library and must not implement a new
execution model implicitly.

## References

- SF-075 / DATA-001: https://github.com/harishkamathuk/signalforge/issues/186
- DATA-002 / nsemine transport remediation: https://github.com/harishkamathuk/signalforge/issues/188
- DATA-003 / canonical historical OHLCV dataset and bar boundary: https://github.com/harishkamathuk/signalforge/issues/189
- nsepython: https://github.com/aeron7/nsepython
- nsepython historical-equity endpoint issue: https://github.com/aeron7/nsepython/issues/74
- OpenChart: https://github.com/marketcalls/openchart
- nsemine: https://github.com/kbizme/nsemine

## Completion status

SF-075 / DATA-001 is **complete**.

Final classifications:

- nsepython 2.101 — **REJECT**;
- OpenChart 0.2.0 — **REJECT**;
- nsemine 2.2.1 — **RETAIN_AS_FALLBACK**;
- SELECT — **none**.

The tested free-source set is inadequate for the required reproducible canonical intraday
acquisition path in its current observed form. DATA-002 (#188) tracks possible nsemine transport remediation. DATA-003 (#189) defines the provider-neutral canonical historical-bar/dataset contract without changing strategy or replay semantics.
