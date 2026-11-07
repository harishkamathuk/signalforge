"""Synthetic-only capacity safety and actual-runner smoke tests for SF-268."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/stage6_synthetic_full_window_probe.py"
SPEC = importlib.util.spec_from_file_location("sf268_memory_probe", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
probe = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = probe
SPEC.loader.exec_module(probe)


def test_frozen_limits_and_synthetic_epoch_are_not_protected_window():
    assert probe.FULL_MINUTES == 525_600
    assert probe.FROZEN_BARS == 524_160
    assert probe.FROZEN_EVENTS == 2_096_640
    assert probe.FROZEN_OUTCOMES == 104_833
    assert probe.FROZEN_TRACES == 2_096_640
    assert probe.START.isoformat().startswith("2027-")
    assert probe.IDENTITY.startswith("synthetic-")


@pytest.mark.parametrize("args", [
    ["--minutes", "1295"],
    ["--minutes", "525605"],
    ["--minutes", "1301"],
    ["--max-rss-gib", "4"],
    ["--vm-limit-gib", "1"],
    ["--max-rss-gib", "3", "--vm-limit-gib", "2"],
    ["--timeout-seconds", "60"],
    ["--min-free-gib", "0.1"],
    ["--min-free-gib", "2.5"],
    ["--child", "--mode", "both"],
])
def test_unsafe_or_invalid_requests_fail_before_worker(args):
    with pytest.raises(SystemExit) as e:
        probe.main(args)
    assert e.value.code == 2


def test_low_memory_snapshot_blocks_before_launch(monkeypatch):
    monkeypatch.setattr(probe, "_available_ram", lambda: 1024**3)
    result = probe._run_one(
        minutes=1300, mode="quiet", max_rss_gib=3,
        vm_limit_gib=4, timeout_seconds=120, min_free_gib=0.75,
    )
    assert result["status"] == "BLOCKED_INSUFFICIENT_INITIAL_HEADROOM"


def test_parent_passes_nondefault_rss_limit_to_worker(monkeypatch):
    captured = []

    class CompletedChild:
        returncode = 0
        pid = 999999

        def poll(self):
            return 0

        def communicate(self, timeout=None):
            return b'{"synthetic_only":true,"status":"SYNTHETIC_RUNNER_COMPLETED"}', b""

    def spawn(command, **_kwargs):
        captured.extend(command)
        return CompletedChild()

    monkeypatch.setattr(probe, "_available_ram", lambda: 10 * probe.GIB)
    monkeypatch.setattr(probe.subprocess, "Popen", spawn)
    result = probe._run_one(
        minutes=1300, mode="quiet", max_rss_gib=1,
        vm_limit_gib=2, timeout_seconds=120, min_free_gib=0.5,
    )
    assert result["status"] == "SYNTHETIC_RUNNER_COMPLETED"
    assert captured[captured.index("--max-rss-gib") + 1] == "1"
    assert captured[captured.index("--vm-limit-gib") + 1] == "2"


def test_parent_retains_synthetic_early_failure_report(monkeypatch):
    class IncompleteChild:
        returncode = 2
        pid = 999999

        def poll(self):
            return 2

        def communicate(self, timeout=None):
            return (b'{"synthetic_only":true,"status":"SYNTHETIC_RUNNER_EARLY_TERMINATION",'
                    b'"failure_category":"BUDGET_EXHAUSTED","trace_count":20}', b"")

    monkeypatch.setattr(probe, "_available_ram", lambda: 10 * probe.GIB)
    monkeypatch.setattr(probe.subprocess, "Popen", lambda *args, **kw: IncompleteChild())
    result = probe._run_one(
        minutes=1300, mode="quiet", max_rss_gib=1,
        vm_limit_gib=2, timeout_seconds=120, min_free_gib=0.5,
    )
    assert result["status"] == "WORKER_FAILED_OR_CAP_REACHED"
    assert result["child_report"]["failure_category"] == "BUDGET_EXHAUSTED"
    assert result["child_report"]["trace_count"] == 20


def test_no_file_or_data_source_cli_options():
    run = subprocess.run(
        [sys.executable, str(SCRIPT), "--help"],
        capture_output=True, text=True, check=True,
    )
    for unwanted in ("--source-file", "--private-dir", "--generation-dir", "--data"):
        assert unwanted not in run.stdout
    assert "--max-rss-gib" in run.stdout


def test_audit_hook_refuses_private_evidence_even_if_absent():
    code = (
        "import importlib.util; "
        f"s=importlib.util.spec_from_file_location('probe', {str(SCRIPT)!r}); "
        "p=importlib.util.module_from_spec(s); s.loader.exec_module(p); "
        "p._assert_synthetic_only(); "
        "open('/tmp/.signalforge-data/sf088/fake-data.json').read()"
    )
    result = subprocess.run([sys.executable, "-c", code],
                            capture_output=True, text=True, check=False)
    assert result.returncode != 0
    assert "synthetic probe cannot open protected/private files" in result.stderr


@pytest.mark.parametrize("mode", ["quiet", "scheduled"])
def test_actual_scenario_runner_small_synthetic_smoke(mode: str):
    """Call the REAL two-traversal runner, never protected data, in Linux CI."""
    if sys.platform != "linux":
        pytest.skip("Linux /proc and RLIMIT_AS required")
    run = subprocess.run(
        [sys.executable, str(SCRIPT), "--minutes", "1300", "--mode", mode,
         "--max-rss-gib", "1", "--vm-limit-gib", "2",
         "--timeout-seconds", "120", "--min-free-gib", "0.5"],
        capture_output=True, text=True, check=False, timeout=150,
    )
    assert run.returncode == 0, (run.stdout[-2000:], run.stderr[-2000:])
    report = json.loads(run.stdout)
    assert report["status"] == "SYNTHETIC_RUNNER_RESOURCE_OBSERVATION_ONLY"
    assert report["protected_source_access"] is False
    assert report["gate_d_approved"] is False
    assert report["historical_performance_evaluated"] is False
    assert len(report["results"]) == 1
    result = report["results"][0]
    assert result["actual_runner_run_verified_called"] is True
    assert result["two_internal_traversals"] is True
    assert result["source_minutes"] == 1300
    assert result["complete_grid"] is True
    assert result["measured_is_candles"] == 1
    assert result["measured_oos_candles"] == 9
    assert result["peak_rss_bytes"] > 0
    assert result["execution_valid"] is False
    assert result["failure_category"] is None
    # This is only an interface/capacity diagnostic, not a synthetic trade study.
    for banned in ("profit", "win_rate", "expectancy", "pnl", "r_distribution"):
        assert banned not in run.stdout.lower()
