"""Source-free safety tests for the bounded Stage 6 launcher (SF-274)."""

from __future__ import annotations

import importlib.util
import json
import os
import stat
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/stage6_guarded_launcher.py"
SPEC = importlib.util.spec_from_file_location("sf274_guarded_launcher", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
launcher = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = launcher
SPEC.loader.exec_module(launcher)


def test_frozen_identities_and_fixed_resource_envelope():
    assert launcher.BASELINE == "5d2812d11f8f5f061a1b637726f9e73b488c6e43"
    assert launcher.MAX_MEMORY == 3 * 1024**3
    assert launcher.MAX_AS == 4 * 1024**3
    assert launcher.MAX_OUTPUT == 512 * 1024**2
    assert launcher.WALL_SECONDS == 1200
    assert launcher.PREREG == "9f55f96b47d2f83c8231595769ad0e3aaede6ef17a599e68f6ea115d1d8252c2"
    assert len(launcher.RUNS) == 2
    assert launcher.SOURCE_DIR.name == "generation-0001"


def test_actual_envelope_has_cgroup_timeout_rlimits_and_one_worker(monkeypatch):
    monkeypatch.setattr(
        launcher.shutil, "which", lambda name: "/usr/bin/" + name,
    )
    cmd = launcher._scope_command(
        ["--internal-worker", "--profile", "REFERENCE_RAW", "--attempt", "2"],
        unit="sf274-reference_raw-a2-432.scope",
    )
    assert "--user" in cmd and "--scope" in cmd and "--quiet" in cmd
    assert f"MemoryMax={launcher.MAX_MEMORY}" in cmd
    assert "MemorySwapMax=0" in cmd
    assert "--unit=sf274-reference_raw-a2-432.scope" in cmd
    assert "--signal=TERM" in cmd and "--kill-after=5s" in cmd
    assert f"{launcher.WALL_SECONDS}s" in cmd
    assert f"--as={launcher.MAX_AS}:{launcher.MAX_AS}" in cmd
    assert f"--fsize={launcher.MAX_OUTPUT}:{launcher.MAX_OUTPUT}" in cmd
    assert f"--cpu={launcher.CPU_SECONDS}:{launcher.CPU_SECONDS}" in cmd
    assert cmd[-5:] == [
        "--internal-worker", "--profile", "REFERENCE_RAW", "--attempt", "2",
    ]
    assert "stage6_synthetic_full_window_probe.py" not in " ".join(cmd)


def test_default_probe_does_not_access_protected_source(monkeypatch, capsys):
    monkeypatch.setattr(launcher, "verify_checkout", lambda: None)

    def no_source():
        raise AssertionError("probe must not touch protected source")

    monkeypatch.setattr(launcher, "_source_dir", no_source)
    monkeypatch.setattr(launcher, "verify_prelaunch", lambda *a, **k: no_source())
    monkeypatch.setattr(launcher, "_probe", lambda: {
        "status": "LIMITS_VERIFIED", "memory_max_bytes": launcher.MAX_MEMORY,
    })
    assert launcher.main([]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["protected_access"] is False


@pytest.mark.parametrize("args", [
    ["--run"],
    ["--profile", "REFERENCE_RAW"],
    ["--run", "--profile", "REFERENCE_RAW"],
    ["--run", "--attempt", "1"],
    ["--run", "--profile", "OTHER", "--attempt", "1"],
    ["--run", "--profile", "REFERENCE_RAW", "--attempt", "3"],
])
def test_bad_launch_arguments_never_enter_worker(monkeypatch, args):
    monkeypatch.setattr(
        launcher, "_parent_run",
        lambda *a: pytest.fail("unsafe arguments reached protected run"),
    )
    with pytest.raises(SystemExit) as exc:
        launcher.main(args)
    assert exc.value.code == 2


def test_unguarded_worker_rejected_before_source(monkeypatch):
    monkeypatch.setattr(
        launcher, "_limits",
        lambda: (_ for _ in ()).throw(launcher.LaunchBlocked("limits absent")),
    )
    monkeypatch.setattr(
        launcher, "verify_prelaunch",
        lambda *a, **k: pytest.fail("worker accessed source before guard"),
    )
    with pytest.raises(launcher.LaunchBlocked, match="limits absent"):
        launcher._worker("REFERENCE_RAW", 1)


def test_private_path_rejects_loose_permissions_and_symlinks(tmp_path):
    directory = tmp_path / "private"
    directory.mkdir(mode=0o700)
    assert launcher._private(directory, 0o700) == directory
    directory.chmod(0o755)
    with pytest.raises(launcher.LaunchBlocked, match="private permissions"):
        launcher._private(directory, 0o700)
    directory.chmod(0o700)
    alias = tmp_path / "alias"
    alias.symlink_to(directory)
    with pytest.raises(launcher.LaunchBlocked, match="symlink"):
        launcher._private(alias, 0o700)


def _setup_protected_looking_preflight(monkeypatch, tmp_path: Path):
    private = tmp_path / "prereg"
    output = tmp_path / "output"
    private.mkdir(mode=0o700)
    output.mkdir(mode=0o700)
    gate = private / "gate-d-record.json"
    gate.write_text(json.dumps({
        "parent_issue": 253, "record_url": launcher.GATE_D_URL,
        "decision": "GATE_D_ACCEPT",
        "preregistration_id": launcher.PREREG,
        "execution_revision": launcher.BASELINE,
    }), encoding="utf-8")
    gate.chmod(0o600)
    manifest = private / "reference_raw-input-manifest.json"
    manifest.write_text("synthetic-private-manifest", encoding="utf-8")
    manifest.chmod(0o600)
    monkeypatch.setattr(launcher, "PRIVATE_DIR", private)
    monkeypatch.setattr(launcher, "OUTPUT_ROOT", output)
    monkeypatch.setattr(launcher, "GATE_RECORD", gate)
    monkeypatch.setattr(launcher, "verify_checkout", lambda: None)
    monkeypatch.setattr(launcher, "_source_dir", lambda: tmp_path / "unused-source")
    monkeypatch.setattr(launcher, "_available_ram", lambda: 10 * launcher.GIB)
    old = launcher.RUNS["REFERENCE_RAW"]
    monkeypatch.setitem(
        launcher.RUNS, "REFERENCE_RAW",
        (old[0], launcher._sha256(manifest), old[2]),
    )
    return output, gate, manifest


def test_prelaunch_accepts_only_exact_existing_private_evidence(monkeypatch, tmp_path):
    root, record, _ = _setup_protected_looking_preflight(monkeypatch, tmp_path)
    source, attempt_dir = launcher.verify_prelaunch("REFERENCE_RAW", 1)
    assert source.name == "unused-source"
    assert attempt_dir.parent == root
    attempt_dir.mkdir(mode=0o700)
    with pytest.raises(launcher.LaunchBlocked, match="overwritten"):
        launcher.verify_prelaunch("REFERENCE_RAW", 1)
    assert launcher.verify_prelaunch("REFERENCE_RAW", 1, existing=True)[1] == attempt_dir
    approval = json.loads(record.read_text(encoding="utf-8"))
    approval["record_url"] = "https://github.com/example/bogus"
    record.write_text(json.dumps(approval), encoding="utf-8")
    with pytest.raises(launcher.LaunchBlocked, match="Gate D record"):
        launcher.verify_prelaunch("REFERENCE_RAW", 2)


def test_parent_failure_quarantines_without_canonical_result(monkeypatch, tmp_path):
    output, _, _ = _setup_protected_looking_preflight(monkeypatch, tmp_path)
    monkeypatch.setattr(launcher, "_probe", lambda: {"status": "LIMITS_VERIFIED"})
    monkeypatch.setattr(launcher, "_scope_command", lambda *_a, **_kw: ["fake-scoped-worker"])
    stopped = []

    def command_run(args, **_kwargs):
        if args[:3] == ["systemctl", "--user", "stop"]:
            stopped.append(args[-1])
            return SimpleNamespace(returncode=0)
        return SimpleNamespace(returncode=124)

    monkeypatch.setattr(launcher.subprocess, "run", command_run)
    result = launcher._parent_run("REFERENCE_RAW", 1)
    assert result["status"] == "ATTEMPT_QUARANTINED_NO_PERFORMANCE"
    assert result["launcher_exit_code"] == 124
    assert (output / "reference_raw-attempt-1/failure.json").exists()
    assert not (output / "reference_raw-attempt-1/canonical-result.json").exists()
    assert len(stopped) == 1
    with pytest.raises(launcher.LaunchBlocked, match="overwritten"):
        launcher._parent_run("REFERENCE_RAW", 1)


def test_parent_success_promotes_only_matching_receipt(monkeypatch, tmp_path):
    output, _, _ = _setup_protected_looking_preflight(monkeypatch, tmp_path)
    monkeypatch.setattr(launcher, "_probe", lambda: {"status": "LIMITS_VERIFIED"})
    monkeypatch.setattr(launcher, "_scope_command", lambda *_a, **_kw: ["fake-scoped-worker"])

    def command_run(_args, **_kwargs):
        attempt = output / "reference_raw-attempt-2"
        pending = attempt / "partial.json"
        pending.write_bytes(b"fabricated-non-economic-json\n")
        pending.chmod(0o600)
        receipt = {
            "status": "CANONICAL_WRITE_COMPLETED_METHOD_UNASSESSED",
            "profile": "REFERENCE_RAW", "attempt": 2,
            "scenario_run_id": launcher.RUNS["REFERENCE_RAW"][0],
            "canonical_sha256": launcher._sha256(pending),
            "canonical_bytes": pending.stat().st_size,
            "execution_valid": False,
        }
        path = attempt / "worker-receipt.json"
        path.write_text(json.dumps(receipt), encoding="utf-8")
        path.chmod(0o600)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(launcher.subprocess, "run", command_run)
    result = launcher._parent_run("REFERENCE_RAW", 2)
    assert result["status"] == "CANONICAL_RESULT_PRIVATE_NOT_RELEASED"
    assert result["gate_e_approved"] is False
    directory = output / "reference_raw-attempt-2"
    assert (directory / "canonical-result.json").exists()
    assert not (directory / "partial.json").exists()
    assert stat.S_IMODE((directory / "canonical-result.json").stat().st_mode) == 0o600
    assert not (directory / "failure.json").exists()


def test_current_source_run_is_forbidden_in_synthetic_tests():
    """CLI help must not start historical research or open the private archive."""
    run = subprocess.run(
        [sys.executable, str(SCRIPT), "--help"],
        check=True, capture_output=True, text=True,
    )
    assert "--run" in run.stdout
    assert "--probe" in run.stdout
    assert "--internal-worker" not in run.stdout
    assert "--internal-probe" not in run.stdout
