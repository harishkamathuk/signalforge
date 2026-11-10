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
**SF-272 adds an optional post-run test of the actual canonical result writer**, so
the resource measurement can include resident synthetic results, nested mapping,
result-ID calculation, JSON encoding and file output. The old default remains
memory-only and creates no result file.

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
No provider requests, persistent result files or protected archive accesses occur.
Only the optional SF-272 writer creates an ephemeral private canonical synthetic
file, disposed of by the parent after measurement.
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

### SF-272: bounded full-result serialization (opt-in)

For the current **synthetic-only** full-window test on the operator's WSL
checkout of the reviewed feature branch, opt into the real immutable writer:

```bash
python scripts/stage6_synthetic_full_window_probe.py \
  --serialize-result --mode both --max-rss-gib 3 \
  --vm-limit-gib 4 --max-output-mib 512 --min-free-gib 0.75
```

**Do not run this full-window optional phase in CI** or with protected data.
Start on a host with adequate Windows/WSL headroom and scratch storage. The
parent requires available Linux RAM >= **3.75 GiB** (3 GiB observed RSS guard
plus 0.75 GiB reserve) and scratch free bytes >= **768 MiB** (512 MiB maximum
file plus 256 MiB reserve) before starting the worker. A child-side
`RLIMIT_AS=4 GiB`, CPU/wall limits and `RLIMIT_FSIZE=512 MiB` also apply.
Do not increase limits to force a pass; a safety stop or output-cap failure is
a feasibility finding, **not** a reason to loosen frozen research budgets.

The `--serialize-result` switch uses the **unchanged**
`ScenarioResearchResult.write_new()` path *after* the two internal
`run_verified()` traversals. The complete synthetic result, generated source
and runner remain resident during the write. The parent creates a private
0700 direct child of the system temp directory; the child verifies it is
empty, private, outside **any** Git checkout/worktree (including another
repository's `.git` ancestor) and protected paths. Writes use a 0077 umask.
The parent hands the worker an inherited one-use pipe token and checks a
matching live parent PID, so running hidden worker options directly cannot
authorize a persistent write or bypass parent resource monitoring. The parent
handles catchable SIGTERM by stopping/waiting for the worker, then removing the
entire scratch directory (including partial output). A parent **SIGKILL**, host
power loss or process-group termination cannot guarantee cleanup; any orphan
must be quarantined/removed manually without treating it as research evidence.
There is **no intentionally persistent result artifact**, no selectable source
or destination path and no OOS release.

The sanitized JSON reports per synthetic mode:
`peak_rss_bytes_before_write`, `peak_rss_bytes` after writing, parent
observed RSS, `serialization.status`, canonical output `bytes` and SHA-256
and write elapsed seconds. It never contains the result mapping, individual
outcomes, economics or file content. An output-size bound or memory/safety
stop **fails closed**, with an explicit status; no partial output is deemed
complete. The calculated digest identifies only **ephemeral fabricated
data**, not the SF-088 source or any protected experiment.

For a small synthetic smoke before attempting a complete year:

```bash
python scripts/stage6_synthetic_full_window_probe.py \
  --minutes 1300 --mode both --serialize-result --max-output-mib 64 \
  --max-rss-gib 1 --vm-limit-gib 2 --timeout-seconds 120
```

Retain **only the sanitized stdout JSON** on #260, including failed resource
observations, exact checkout SHA and runner-file SHA, counts, RSS, write duration,
output bytes/hash, and safety status. An observed 3 GiB ceiling near the
reported **2.826 GiB scheduled pre-write peak** leaves a narrow margin and
serialization may be stopped. Even a successful fabricated-data run does
not establish a statistical worst-case upper bound for protected history
or grant Gate D. A failed case should be routed to 02/04 for mitigation
or explicit risk disposition without modifying frozen execution semantics.

### Safety boundaries

The default command starts only when Linux `MemAvailable` is at least **3.75 GiB**
(3 GiB child RSS ceiling plus 0.75 GiB reserve). Its process monitor kills the
child at **3 GiB observed RSS** or if available RAM falls below the reserve;
child address space is additionally capped at **4 GiB** using `RLIMIT_AS`,
CPU time capped at 1,200 seconds and wall time at 1,200 seconds. Linux RSS sampling
is not instantaneous, so this is a reasonable fail-closed limit rather than a
hard absolute guarantee against any transient memory spike. The child normally sets a
1 MiB file-size limit; only opt-in SF-272 serialization raises that bounded
child limit to the explicitly declared output cap. A Python audit hook
rejects protected/private-path opens and network connections. Run while Windows has adequate headroom, without
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
