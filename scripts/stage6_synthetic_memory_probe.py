"""Bounded synthetic-only Stage 6 object/serializer memory probe (SF-266).

No protected-source access, market-data acquisition, strategy execution, or
ScenarioResearchRunner method is permitted. Runs two sized payloads in separate
Linux processes and extrapolates; never certifies full-run memory feasibility.
"""

from __future__ import annotations

import argparse
import json
import math
import resource
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

SOURCE_MINUTES = 525_600
FIVE_MINUTE_CANDLES = 105_120
MAX_BARS = 524_160
MAX_EVENTS = 2_096_640
MAX_OUTCOMES = 104_833
MAX_EVIDENCE = 2_096_640
MAX_STATES = 1
MIB = 1024**2
GIB = 1024**3
WORKER_TAG = "synthetic-only-memory-sizing-v1"
# This list is a fail-closed code review tripwire against accidental runner usage.


class ProbeError(RuntimeError):
    """A synthetic measurement is unsafe, incomplete or unrepresentative."""


def sample_counts(evidence_count: int) -> dict[str, int]:
    """Scale frozen maximal object budgets proportionally for a bounded sample.

    Args:
        evidence_count: Number of trace/blocked objects per synthetic result.

    Returns:
        Sample counts for source bars, candles and outcomes.

    Raises:
        ProbeError: If the sample is outside the frozen evidence bound.
    """
    if type(evidence_count) is not int or not 0 < evidence_count <= MAX_EVIDENCE:
        raise ProbeError("synthetic sample evidence count must be positive and bounded")
    return {
        "source_bars": max(5, math.ceil(evidence_count * SOURCE_MINUTES / MAX_EVIDENCE)),
        "five_minute_candles": max(
            1, math.ceil(evidence_count * FIVE_MINUTE_CANDLES / MAX_EVIDENCE)
        ),
        "outcomes": max(1, math.ceil(evidence_count * MAX_OUTCOMES / MAX_EVIDENCE)),
    }


def extrapolate(small: dict[str, object], large: dict[str, object]) -> dict[str, object]:
    """Linearly extrapolate the *measured* process high-water RSS and output size.

    Notes:
        This is a projection based on two measured points, NOT an upper bound:
        allocator non-linearity, indicator state, source validation, work-list
        reallocations, WSL/Windows pressure and platform changes are excluded.
    """
    a, b = int(small["evidence_count"]), int(large["evidence_count"])
    if not 0 < a < b <= MAX_EVIDENCE:
        raise ProbeError("sample sizes must increase within frozen evidence cap")
    if small["mode"] != large["mode"]:
        raise ProbeError("cannot combine unlike synthetic evidence modes")
    peak_a, peak_b = int(small["peak_rss_bytes"]), int(large["peak_rss_bytes"])
    output_a, output_b = int(small["output_bytes"]), int(large["output_bytes"])
    if peak_a <= 0 or peak_b <= peak_a or output_a <= 0 or output_b <= output_a:
        raise ProbeError("unstable/nonincreasing RSS or output: no safe projection")
    slope_rss = (peak_b - peak_a) / (b - a)
    slope_output = (output_b - output_a) / (b - a)
    rss_full = math.ceil(peak_b + (MAX_EVIDENCE - b) * slope_rss)
    output_full = math.ceil(output_b + (MAX_EVIDENCE - b) * slope_output)
    return {
        "mode": small["mode"],
        "peak_rss_small_bytes": peak_a,
        "peak_rss_large_bytes": peak_b,
        "rss_projected_full_evidence_bytes": rss_full,
        "rss_projected_full_evidence_gib": round(rss_full / GIB, 3),
        "rss_projected_with_1_5x_margin_gib": round(rss_full * 1.5 / GIB, 3),
        "rss_projected_with_2x_margin_gib": round(rss_full * 2 / GIB, 3),
        "canonical_json_projected_bytes_per_result": output_full,
        "canonical_json_projected_mib_per_result": round(output_full / MIB, 2),
        "two_profiles_two_attempts_disk_gib_before_backups": round(4 * output_full / GIB, 3),
        "projection_warning": "not a statistical upper bound or runnable-history guarantee",
    }


def linux_available_memory() -> int | None:
    """Read the current Linux MemAvailable value without accessing market data."""
    meminfo = Path("/proc/meminfo")
    if not meminfo.is_file():
        return None
    for line in meminfo.read_text(encoding="utf-8").splitlines():
        if line.startswith("MemAvailable:"):
            return int(line.split()[1]) * 1024
    return None


def _sample_worker(mode: str, evidence: int, vm_limit_gib: int) -> dict[str, object]:
    """Build fake domain objects and serialize two replay-like results in a child.

    This deliberately never constructs a real historical dataset or calls any
    strategy/runner. Its only input is a count and a synthetic representation.
    """
    if mode not in ("trace", "blocked"):
        raise ProbeError("invalid synthetic evidence mode")
    if not 0 < evidence <= 50_000:
        raise ProbeError("synthetic worker sample exceeds the 50k hard cap")
    if not 1 <= vm_limit_gib <= 4:
        raise ProbeError("invalid bounded child virtual memory cap")
    # Apply before importing the project: oversized synthetic workloads should
    # terminate with a clear failure rather than exhausting the WSL host.
    resource.setrlimit(resource.RLIMIT_AS, (vm_limit_gib * GIB, vm_limit_gib * GIB))
    from signalforge.domain.ids import InstrumentId
    from signalforge.domain.market import CandleQuality, CompletedCandle
    from signalforge.domain.money import Price
    from signalforge.domain.time import CandleInterval
    from signalforge.research.historical_bars import HistoricalBar
    from signalforge.research.scenario_execution import (
        ScenarioBlockedDecision,
        ScenarioExecutionManifest,
        ScenarioMethodStatus,
        ScenarioOutcome,
        ScenarioResearchResult,
        ScenarioTrace,
    )

    started = time.monotonic()
    count = sample_counts(evidence)
    minute = timedelta(minutes=1)
    five_minutes = timedelta(minutes=5)
    start = datetime(2026, 1, 1, tzinfo=UTC)
    instrument = InstrumentId("SYNTHETIC:MEMORY_ONLY")
    base_decimal = Decimal("50000.01")

    bars: list[HistoricalBar] = []
    for i in range(count["source_bars"]):
        t = start + i * minute
        p = base_decimal + Decimal(i % 77) / Decimal(100)
        bars.append(
            HistoricalBar(
                instrument_id=instrument,
                interval=CandleInterval(t, t + minute),
                open=Price(p), high=Price(p + Decimal("2.1")),
                low=Price(p - Decimal("2.1")), close=Price(p + Decimal("0.03")),
                volume=i % 100 + 1, quality=CandleQuality.VALID,
                source_provider="synthetic-only", source_record_count=1,
                provider_timestamp_raw=f"synthetic-{i:08d}",
                provider_timestamp_interpreted=t,
                canonicalisation_version="synthetic-memory-v1",
            )
        )
    bar_tuple = tuple(bars)
    candles: list[CompletedCandle] = []
    for i in range(count["five_minute_candles"]):
        bar = bar_tuple[(i * 5) % len(bar_tuple)]
        t = start + i * five_minutes
        candles.append(
            CompletedCandle(
                instrument_id=instrument,
                interval=CandleInterval(t, t + five_minutes),
                quality=CandleQuality.VALID, open=bar.open,
                high=Price(bar.high.value + Decimal("1")),
                low=Price(bar.low.value - Decimal("1")), close=bar.close,
                volume=5, source="synthetic-memory-5m", source_event_count=5,
            )
        )
    candle_tuple = tuple(candles)
    candles_by_end = {c.interval.end: c for c in candles}
    manifest = ScenarioExecutionManifest({
        "source": {"source_diagnostic_id": WORKER_TAG,
                   "synthetic_fixture_identity": WORKER_TAG},
        "strategy": {"synthetic_fixture_identity": WORKER_TAG},
        "implementation": {"revision": WORKER_TAG},
    })

    def fake_result() -> ScenarioResearchResult:
        # Each call builds fresh independent object arrays like the two
        # run_verified traversals. Bars/candles are shared across those runs.
        trace: list[ScenarioTrace] = []
        blocked: list[ScenarioBlockedDecision] = []
        for i in range(evidence):
            t = bar_tuple[i % len(bar_tuple)].interval.start
            if mode == "trace":
                p = base_decimal + Decimal(i % 91) / Decimal(10)
                trace.append(ScenarioTrace(
                    t, p, p + Decimal("1.00"),
                    "ENTRY" if i % 2 else "STOP", True, p + Decimal("0.50")
                ))
            else:
                blocked.append(ScenarioBlockedDecision(
                    t, t + five_minutes, f"synthetic-{i:064x}", "OPEN"
                ))
        outcomes: list[ScenarioOutcome] = []
        for i in range(count["outcomes"]):
            t = bar_tuple[i % len(bar_tuple)].interval.start
            p = base_decimal + Decimal(i % 89) / Decimal(100)
            outcomes.append(ScenarioOutcome(
                f"synthetic-{i:064x}", "CLOSED", "TARGET", t, t + minute,
                p, p + Decimal("3.00"), Decimal("1.50"), i % 200 + 1,
            ))
        return ScenarioResearchResult(
            manifest=manifest, outcomes=tuple(outcomes), trace=tuple(trace),
            is_observed=0, oos_observed=0, unsupported=0, failure=None,
            failure_bucket=None, event_count=evidence,
            method_status=ScenarioMethodStatus.INCONCLUSIVE,
            blocked_decisions=tuple(blocked),
        )

    first = fake_result()
    second = fake_result()
    if first.result_id != second.result_id or first.mapping() != second.mapping():
        raise ProbeError("synthetic replay object serialization mismatch")
    # Same canonical serializer and exclusive result writer as the frozen code.
    with tempfile.TemporaryDirectory(prefix="sf266-synthetic-only-") as directory:
        path = Path(directory) / "synthetic-result.json"
        first.write_new(path)
        output_bytes = path.stat().st_size
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024  # Linux KiB.
    if not bar_tuple or not candle_tuple or not candles_by_end:
        raise ProbeError("source/candle fixture construction failed")
    return {
        "tag": WORKER_TAG,
        "mode": mode,
        "evidence_count": evidence,
        "source_bars_count": len(bar_tuple),
        "five_minute_candles_count": len(candle_tuple),
        "outcomes_count_each_result": count["outcomes"],
        "two_replay_results_retained": True,
        "peak_rss_bytes": peak,
        "output_bytes": output_bytes,
        "elapsed_seconds": round(time.monotonic() - started, 3),
    }


def run_probe(*, small: int, large: int, child_vm_limit_gib: int) -> dict[str, object]:
    """Collect two fresh process measurements for both evidence shapes."""
    if not 0 < small < large <= 50_000:
        raise ProbeError("samples must increase and remain <= 50000")
    if not 1 <= child_vm_limit_gib <= 4:
        raise ProbeError("child VM cap must be in [1, 4] GiB")
    measures: list[dict[str, object]] = []
    for mode in ("trace", "blocked"):
        for size in (small, large):
            # One subprocess per point prevents prior Python allocation state
            # from contaminating process high-water marks.
            cmd = [sys.executable, str(Path(__file__).resolve()), "--worker",
                   "--mode", mode, "--evidence", str(size),
                   "--child-vm-limit-gib", str(child_vm_limit_gib)]
            outcome = subprocess.run(
                cmd, capture_output=True, text=True, check=False, timeout=180,
            )
            if outcome.returncode != 0:
                raise ProbeError(
                    f"synthetic child {mode}/{size} failed (exit={outcome.returncode}): "
                    + outcome.stderr[-600:]
                )
            try:
                measure = json.loads(outcome.stdout)
            except json.JSONDecodeError as exc:
                raise ProbeError("synthetic worker produced invalid JSON") from exc
            if not isinstance(measure, dict) or measure.get("tag") != WORKER_TAG:
                raise ProbeError("synthetic-only worker attestation missing")
            if measure.get("mode") != mode or measure.get("evidence_count") != size:
                raise ProbeError("synthetic sample mismatch")
            measures.append(measure)
    projections = [extrapolate(measures[i], measures[i + 1]) for i in (0, 2)]
    worst_rss = max(p["rss_projected_full_evidence_bytes"] for p in projections)
    current_ram = linux_available_memory()
    return {
        "status": "SYNTHETIC_PROJECTION_ONLY_NOT_FULL_RUN_CERTIFIED",
        "approved_frozen_limits_unchanged": {
            "source_minutes": SOURCE_MINUTES,
            "five_minute_candles": FIVE_MINUTE_CANDLES,
            "max_bars": MAX_BARS,
            "max_events": MAX_EVENTS,
            "max_outcomes": MAX_OUTCOMES,
            "max_trace_records_including_blocked": MAX_EVIDENCE,
            "max_states": MAX_STATES,
        },
        "synthetic_only": True,
        "scenario_runner_invoked": False,
        "two_replay_results_modeled": True,
        "sample_measurements": measures,
        "linear_projections": projections,
        "worst_projection_gib": round(worst_rss / GIB, 3),
        "worst_projection_with_2x_margin_gib": round(2 * worst_rss / GIB, 3),
        "wsl_mem_available_gib_at_probe": (
            None if current_ram is None else round(current_ram / GIB, 3)
        ),
        "comparison": (
            "CURRENT_AVAILABILITY_UNKNOWN" if current_ram is None
            else "ESTIMATE_WITH_2X_MARGIN_OVER_AVAILABLE"
            if 2 * worst_rss > current_ram
            else "ESTIMATE_WITH_2X_MARGIN_BELOW_AVAILABLE_UNCERTIFIED"
        ),
        "limitations": [
            ("High-water RSS is measured for synthetic object collections, "
             "NOT the actual scenario run."),
            "Linear scaling and 1.5x/2x margins are heuristics, not safe upper bounds.",
            ("Indicator computation, full source dataset validation and "
             "transient runner state not fully modeled."),
            "Actual source data object values and Python allocator behavior may differ.",
            ("Two sequential process-isolated run_verified calls per profile "
             "remain mandatory after Gate D."),
            ("WSL memory pressure and Windows host contention can change "
             "between samples and execution."),
            "No protected historical IS/OOS performance was run or inspected.",
        ],
        "gate_d_approved": False,
    }


def main(argv: list[str] | None = None) -> int:
    """Run synthetic-only measurement or an internal, strictly bounded worker."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--small", type=int, default=5_000)
    parser.add_argument("--large", type=int, default=20_000)
    parser.add_argument("--child-vm-limit-gib", type=int, default=2)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--mode", choices=("trace", "blocked"), help=argparse.SUPPRESS)
    parser.add_argument("--evidence", type=int, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        if args.worker:
            if args.mode is None or args.evidence is None:
                raise ProbeError("internal worker requires mode/evidence")
            report = _sample_worker(args.mode, args.evidence, args.child_vm_limit_gib)
        else:
            if args.mode is not None or args.evidence is not None:
                raise ProbeError("worker-only controls not permitted in normal mode")
            report = run_probe(
                small=args.small,
                large=args.large,
                child_vm_limit_gib=args.child_vm_limit_gib,
            )
        print(json.dumps(report, sort_keys=True, indent=2))
        return 0
    except (ProbeError, OSError, subprocess.TimeoutExpired, MemoryError, ValueError) as exc:
        print(json.dumps({"status": "BLOCKED_SYNTHETIC_MEMORY_PROBE", "reason": str(exc),
                          "gate_d_approved": False}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
