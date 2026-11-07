"""Guard frozen Stage 6 synthetic-only memory sizing and projection semantics."""

from __future__ import annotations

import ast
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "stage6_synthetic_memory_probe.py"
SPEC = importlib.util.spec_from_file_location("stage6_synthetic_memory_probe", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)


def _result(evidence: int, rss: int, output: int, mode: str = "trace") -> dict[str, object]:
    return {"mode": mode, "evidence_count": evidence,
            "peak_rss_bytes": rss, "output_bytes": output}


def test_frozen_budget_constants_and_ratio() -> None:
    """Sizing must not quietly change the preregistered finite limits."""
    assert (probe.SOURCE_MINUTES, probe.FIVE_MINUTE_CANDLES, probe.MAX_BARS) == (
        525_600, 105_120, 524_160,
    )
    assert (probe.MAX_EVENTS, probe.MAX_OUTCOMES, probe.MAX_EVIDENCE, probe.MAX_STATES) == (
        2_096_640, 104_833, 2_096_640, 1,
    )
    exact = probe.sample_counts(probe.MAX_EVIDENCE)
    assert exact == {"source_bars": 525_600, "five_minute_candles": 105_120,
                     "outcomes": 104_833}


def test_sample_bounds_fail_closed() -> None:
    for value in (-1, 0, 2_096_641, True, 1.1):
        with pytest.raises(probe.ProbeError):
            probe.sample_counts(value)
    for value in (1, 100, 5_000, 20_000):
        sample = probe.sample_counts(value)
        assert all(v > 0 for v in sample.values())
        assert sample["source_bars"] <= 525_600


def test_projection_measured_slope_and_output_size() -> None:
    small = _result(5_000, 100_000_000, 3_000_000)
    large = _result(20_000, 250_000_000, 12_000_000)
    projection = probe.extrapolate(small, large)
    assert projection["mode"] == "trace"
    assert projection["rss_projected_full_evidence_bytes"] == (
        250_000_000 + (2_096_640 - 20_000) * 10_000
    )
    assert projection["canonical_json_projected_bytes_per_result"] == (
        12_000_000 + (2_096_640 - 20_000) * 600
    )
    assert "not a statistical upper bound" in projection["projection_warning"]
    assert projection["rss_projected_with_2x_margin_gib"] > (
        projection["rss_projected_full_evidence_gib"]
    )


def test_projection_rejects_bad_inputs() -> None:
    with pytest.raises(probe.ProbeError):
        probe.extrapolate(_result(5, 100, 10), _result(5, 200, 20))
    with pytest.raises(probe.ProbeError):
        probe.extrapolate(_result(5, 100, 10), _result(10, 200, 20, "blocked"))
    with pytest.raises(probe.ProbeError):
        probe.extrapolate(_result(5, 100, 10), _result(10, 90, 20))
    with pytest.raises(probe.ProbeError):
        probe.extrapolate(_result(5, 100, 10), _result(10, 200, 8))


ALLOWED_PROJECT_SYMBOLS = {
    "signalforge.domain.ids": {"InstrumentId"},
    "signalforge.domain.market": {"CandleQuality", "CompletedCandle"},
    "signalforge.domain.money": {"Price"},
    "signalforge.domain.time": {"CandleInterval"},
    "signalforge.research.historical_bars": {"HistoricalBar"},
    "signalforge.research.scenario_execution": {
        "ScenarioBlockedDecision", "ScenarioExecutionManifest", "ScenarioMethodStatus",
        "ScenarioOutcome", "ScenarioResearchResult", "ScenarioTrace",
    },
}


def assert_synthetic_only_ast(tree: ast.AST) -> None:
    """Reject non-allowlisted project imports and runner dispatch, including aliases."""
    actual: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert all(not entry.name.startswith("signalforge") for entry in node.names)
        elif isinstance(node, ast.ImportFrom):
            if (node.module or "").startswith("signalforge"):
                assert node.module in ALLOWED_PROJECT_SYMBOLS
                actual.setdefault(node.module, set()).update(item.name for item in node.names)
                assert all(item.asname is None for item in node.names)
                assert all(item.name in ALLOWED_PROJECT_SYMBOLS[node.module]
                           for item in node.names)
        elif isinstance(node, ast.Call):
            called = node.func
            if isinstance(called, ast.Attribute) and called.attr in {"run", "run_verified"}:
                # Only the fixed subprocess launcher is allowed. Never a
                # ScenarioResearchRunner instance nor imported runner alias.
                assert (called.attr == "run" and isinstance(called.value, ast.Name)
                        and called.value.id == "subprocess")
            if isinstance(called, ast.Name):
                assert called.id not in {"ScenarioResearchRunner", "run_verified"}
    assert actual == ALLOWED_PROJECT_SYMBOLS


def test_only_allowlisted_domain_types_and_never_call_runner() -> None:
    """Guard exact domain symbols and stop direct scenario runner invocation."""
    assert_synthetic_only_ast(ast.parse(SCRIPT.read_text(encoding="utf-8")))


@pytest.mark.parametrize("snippet", [
    "from signalforge.research.scenario_execution import ScenarioResearchRunner",
    "import signalforge.research.scenario_execution as engine",
    "runner.run(request)",
    "runner.run_verified(request)",
    "ScenarioResearchRunner().run(request)",
])
def test_synthetic_only_guard_rejects_runner_dispatch(snippet: str) -> None:
    """Prove guard fails closed for attempted runner import and invocation."""
    original = SCRIPT.read_text(encoding="utf-8")
    with pytest.raises(AssertionError):
        assert_synthetic_only_ast(ast.parse(original + "\n" + snippet))


def test_rejects_large_unbounded_worker_configuration() -> None:
    with pytest.raises(probe.ProbeError):
        probe.run_probe(small=500, large=50_001, child_vm_limit_gib=2)
    with pytest.raises(probe.ProbeError):
        probe.run_probe(small=20_000, large=5_000, child_vm_limit_gib=2)
    with pytest.raises(probe.ProbeError):
        probe.run_probe(small=5_000, large=20_000, child_vm_limit_gib=6)


@pytest.mark.skipif(sys.platform != "linux", reason="Linux-only resource guard")
def test_actual_domain_objects_synthetic_worker_small() -> None:
    """Exercise actual slots/domain classes and canonical serialization, no runner."""
    output = subprocess.run(
        [sys.executable, str(SCRIPT), "--worker", "--mode", "trace",
         "--evidence", "25", "--child-vm-limit-gib", "2"],
        capture_output=True, text=True, check=False, timeout=45,
    )
    assert output.returncode == 0, output.stderr
    record = json.loads(output.stdout)
    assert record["tag"] == probe.WORKER_TAG
    assert record["evidence_count"] == 25
    assert record["source_bars_count"] > 0
    assert record["two_replay_results_retained"] is True
    assert record["peak_rss_bytes"] > 0
    assert record["output_bytes"] > 0


@pytest.mark.skipif(sys.platform != "linux", reason="Linux-only resource guard")
def test_actual_blocked_domain_objects_synthetic_worker_small() -> None:
    output = subprocess.run(
        [sys.executable, str(SCRIPT), "--worker", "--mode", "blocked",
         "--evidence", "25", "--child-vm-limit-gib", "2"],
        capture_output=True, text=True, check=False, timeout=45,
    )
    assert output.returncode == 0, output.stderr
    record = json.loads(output.stdout)
    assert record["mode"] == "blocked"
    assert record["evidence_count"] == 25


@pytest.mark.skipif(sys.platform != "linux", reason="Linux-only resource guard")
def test_reject_worker_oversize_before_project_import() -> None:
    output = subprocess.run(
        [sys.executable, str(SCRIPT), "--worker", "--mode", "trace",
         "--evidence", "9999999", "--child-vm-limit-gib", "2"],
        capture_output=True, text=True, check=False, timeout=15,
    )
    assert output.returncode == 2
    record = json.loads(output.stderr)
    assert record["status"] == "BLOCKED_SYNTHETIC_MEMORY_PROBE"
    assert record["gate_d_approved"] is False
