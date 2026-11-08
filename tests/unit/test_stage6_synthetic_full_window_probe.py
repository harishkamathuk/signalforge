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
    ["--child", "--serialize-result", "--mode", "quiet"],
    ["--child-scratch", "/tmp/signalforge-sf272-forbidden"],
    ["--max-output-mib", "2048"],
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
    assert "--serialize-result" in run.stdout
    assert "--max-output-mib" in run.stdout
    assert "--child-scratch" not in run.stdout


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
    assert result["serialization"]["status"] == "NOT_REQUESTED"
    assert report["serialization_requested"] is False
    assert len(result["runner_checkout_git_sha"]) == 40
    assert len(result["loaded_runner_sha256"]) == 64
    assert result["loaded_runner_file"].endswith(
        "/signalforge/research/scenario_execution.py"
    )
    assert result["execution_valid"] is False
    assert result["failure_category"] is None
    # This is only an interface/capacity diagnostic, not a synthetic trade study.
    for banned in ("profit", "win_rate", "expectancy", "pnl", "r_distribution"):
        assert banned not in run.stdout.lower()


def test_disposable_scratch_accepts_only_private_empty_temp_root(tmp_path: Path):
    """A caller-selected directory is never eligible for canonical output."""
    with pytest.raises(probe.ProbeBlocked):
        probe._private_scratch(tmp_path)
    import tempfile
    import stat

    with tempfile.TemporaryDirectory(prefix=probe.SCRATCH_PREFIX) as name:
        private = Path(name)
        assert probe._private_scratch(private) == private
        (private / "leftover").write_text("partial", encoding="utf-8")
        with pytest.raises(probe.ProbeBlocked, match="must be empty"):
            probe._private_scratch(private)
        (private / "leftover").unlink()
        private.chmod(0o755)
        with pytest.raises(probe.ProbeBlocked, match="unapproved"):
            probe._private_scratch(private)
        private.chmod(0o700)
        assert stat.S_IMODE(private.stat().st_mode) == 0o700


def test_low_scratch_disk_blocks_before_worker(monkeypatch):
    """Synthetic serialization never starts when scratch disk reserve is absent."""
    monkeypatch.setattr(probe, "_available_ram", lambda: 10 * probe.GIB)
    monkeypatch.setattr(probe, "_scratch_free_bytes", lambda: 5 * probe.MIB)

    def forbidden_spawn(*_args, **_kwargs):
        raise AssertionError("worker must not start without scratch capacity")

    monkeypatch.setattr(probe.subprocess, "Popen", forbidden_spawn)
    result = probe._run_one(
        minutes=1300, mode="quiet", max_rss_gib=1,
        vm_limit_gib=2, timeout_seconds=120, min_free_gib=0.5,
        serialize_result=True, max_output_mib=64,
    )
    assert result["status"] == "BLOCKED_INSUFFICIENT_SCRATCH_DISK"


def test_parent_cleans_partial_serialization_after_failed_worker(monkeypatch):
    """A worker failure leaves no private or partially written canonical JSON."""
    scratch_paths: list[Path] = []

    class FailedChild:
        returncode = 2
        pid = 999999

        def poll(self):
            return 2

        def communicate(self, timeout=None):
            return b"", b"intentional synthetic worker failure"

    def spawn(command, **_kwargs):
        scratch = Path(command[command.index("--child-scratch") + 1])
        scratch_paths.append(scratch)
        assert scratch.is_dir()
        assert command[command.index("--max-output-mib") + 1] == "64"
        assert "--serialize-result" in command
        (scratch / "synthetic-result.json").write_bytes(b"partial")
        return FailedChild()

    monkeypatch.setattr(probe, "_available_ram", lambda: 10 * probe.GIB)
    monkeypatch.setattr(probe, "_scratch_free_bytes", lambda: 2 * probe.GIB)
    monkeypatch.setattr(probe.subprocess, "Popen", spawn)
    result = probe._run_one(
        minutes=1300, mode="scheduled", max_rss_gib=1,
        vm_limit_gib=2, timeout_seconds=120, min_free_gib=0.5,
        serialize_result=True, max_output_mib=64,
    )
    assert result["status"] == "WORKER_FAILED_OR_CAP_REACHED"
    assert len(scratch_paths) == 1
    assert not scratch_paths[0].exists()


def test_parent_cleans_partial_serialization_after_rss_safety_kill(monkeypatch):
    """The parent must remove an interrupted writer's partial scratch artifact."""
    scratch_paths: list[Path] = []

    class RunningChild:
        pid = 999999
        returncode = -9

        def poll(self):
            return None

        def kill(self):
            self.returncode = -9

        def communicate(self, timeout=None):
            return b"", b""

    def spawn(command, **_kwargs):
        scratch = Path(command[command.index("--child-scratch") + 1])
        scratch_paths.append(scratch)
        (scratch / "synthetic-result.json").write_bytes(b"partial")
        return RunningChild()

    monkeypatch.setattr(probe, "_available_ram", lambda: 10 * probe.GIB)
    monkeypatch.setattr(probe, "_scratch_free_bytes", lambda: 2 * probe.GIB)
    monkeypatch.setattr(probe, "_worker_rss", lambda _pid: 2 * probe.GIB)
    monkeypatch.setattr(probe.subprocess, "Popen", spawn)
    result = probe._run_one(
        minutes=1300, mode="scheduled", max_rss_gib=1,
        vm_limit_gib=2, timeout_seconds=120, min_free_gib=0.5,
        serialize_result=True, max_output_mib=64,
    )
    assert result["status"] == "SAFETY_STOP"
    assert result["reason"] == "RSS_CEILING_REACHED"
    assert not scratch_paths[0].exists()


@pytest.mark.parametrize("mode", ["quiet", "scheduled"])
def test_real_synthetic_canonical_write_small_smoke(mode: str):
    """Exercise run_verified and the unchanged result writer, with ephemeral output."""
    if sys.platform != "linux":
        pytest.skip("Linux /proc and RLIMIT_AS required")
    run = subprocess.run(
        [sys.executable, str(SCRIPT), "--minutes", "1300", "--mode", mode,
         "--serialize-result", "--max-output-mib", "64",
         "--max-rss-gib", "1", "--vm-limit-gib", "2",
         "--timeout-seconds", "120", "--min-free-gib", "0.5"],
        capture_output=True, text=True, check=False, timeout=150,
    )
    assert run.returncode == 0, (run.stdout[-2000:], run.stderr[-2000:])
    report = json.loads(run.stdout)
    assert report["status"] == "SYNTHETIC_RUNNER_RESOURCE_OBSERVATION_ONLY"
    assert report["serialization_requested"] is True
    assert report["protected_source_access"] is False
    assert report["historical_performance_evaluated"] is False
    result = report["results"][0]
    assert result["two_internal_traversals"] is True
    assert result["serialization"]["status"] == "SYNTHETIC_CANONICAL_WRITE_COMPLETED"
    assert 0 < result["serialization"]["bytes"] < 64 * probe.MIB
    assert len(result["serialization"]["sha256"]) == 64
    assert result["serialization"]["peak_rss_bytes_after_write"] >= (
        result["peak_rss_bytes_before_write"]
    )
    assert result["peak_rss_bytes"] >= result["peak_rss_bytes_before_write"]
    assert "synthetic-result.json" not in run.stdout
    for banned in ("profit", "win_rate", "expectancy", "pnl", "r_distribution"):
        assert banned not in run.stdout.lower()
