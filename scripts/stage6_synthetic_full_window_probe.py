"""Guarded Stage 6 full-window *synthetic* runner-memory probe.

Only fabricated OHLCV is accepted. This is not a protected historical scenario,
a result publication path, a profitability test, or Gate D authorisation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import resource
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

FULL_MINUTES = 525_600
FROZEN_BARS = 524_160
FROZEN_EVENTS = 2_096_640
FROZEN_OUTCOMES = 104_833
FROZEN_TRACES = 2_096_640
FULL_IS_CANDLES = 69_984
FULL_OOS_CANDLES = 34_848
GIB = 1024**3
START = datetime(2027, 1, 1, tzinfo=UTC)  # NOT the frozen SF-088 source interval.
IDENTITY = "synthetic-sf268-memory-only"


class ProbeBlocked(ValueError):
    """Explicit failure to establish safe synthetic-runner feasibility."""


def _assert_synthetic_only() -> None:
    """Enforce an additional Python audit boundary around private evidence paths."""

    def audit(event: str, args: tuple[object, ...]) -> None:
        if event == "open" and args:
            value = args[0]
            if isinstance(value, (str, bytes, os.PathLike)):
                path = Path(os.fsdecode(os.fspath(value)))
                if any(part in (".signalforge-data", "signalforge-private", "sf088", "sf096")
                       for part in path.parts):
                    raise PermissionError("synthetic probe cannot open protected/private files")
        if event in ("socket.connect", "socket.connect_ex"):
            raise PermissionError("synthetic probe cannot make network connections")

    sys.addaudithook(audit)


def _available_ram() -> int:
    text = Path("/proc/meminfo").read_text(encoding="ascii")
    for line in text.splitlines():
        if line.startswith("MemAvailable:"):
            return int(line.split()[1]) * 1024
    raise ProbeBlocked("MemAvailable unavailable; Linux/WSL is required")


def _worker_rss(pid: int) -> int:
    try:
        content = Path(f"/proc/{pid}/status").read_text(encoding="ascii")
    except FileNotFoundError:
        return 0
    for line in content.splitlines():
        if line.startswith("VmRSS:"):
            return int(line.split()[1]) * 1024
    return 0


def _bind_runner_checkout() -> tuple[str, str, str]:
    """Use only the runner from this exact Git checkout, not site-packages."""
    root = Path(__file__).resolve().parents[1]
    expected = (root / "signalforge/research/scenario_execution.py").resolve()
    if not expected.is_file():
        raise ProbeBlocked("checked-out scenario runner module is missing")
    git = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True, timeout=10,
    )
    head = git.stdout.strip()
    if len(head) != 40 or any(c not in "0123456789abcdef" for c in head):
        raise ProbeBlocked("checkout revision is not a Git commit identity")
    if str(root) in sys.path:
        sys.path.remove(str(root))
    sys.path.insert(0, str(root))
    # The child has not imported any SignalForge modules before this point.
    from signalforge.research import scenario_execution as actual

    loaded = Path(actual.__file__).resolve() if actual.__file__ else None
    if loaded != expected:
        raise ProbeBlocked("imported runner is not from the checked-out source tree")
    return head, str(loaded), hashlib.sha256(expected.read_bytes()).hexdigest()


def _source(minutes: int, *, mode: str) -> Any:
    """Construct an invented chronological one-minute dataset wholly in memory."""
    from decimal import Decimal

    from signalforge.domain.ids import InstrumentId
    from signalforge.domain.market import CandleQuality
    from signalforge.domain.money import Price
    from signalforge.domain.time import CandleInterval
    from signalforge.research.btc_raw_diagnostic_input import RawDiagnosticSource
    from signalforge.research.historical_bars import (
        CorporateActionPolicy,
        HistoricalBar,
        HistoricalBarDataset,
        HistoricalDatasetManifest,
        HistoricalPriceBasis,
    )
    from signalforge.research.historical_grid import HistoricalBarGrid

    instrument = InstrumentId("DELTA:BTCUSD")  # Required synthetic request instrument shape.
    minute = timedelta(minutes=1)
    end = START + minutes * minute
    bars: list[HistoricalBar] = []
    for i in range(minutes):
        timestamp = START + i * minute
        # All price strings are invented; no real provider or historical observations.
        anchor = Decimal("100") + Decimal(i % 23) / Decimal("100")
        if mode == "scheduled":
            high, low = anchor + Decimal("10"), anchor - Decimal("10")
        else:
            high, low = anchor + Decimal("0.05"), anchor - Decimal("0.05")
        bars.append(HistoricalBar(
            instrument_id=instrument,
            interval=CandleInterval(timestamp, timestamp + minute),
            open=Price(Decimal(str(anchor))),
            high=Price(Decimal(str(high))),
            low=Price(Decimal(str(low))),
            close=Price(Decimal(str(anchor))),
            volume=100 + (i % 7), quality=CandleQuality.VALID,
            source_provider="fixture", source_record_count=1,
            provider_timestamp_raw=f"synthetic-{i:07d}",
            provider_timestamp_interpreted=timestamp,
            canonicalisation_version="synthetic-sf268-v1",
        ))
    manifest = HistoricalDatasetManifest(
        provider="fixture", acquisition_adapter="repository-fixture",
        acquisition_version="synthetic-v1", requested_instrument="BTCUSD",
        resolved_provider_instrument="SYNTHETIC-BTCUSD",
        instrument_id=instrument, requested_start=START, requested_end=end,
        returned_start=START, returned_end=end, interval_minutes=1,
        acquired_at=START, provider_timestamp_representation="synthetic-index",
        timezone_interpretation="UTC", canonicalisation_version="synthetic-sf268-v1",
        expected_session_dates=(), raw_row_count=minutes,
        canonical_row_count=minutes, missing_interval_count=0,
        duplicate_observation_count=0, corrupt_rejected_count=0,
        corporate_action_policy=CorporateActionPolicy.NOT_APPLICABLE,
        limitations=("UNQUALIFIED_HISTORICAL_METADATA", "SYNTHETIC_TEST_ONLY"),
        grid=HistoricalBarGrid(
            "scenario-synthetic", "1", (CandleInterval(START, end),)
        ),
        price_basis=HistoricalPriceBasis.TRADED, acquisition_evidence=(),
    )
    return RawDiagnosticSource(
        HistoricalBarDataset(manifest, tuple(bars)), IDENTITY,
    )


def _execute(minutes: int, *, mode: str) -> dict[str, object]:
    """Execute the unmodified runner, with no protected source or result output."""
    from signalforge.config.btc_momentum_baseline_v0 import BtcMomentumBaselineV0Config
    from signalforge.config.strategy_registry import (
        StrategyRegistration,
        StrategyRegistry,
        StrategySelection,
    )
    from signalforge.research.historical_execution import HistoricalExecutionAssumptionProfile
    from signalforge.research.scenario_execution import (
        ScenarioAssumptionSet,
        ScenarioMode,
        ScenarioResearchRequest,
        ScenarioResearchRunner,
        ScenarioResourcePolicy,
    )
    from signalforge.runtime.btc_momentum_baseline_v0 import (
        BtcMomentumBaselineDecision,
        BtcMomentumBaselineV0Strategy,
    )
    from signalforge.runtime.strategy import CompletedCandleStrategyContext

    git_head, runner_file, runner_sha256 = _bind_runner_checkout()
    source = _source(minutes, mode=mode)
    strategy_selection = StrategySelection(
        "btc_momentum_baseline_v0", "0.1.0-experimental", {}
    )
    if mode == "scheduled":
        # Only stress-mode strategy decisions are fabricated. Actual runner,
        # entry/stop/target/lifecycle implementations remain unchanged.
        class SyntheticScheduledSignals(BtcMomentumBaselineV0Strategy):
            """Synthetic frequency injection, never approved BTC signal semantics."""

            def __init__(self) -> None:
                super().__init__(BtcMomentumBaselineV0Config())

            def evaluate_completed_candle(
                self, context: CompletedCandleStrategyContext,
            ) -> BtcMomentumBaselineDecision:
                count = context.completed_regular_session_candles
                active = count >= 251 and count % 3 == 0
                return BtcMomentumBaselineDecision(
                    context.candle.instrument_id, context.candle.interval,
                    active, active,
                    ("synthetic_schedule",) if active else ("synthetic_no_signal",),
                    None,
                )

        registry = StrategyRegistry((StrategyRegistration(
            strategy_selection.strategy_id,
            strategy_selection.strategy_version,
            lambda _params: SyntheticScheduledSignals(),
        ),))
        runner = ScenarioResearchRunner(registry=registry)
    else:
        runner = ScenarioResearchRunner()  # Real frozen BTC strategy and indicators.

    warmup = 1440 if minutes == FULL_MINUTES else 1250
    is_start = START + timedelta(minutes=warmup)
    oos_start = (
        is_start + timedelta(minutes=FULL_IS_CANDLES * 5)
        if minutes == FULL_MINUTES
        else is_start + timedelta(minutes=5)
    )
    request = ScenarioResearchRequest(
        mode=ScenarioMode.SCENARIO_RESEARCH, source=source,
        strategy_selection=strategy_selection,
        engine_calculation_version="synthetic-sf268-engine-v1",
        assumptions=ScenarioAssumptionSet.btc_ohlc_path_v1(),
        profile=HistoricalExecutionAssumptionProfile.reference_raw(),
        resources=ScenarioResourcePolicy(
            "FINITE_FAIL_CLOSED", "1.0.0", FROZEN_BARS, FROZEN_EVENTS,
            FROZEN_OUTCOMES, FROZEN_TRACES, 1,
        ),
        is_start=is_start, oos_start=oos_start,
        measured_end=START + timedelta(minutes=minutes),
        repository_revision=git_head,
        synthetic_fixture_identity=f"{IDENTITY}-{mode}",
    )
    begun = time.monotonic()
    result = runner.run_verified(request)  # Actual two-pass runner; synthetic source only.
    elapsed = round(time.monotonic() - begun, 3)
    expected_is = int((oos_start - is_start) / timedelta(minutes=5))
    expected_oos = int((request.measured_end - oos_start) / timedelta(minutes=5))
    # Never report trade economics, price paths, result mappings or OOS statistics.
    return {
        "status": "SYNTHETIC_RUNNER_COMPLETED" if result.failure is None
                  else "SYNTHETIC_RUNNER_EARLY_TERMINATION",
        "synthetic_only": True,
        "actual_runner_run_verified_called": True,
        "two_internal_traversals": True,
        "strategy_mode": "frozen_btc_baseline_synthetic_ohlc" if mode == "quiet"
                         else "synthetic_scheduled_signal_override_NOT_frozen_strategy",
        "source_minutes": minutes,
        "runner_checkout_git_sha": git_head,
        "loaded_runner_file": runner_file,
        "loaded_runner_sha256": runner_sha256,
        "measured_is_candles": result.is_observed,
        "measured_oos_candles": result.oos_observed,
        "expected_is_candles": expected_is,
        "expected_oos_candles": expected_oos,
        "trace_count": len(result.trace),
        "outcome_count": len(result.outcomes),
        "blocked_count": len(result.blocked_decisions),
        "events_count": result.event_count,
        "complete_grid": (result.is_observed == expected_is
                          and result.oos_observed == expected_oos),
        "failure_category": None if result.failure is None
                            else result.failure.split(":", 1)[0],
        "elapsed_runner_seconds": elapsed,
        "peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
        "gate_d_approved": False,
        "execution_valid": False,
    }


def _child(minutes: int, *, mode: str, vm_limit_gib: int,
           cpu_limit_seconds: int) -> int:
    """Contain synthetic computation before importing any SignalForge module."""
    resource.setrlimit(resource.RLIMIT_AS, (vm_limit_gib * GIB, vm_limit_gib * GIB))
    resource.setrlimit(resource.RLIMIT_CPU, (cpu_limit_seconds, cpu_limit_seconds + 1))
    resource.setrlimit(resource.RLIMIT_FSIZE, (1024 * 1024, 1024 * 1024))
    _assert_synthetic_only()
    report = _execute(minutes, mode=mode)
    print(json.dumps(report, sort_keys=True), flush=True)
    return 0 if report["status"] == "SYNTHETIC_RUNNER_COMPLETED" else 2


def _run_one(*, minutes: int, mode: str, max_rss_gib: int,
             vm_limit_gib: int, timeout_seconds: int,
             min_free_gib: float) -> dict[str, object]:
    """Monitor and terminate one synthetic subprocess before unsafe RSS growth."""
    available = _available_ram()
    reserve = int(min_free_gib * GIB)
    if available < max_rss_gib * GIB + reserve:
        return {
            "mode": mode, "status": "BLOCKED_INSUFFICIENT_INITIAL_HEADROOM",
            "available_ram_gib": round(available / GIB, 3),
        }
    command = [sys.executable, str(Path(__file__).resolve()),
               "--child", "--minutes", str(minutes), "--mode", mode,
               "--max-rss-gib", str(max_rss_gib),
               "--vm-limit-gib", str(vm_limit_gib),
               "--timeout-seconds", str(timeout_seconds)]
    start = time.monotonic()
    proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    peak_observed = 0
    kill_reason = None
    try:
        while proc.poll() is None:
            rss = _worker_rss(proc.pid)
            peak_observed = max(peak_observed, rss)
            if rss >= max_rss_gib * GIB:
                kill_reason = "RSS_CEILING_REACHED"
            elif _available_ram() < reserve:
                kill_reason = "HOST_AVAILABLE_MEMORY_BELOW_RESERVE"
            elif time.monotonic() - start > timeout_seconds:
                kill_reason = "WALL_TIMEOUT"
            if kill_reason:
                proc.kill()
                break
            time.sleep(0.15)
        stdout, stderr = proc.communicate(timeout=5)
    except BaseException:
        proc.kill()
        proc.communicate()
        raise
    duration = round(time.monotonic() - start, 3)
    if kill_reason:
        return {"mode": mode, "status": "SAFETY_STOP", "reason": kill_reason,
                "observed_rss_mib": round(peak_observed / (1024 * 1024), 1),
                "elapsed_seconds": duration, "exit_code": proc.returncode}
    if proc.returncode != 0:
        blocked: dict[str, object] = {
            "mode": mode, "status": "WORKER_FAILED_OR_CAP_REACHED",
            "exit_code": proc.returncode,
            "observed_rss_mib": round(peak_observed / (1024 * 1024), 1),
            "elapsed_seconds": duration,
            "stderr_tail": stderr.decode("utf-8", errors="replace")[-500:],
        }
        # An early-terminated synthetic runner emits its bounded diagnostic
        # before exiting 2; preserve it instead of losing the failure category.
        try:
            child = json.loads(stdout.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            pass
        else:
            if isinstance(child, dict) and child.get("synthetic_only") is True:
                blocked["child_report"] = child
        return blocked
    try:
        payload = json.loads(stdout.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return {"mode": mode, "status": "INVALID_WORKER_REPORT"}
    if not isinstance(payload, dict) or payload.get("synthetic_only") is not True:
        return {"mode": mode, "status": "INVALID_SYNTHETIC_ATTESTATION"}
    payload["mode"] = mode
    payload["parent_observed_rss_bytes"] = peak_observed
    payload["total_process_elapsed_seconds"] = duration
    return payload


def main(argv: list[str] | None = None) -> int:
    """Run guarded synthetic-only full-window source and runner memory measurement."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--minutes", type=int, default=FULL_MINUTES)
    parser.add_argument("--mode", choices=("quiet", "scheduled", "both"), default="both")
    parser.add_argument("--max-rss-gib", type=int, choices=(1, 2, 3), default=3)
    parser.add_argument("--vm-limit-gib", type=int, choices=(2, 3, 4, 5), default=4)
    parser.add_argument("--timeout-seconds", type=int, default=1200)
    parser.add_argument("--min-free-gib", type=float, default=0.75)
    parser.add_argument("--child", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if (args.minutes < 1300 or args.minutes > FULL_MINUTES or args.minutes % 5
        or not 120 <= args.timeout_seconds <= 3600
        or not 0.5 <= args.min_free_gib <= 2.0
        or args.vm_limit_gib < args.max_rss_gib):
        parser.error("invalid bounded synthetic probe settings")
    if args.child:
        if args.mode == "both":
            parser.error("internal child requires one mode")
        try:
            return _child(args.minutes, mode=args.mode,
                          vm_limit_gib=args.vm_limit_gib,
                          cpu_limit_seconds=args.timeout_seconds)
        except (MemoryError, ValueError, OSError) as exc:
            print(json.dumps({"status": "SYNTHETIC_WORKER_BLOCKED",
                              "error_type": type(exc).__name__,
                              "reason": str(exc)[:300]}), file=sys.stderr)
            return 2
    modes = ("quiet", "scheduled") if args.mode == "both" else (args.mode,)
    results = []
    for mode in modes:
        result = _run_one(
            minutes=args.minutes, mode=mode, max_rss_gib=args.max_rss_gib,
            vm_limit_gib=args.vm_limit_gib,
            timeout_seconds=args.timeout_seconds, min_free_gib=args.min_free_gib,
        )
        results.append(result)
        if result["status"] != "SYNTHETIC_RUNNER_COMPLETED":
            break  # No further host load after a failed safety/runner condition.
    completed = all(r["status"] == "SYNTHETIC_RUNNER_COMPLETED" for r in results)
    report = {
        "status": "SYNTHETIC_RUNNER_RESOURCE_OBSERVATION_ONLY" if completed
                  else "SYNTHETIC_RUNNER_FEASIBILITY_NOT_ESTABLISHED",
        "full_window_minutes": FULL_MINUTES,
        "requested_minutes": args.minutes,
        "frozen_caps_unchanged": {"max_bars": FROZEN_BARS,
                                  "max_events": FROZEN_EVENTS,
                                  "max_outcomes": FROZEN_OUTCOMES,
                                  "max_trace_records": FROZEN_TRACES,
                                  "max_states": 1},
        "synthetic_source_interval_start": START.isoformat(),
        "synthetic_only": True, "protected_source_access": False,
        "gate_d_approved": False, "historical_performance_evaluated": False,
        "available_ram_gib_after": round(_available_ram() / GIB, 3),
        "safety_controls": {"max_rss_gib": args.max_rss_gib,
                            "virtual_memory_cap_gib": args.vm_limit_gib,
                            "minimum_available_ram_gib": args.min_free_gib,
                            "wall_timeout_seconds": args.timeout_seconds},
        "results": results,
        "limitations": [
            "Only synthetic prices; scheduled mode overrides signal decisions for stress.",
            "This measures actual runner and source construction, NOT protected BTC outcomes.",
            "RSS sampling can miss sub-150ms spikes; RLIMIT_AS is additional fail-closed cap.",
            "No full historical result disk output or protected OOS inspection.",
            "Observed success is not a formal worst-case upper memory bound.",
            "Both profiles and separate outer process-isolated repeats remain future Gate D work.",
        ],
    }
    print(json.dumps(report, sort_keys=True, indent=2))
    return 0 if completed else 2


if __name__ == "__main__":
    raise SystemExit(main())
