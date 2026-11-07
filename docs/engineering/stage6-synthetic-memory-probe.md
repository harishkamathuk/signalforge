# Stage 6 — synthetic-only memory and result-size probe (SF-266)

**Preparation only. Gate D remains withheld.** The probe is a computational
sizing instrument, **not** a protected historical scenario-performance experiment
or acceptance gate. See [Child D #260](https://github.com/harishkamathuk/signalforge/issues/260),
[owner solo-developer protocol](https://github.com/harishkamathuk/signalforge/issues/253#issuecomment-6711344205),
and [Stage 6 custody](stage6-result-custody.md).

The earlier workstation check found ~4.74 GiB WSL available memory against
an *arbitrary*, not experimentally established 6 GiB threshold. Windows has
16 GB physical RAM, but WSL 2's default ceiling is about half. Neither number
is a measured memory requirement of the frozen scenario code. Changing the
threshold or WSL allocation without sizing evidence is not justified.

## Operator command (from clean local `develop`)

```bash
cd ~/dev/signalforge
python scripts/stage6_synthetic_memory_probe.py
```

This script reads **no historical archive**, private manifest, provider data or
protected IS/OOS scenario result. No further Python-path setup is required.
It emits JSON to the terminal, with no protected prices or trade statistics.
Use the default 5,000/20,000 evidence-record samples and **2 GiB hard virtual
address-space limit per isolated worker** initially. The workers write only a
fabricated, temporary canonical JSON sample to the OS temporary directory; it
is deleted on exit. They never invoke
`ScenarioResearchRunner.run` or `run_verified`.

If the process fails with `BLOCKED_SYNTHETIC_MEMORY_PROBE`, preserve the error
and do **not** remove the hard memory cap just to make the report green. If
an environment's virtual memory reservation exceeds 2 GiB despite small RSS,
a separately reviewed limit up to 4 GiB is supported, but isn't a proof of
sufficient RAM.

## What is actually measured

Each sample builds fake values with the **actual** accepted immutable Python
`HistoricalBar`, `CompletedCandle`, `ScenarioTrace`, `ScenarioOutcome`,
`ScenarioBlockedDecision`, `ScenarioExecutionManifest` and
`ScenarioResearchResult` classes, uses two separately constructed result objects,
performs the approved result-ID and mapping comparison, and calls the real
`write_new` canonical JSON writer. It records the Linux process peak resident
memory (`ru_maxrss`), the one-result JSON file size and elapsed time.
A child process is used for **each** small/large trace-heavy and blocked-heavy
measurement to isolate Python allocator high-water state. This approximates
**one** `run_verified` call's two internal replay results; the approved later
sequence requires two distinct process-isolated invocations per RAW profile.

The projection extrapolates the *difference between two measured points* to
the frozen `max_trace_records=2,096,640` inclusive evidence budget, and scales
the synthetic source bars, five-minute candles and outcomes proportionally up to
`525,600`, `105,120`, `104,833`, respectively. `max_bars=524,160`,
`max_events=2,096,640`, and `max_states=1` are displayed unchanged.
`max_trace_records` includes blocked-decision evidence, so the probe separately
measures all-trace and all-blocked collections and reports the larger projection.

The report provides a heuristic **1×, 1.5× and 2×** RSS projection and a
four-output disk projection (two independent attempts for two profiles, excluding
backups). The multipliers are **not statistical confidence intervals or safe
upper bounds**. Real indicator-state allocations, historical source-loader
intermediates, validator work, Python allocator non-linearity, exception paths,
run-time WSL/Windows pressure and worst-case transient results are not fully
modeled. Linear extrapolation from 20k to 2.1m objects is significant.

A projection below currently available RAM does **not** certify that protected
scenario execution is feasible. A projection above available RAM is a reason to
consider more conservative proof, WSL memory settings or a machine with greater
headroom **before** asking for Gate D; it is not a witnessed OOM event.

## Test-only verification

```bash
python -m pytest -q tests/unit/test_stage6_synthetic_memory_probe.py
```

The tests exercise frozen caps, count ratios, projection sanity/fail-closed
behavior, forbidden runner calls, bounded virtual memory and **actual small
synthetic** domain-result serialization. They do not generate trading results.

**Gate D remains `GATE_D_WITHHELD` regardless of the probe's findings.** Retain
the sanitized output in #260 for evidence/review and separately address private
backup, custody attestation and owner OOS-risk acceptance.
