"""SF-260 synthetic-only private custody checks; no source/archive access."""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import stage6_90d_independent_verifier as independent
from scripts import stage6_90d_source_preflight as preflight


def test_source_only_preflight_writes_canonical_private_once(monkeypatch, tmp_path):
    monkeypatch.setattr(preflight, "PRIVATE", tmp_path)
    tmp_path.chmod(0o700)
    before = json.dumps({"synthetic": True}).encode("utf-8")
    monkeypatch.setattr(preflight.os, "umask", lambda _value: 0o022)
    preflight._write_private_payloads([("fixture-only.json", before)])
    output = tmp_path / "fixture-only.json"
    assert output.read_bytes() == before
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    with pytest.raises(FileExistsError):
        preflight._write_private_payloads([("fixture-only.json", b"replacement")])
    assert output.read_bytes() == before


def test_independent_receipt_has_real_newline_and_0600(monkeypatch, tmp_path):
    monkeypatch.setattr(independent, "PRIVATE", tmp_path)
    monkeypatch.setattr(independent, "git_revision", lambda: "a" * 40)
    monkeypatch.setattr(independent, "verify_source_only", lambda: {
        "status": "SOURCE_ONLY_INDEPENDENTLY_VERIFIED_NO_GATE_D",
        "preregistration_id": "b" * 64,
        "receipt_sha256": "c" * 64,
        "audit_recomputed": True,
        "source_only": True,
        "protected_scenario_executed": False,
    })
    tmp_path.chmod(0o700)
    monkeypatch.setattr(independent.os, "umask", lambda _value: 0o022)
    assert independent.main([
        "--independent-source-only-verify", "--write-private-receipt",
    ]) == 0
    path = tmp_path / "independent-verification.json"
    data = path.read_bytes()
    assert data.endswith(b"\n")
    assert not data.endswith(b"\\n")
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    decoded, digest = independent.read_canonical(path)
    assert len(digest) == 64
    assert decoded["status"] == "SOURCE_ONLY_INDEPENDENTLY_VERIFIED_NO_GATE_D"
    assert decoded["gate_d_approved"] is False
    assert decoded["execution_valid"] is False
    with pytest.raises(SystemExit) as error:
        independent.main([
            "--independent-source-only-verify", "--write-private-receipt",
        ])
    assert error.value.code == 2


def test_source_only_operator_rejects_unmerged_branch(monkeypatch):
    monkeypatch.setattr(
        preflight.subprocess, "run",
        lambda *_args, **_kwargs: SimpleNamespace(stdout="feat/not-reviewed\\n"),
    )
    with pytest.raises(preflight.PreflightBlocked, match="merged develop"):
        preflight.git_revision()


def test_source_only_checkout_rejects_untracked_file(monkeypatch):
    commands: list[list[str]] = []

    def fake_run(args, **_kwargs):
        commands.append(args)
        if "symbolic-ref" in args:
            return SimpleNamespace(stdout="develop\\n", returncode=0)
        if "rev-parse" in args:
            return SimpleNamespace(stdout="a" * 40 + "\\n", returncode=0)
        if "status" in args:
            return SimpleNamespace(stdout="?? unexpected.py\\n", returncode=0)
        pytest.fail("unexpected git command")

    monkeypatch.setattr(preflight.subprocess, "run", fake_run)
    with pytest.raises(preflight.PreflightBlocked, match="dirty source-only checkout"):
        preflight.git_revision()
    assert any("--untracked-files=normal" in args for args in commands)


@pytest.mark.parametrize(
    "script",
    [
        "stage6_90d_guarded_launcher.py",
        "stage6_90d_source_preflight.py",
        "stage6_90d_independent_verifier.py",
    ],
)
def test_absolute_entrypoint_imports_without_operator_pythonpath(script, tmp_path):
    root = Path(__file__).resolve().parents[2]
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    result = subprocess.run(
        [sys.executable, str(root / "scripts" / script), "--help"],
        cwd=tmp_path, env=env, capture_output=True, text=True,
        check=False, timeout=15,
    )
    assert result.returncode == 0, result.stderr
