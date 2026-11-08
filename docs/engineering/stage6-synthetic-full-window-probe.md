# Stage 6 — full-window synthetic runner capacity probe (SF-268)

**Preparation-only.** This tool exercises the actual frozen
`ScenarioResearchRunner.run_verified` path using only generated, fictional
one-minute OHLCV. It does not read `.signalforge-data`, the private SF-088
archive or any historical evidence; it does not provide strategy performance,
Gate D approval or PAPER/live permission.

The preceding SF-266 / PR #267 object sizing projected up to 7.855 GiB process
RSS at frozen maximum evidence records from 5k/20k synthetic samples. That was
**not an actual-runner measurement** and not proof of a real memory requirement.
This probe asks the narrower question: can a **complete year-length** synthetic
source pass through the unchanged runner within the declared WSL resource guard?

## Operator WSL command

After the PR has completed review, the exact reviewed feature branch may be
checked out temporarily while `develop` remains the protected baseline:

```bash
cd ~/dev/signalforge
(
  set -e
  git diff --quiet
  git diff --cached --quiet
  git fetch origin feat/sf-268-synthetic-runner-capacity
  git switch --detach FETCH_HEAD
  trap 'git switch develop' EXIT
  python scripts/stage6_synthetic_full_window_probe.py
)
```

This defaults to two **sequential child processes** (`quiet`, `scheduled`),
full source length **525,600 one-minute bars / 105,120 five-minute bars**.
For both, the frozen `FINITE_FAIL_CLOSED` caps remain unchanged. A source period
beginning **2027-01-01 UTC** ensures these are not the protected historical dates.
The child source provider is `fixture` and all values are invented in memory.
No provider requests, on-disk result files or protected archive accesses occur.
The child pins imports to the same Git checkout containing the probe and verifies
the loaded `scenario_execution.py` path. Its sanitized report includes the actual
checkout commit SHA and runner-module file SHA-256. This prevents an unrelated
editable/site-packages installation from silently supplying the measured runner.

`quiet` uses the real, frozen BTC strategy and actual indicator calculations
on artificial low-volatility candles. `scheduled` uses a conspicuously named
**synthetic-only signal override** to stress opportunities and lifecycle
activity while retaining the real runner and original BTC entry/exit/economics.
It must **never** be interpreted as the approved strategy signal frequency or
historical profitability. Both modes call the original `run_verified` method,
which performs two complete internal traversals before returning a result.

### Safety boundaries

The default command starts only when Linux `MemAvailable` is at least **3.75 GiB**
(3 GiB child RSS ceiling plus 0.75 GiB reserve). Its process monitor kills the
child at **3 GiB observed RSS** or if available RAM falls below the reserve;
child address space is additionally capped at **4 GiB** using `RLIMIT_AS`,
CPU time capped at 1,200 seconds and wall time at 1,200 seconds. Linux RSS sampling
is not instantaneous, so this is a reasonable fail-closed limit rather than a
hard absolute guarantee against any transient memory spike. The child sets a
1 MiB file-size limit and a Python audit hook rejects protected/private-path opens
and network connections. Run while Windows has adequate headroom, without
other heavy applications. Do **not** increase caps just to obtain a PASS.

A reduced, small **synthetic CI smoke only** exercises 1,300 fabricated minutes:

```bash
python scripts/stage6_synthetic_full_window_probe.py \
  --minutes 1300 --mode both --max-rss-gib 1 --vm-limit-gib 2
```

The stdout report contains only synthetic coverage/event/evidence **counts**,
peak RSS, time, failure **category**, safety stops and execution provenance.
It never prints trading profitability, individual outcomes, signals or
protected data. `exit 2` means feasibility was not established, even if it
stopped safely; retain the sanitized JSON and error summary. Do not repeatedly
retry by loosening caps without reviewing the evidence and Windows headroom.

## Interpretation

A clean full-window synthetic completion demonstrates memory feasibility for
**those fabricated price shapes and declared memory limits**, not a proven
worst-case bound for all market histories or actual protected performance.
Different real trade/evidence counts, allocator behaviour, data loader,
Windows/WSL host pressure or an OOS custody wrapper can consume more memory.
A safety stop shows that the particular synthetic scenario exceeded a guard
or exhausted its budget; it does not prove a market study will do so.

The historical experiment still requires two **separate process-isolated**
`run_verified` invocations per RAW profile, intact complete-grid semantics,
protected-input custody, and a **separate Gate D ACCEPT** on parent #253 before
any historical IS/OOS performance execution or inspection. No strategy, runner,
result schema, budget or durable artifact contract changes in SF-268.
