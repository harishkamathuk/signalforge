"""SF-296 restricted operator/custody tests; never load protected data."""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import sf296_guarded_v2 as op
from signalforge.research.prospective_saved_verifier import EvidenceBlocked, verify_v2_structure


def test_status_is_exact_non_economic_allowlist():
    for state in ("NON_ECONOMIC_EVIDENCE_VERIFIED", "WITHHELD", "VALIDATION_BLOCKED"):
        record = op._status(state)
        assert set(record) == {
            "contract", "status", "source_kind", "verification_tier",
            "economics", "oos", "gate_d_approved", "gate_e_approved",
            "execution_valid",
        }
        assert record["source_kind"] == "SYNTHETIC_TEST_ONLY"
        assert record["oos"] == "SEALED"
        assert record["economics"] == "WITHHELD"
        assert record["execution_valid"] is False
        assert record["gate_d_approved"] is False
        assert record["gate_e_approved"] is False
        assert record["verification_tier"] == (
            op.TIER if state == "NON_ECONOMIC_EVIDENCE_VERIFIED"
            else "NOT_VERIFIED"
        )


@pytest.mark.parametrize("args", [
    ["--run-synthetic"],
    ["--verify", "--profile", "REFERENCE_RAW", "--attempt", "1"],
    ["--run-synthetic", "--profile", "WRONG"],
    ["--run-synthetic", "--profile", "REFERENCE_RAW", "--attempt", "3"],
    ["--root", "/tmp/unsafe"],
    ["--unknown"],
    ["--help"],
])
def test_bad_arguments_emit_only_fixed_blocked_status(capsys, args):
    assert op.main(args) == 1
    captured = capsys.readouterr()
    assert captured.err == ""
    assert json.loads(captured.out) == op._status("VALIDATION_BLOCKED")
    assert "Traceback" not in captured.out


def test_missing_committed_set_never_verified(tmp_path: Path, capsys):
    os.chmod(tmp_path, 0o700)
    assert op.main([
        "--verify", "--root", str(tmp_path),
        "--profile", "REFERENCE_RAW", "--attempt", "1",
    ]) == 1
    captured = capsys.readouterr()
    assert captured.err == ""
    assert json.loads(captured.out) == op._status("VALIDATION_BLOCKED")


def test_private_writes_are_0600_and_exclusive(tmp_path: Path):
    os.chmod(tmp_path, 0o700)
    path = tmp_path / "receipt.json"
    op._json(path, {"schema": "test"})
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert op._record(path, root=tmp_path) == {"schema": "test"}
    with pytest.raises(FileExistsError):
        op._json(path, {"schema": "overwrite"})


def test_atomic_directory_rename_refuses_existing_target(tmp_path: Path):
    os.chmod(tmp_path, 0o700)
    staged = tmp_path / "stage"
    final = tmp_path / "final"
    staged.mkdir(mode=0o700)
    final.mkdir(mode=0o700)
    with pytest.raises((OSError, op.OperatorBlocked)):
        op._no_replace_directory(staged, final)
    assert staged.is_dir() and final.is_dir()


def test_atomic_directory_rename_moves_entire_set(tmp_path: Path):
    os.chmod(tmp_path, 0o700)
    staged = tmp_path / "stage"
    final = tmp_path / "final"
    staged.mkdir(mode=0o700)
    op._write(staged / "artifact.json", b'{"synthetic":true}\n')
    op._sync_dir(staged)
    op._no_replace_directory(staged, final)
    op._sync_dir(tmp_path)
    assert final.is_dir() and not staged.exists()
    assert op._read(final / "artifact.json", root=tmp_path) == (
        b'{"synthetic":true}\n'
    )


def test_saved_verifier_refuses_untrusted_and_malformed_bytes():
    for value in (b"", b"{}", b'{"result":"scenario-result-v1"}\n',
                  b'{"invalid":true}\n'):
        with pytest.raises(EvidenceBlocked):
            verify_v2_structure(value, b"{}", b"{}")


def test_consistent_forged_uncommitted_set_is_blocked(tmp_path: Path, capsys):
    os.chmod(tmp_path, 0o700)
    name = "reference_raw-attempt-1"
    path = tmp_path / name
    path.mkdir(mode=0o700)
    # Even a self-authored, hash-matching artifact/receipt without a trusted
    # parent completion record is not controlled producer lineage (T2).
    op._json(path / "worker-receipt.json", {
        "schema": "sf296-worker-receipt-v1", "files": {},
    })
    assert op.main([
        "--verify", "--root", str(tmp_path),
        "--profile", "REFERENCE_RAW", "--attempt", "1",
    ]) == 1
    captured = capsys.readouterr()
    assert json.loads(captured.out) == op._status("VALIDATION_BLOCKED")


def test_no_protected_mode_is_exposed(capsys):
    assert op.main(["--run", "--profile", "REFERENCE_RAW", "--attempt", "1"]) == 1
    captured = capsys.readouterr()
    assert captured.err == ""
    assert json.loads(captured.out) == op._status("VALIDATION_BLOCKED")


def test_supplemental_parent_worker_v2_custody_with_mocked_scope(
    tmp_path: Path, capsys, monkeypatch,
):
    """Supplemental composition; explicitly NOT real systemd-host acceptance."""
    from types import SimpleNamespace

    os.chmod(tmp_path, 0o700)
    head = subprocess.check_output(
        ["git", "-C", str(op.ROOT), "rev-parse", "HEAD"], text=True,
    ).strip()
    monkeypatch.setattr(op, "_checkout", lambda: head)
    monkeypatch.setattr(op, "_limits", lambda: None)
    monkeypatch.setattr(op, "_command", lambda *args: ["synthetic-fake-scope"])
    monkeypatch.setattr(op, "_stop", lambda scope: True)

    def guarded_worker_simulation(command, **kwargs):
        assert command == ["synthetic-fake-scope"]
        # The original parent owns a live OS flock and crash marker.
        # The worker runs actual scenario + distinct strict producer + writer.
        op._worker(tmp_path, "REFERENCE_RAW", 1)
        return SimpleNamespace(returncode=0)

    # Mock only the parent-to-scope subprocess. The detached verifier below
    # must start a *real* independent Python interpreter.
    with monkeypatch.context() as scope_patch:
        scope_patch.setattr(op.subprocess, "run", guarded_worker_simulation)
        assert op.main([
            "--run-synthetic", "--root", str(tmp_path),
            "--profile", "REFERENCE_RAW", "--attempt", "1",
        ]) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    assert json.loads(captured.out) == op._status("NON_ECONOMIC_EVIDENCE_VERIFIED")
    finished = tmp_path / "reference_raw-attempt-1"
    assert finished.is_dir()
    assert set(x.name for x in finished.iterdir()) == set(op.FILES) | {
        op.WORKER_RECEIPT,
    }
    assert (tmp_path / "reference_raw-attempt-1.complete.json").is_file()
    assert not (tmp_path / op.MARKER).exists()
    assert op._verify_set(tmp_path, "reference_raw-attempt-1") == "COMPLETE"
    # An independently started Python interpreter rereads the saved files.
    # Override only the clean-checkout requirement for this *supplemental*
    # test: ordinary developer trees may contain unrelated uncommitted work.
    # The mandatory clean-head real guarded-host CLI test is separate AC-01.
    verifier = (
        "import sys; from scripts import sf296_guarded_v2 as op; "
        "op._checkout = lambda: sys.argv[1]; "
        "sys.exit(op.main(sys.argv[2:]))"
    )
    checked = subprocess.run(
        [
            sys.executable, "-c", verifier, head,
            "--verify", "--root", str(tmp_path),
            "--profile", "REFERENCE_RAW", "--attempt", "1",
        ],
        cwd=op.ROOT, capture_output=True, text=True, check=False,
    )
    assert checked.returncode == 0
    assert checked.stderr == ""
    assert json.loads(checked.stdout) == op._status("NON_ECONOMIC_EVIDENCE_VERIFIED")

    # Control: remove *only* the parent ack from an otherwise valid saved set.
    # Unlike an incomplete mock directory, this reaches the actual ack gate.
    ack = tmp_path / "reference_raw-attempt-1.complete.json"
    ack_quarantine = tmp_path / "ack-withheld-for-test"
    ack.rename(ack_quarantine)
    try:
        with pytest.raises((op.OperatorBlocked, OSError, KeyError)):
            op._verify_set(tmp_path, "reference_raw-attempt-1")
    finally:
        ack_quarantine.rename(ack)
    assert op._verify_set(tmp_path, "reference_raw-attempt-1") == "COMPLETE"

    # Fail closed on attempted idempotent rerun, no overwrite.
    assert op.main([
        "--run-synthetic", "--root", str(tmp_path),
        "--profile", "REFERENCE_RAW", "--attempt", "1",
    ]) == 1
    assert json.loads(capsys.readouterr().out) == op._status("VALIDATION_BLOCKED")


def test_unavailable_guard_tool_fails_before_creating_attempt(tmp_path, monkeypatch):
    os.chmod(tmp_path, 0o700)
    monkeypatch.setattr(op, "_checkout", lambda: "synthetic-revision")

    def missing_systemd(*args):
        raise op.OperatorBlocked("MISSING_SYSTEMD")

    monkeypatch.setattr(op, "_command", missing_systemd)
    with pytest.raises(op.OperatorBlocked):
        op._parent(tmp_path, "REFERENCE_RAW", 1)
    assert not (tmp_path / op.MARKER).exists()
    assert not (tmp_path / "reference_raw-attempt-1.staging").exists()
    assert not (tmp_path / "reference_raw-attempt-1").exists()


def _make_synthetic_complete_set(tmp_path: Path, monkeypatch, capsys) -> Path:
    """Supplemental mocked scope, but real worker/producers/v2 bytes and commit."""
    from types import SimpleNamespace

    os.chmod(tmp_path, 0o700)
    monkeypatch.setattr(op, "_checkout", lambda: "synthetic-test-revision")
    monkeypatch.setattr(op, "_limits", lambda: None)
    monkeypatch.setattr(op, "_command", lambda *args: ["synthetic-fake-scope"])
    monkeypatch.setattr(op, "_stop", lambda scope: True)

    def run_worker(command, **kwargs):
        assert command == ["synthetic-fake-scope"]
        op._worker(tmp_path, "REFERENCE_RAW", 1)
        return SimpleNamespace(returncode=0)

    with monkeypatch.context() as fake_scope:
        fake_scope.setattr(op.subprocess, "run", run_worker)
        assert op.main([
            "--run-synthetic", "--root", str(tmp_path),
            "--profile", "REFERENCE_RAW", "--attempt", "1",
        ]) == 0
    assert json.loads(capsys.readouterr().out) == op._status(
        "NON_ECONOMIC_EVIDENCE_VERIFIED"
    )
    final = tmp_path / "reference_raw-attempt-1"
    assert op._verify_set(tmp_path, final.name) == "COMPLETE"
    return final


@pytest.mark.parametrize("fault", [
    "missing_source_companion",
    "changed_result_bytes",
    "receipt_hash_mismatch",
    "changed_completion_ack",
    "unsafe_hardlink",
    "unsafe_symlink",
    "public_read_permission",
])
def test_complete_set_adversarial_mutations_fail_closed(
    tmp_path: Path, monkeypatch, capsys, fault: str,
):
    """Mutate a *valid* committed synthetic set so the intended gate is reached."""
    final = _make_synthetic_complete_set(tmp_path, monkeypatch, capsys)
    source = final / op.FILES[0]
    result = final / op.FILES[2]
    receipt = final / op.WORKER_RECEIPT
    ack = tmp_path / (final.name + ".complete.json")
    files = {p: p.read_bytes() for p in (source, result, receipt, ack)}
    linked = tmp_path / "link-target"

    try:
        if fault == "missing_source_companion":
            source.unlink()
        elif fault == "changed_result_bytes":
            result.write_bytes(result.read_bytes() + b" ")
        elif fault == "receipt_hash_mismatch":
            receipt.write_bytes(receipt.read_bytes() + b" ")
        elif fault == "changed_completion_ack":
            altered = json.loads(ack.read_bytes())
            altered["scope_confirmed_inactive"] = False
            ack.write_text(json.dumps(altered) + "\n", encoding="utf-8")
        elif fault == "unsafe_hardlink":
            linked.hardlink_to(source)
        elif fault == "unsafe_symlink":
            source.unlink()
            linked.write_bytes(files[source])
            source.symlink_to(linked)
        elif fault == "public_read_permission":
            source.chmod(0o644)

        assert op.main([
            "--verify", "--root", str(tmp_path),
            "--profile", "REFERENCE_RAW", "--attempt", "1",
        ]) == 1
        captured = capsys.readouterr()
        assert captured.err == ""
        assert json.loads(captured.out) == op._status("VALIDATION_BLOCKED")
        assert "Traceback" not in captured.out
    finally:
        for path, raw in files.items():
            if path.is_symlink():
                path.unlink()
            path.write_bytes(raw)
            path.chmod(0o600)
        if linked.exists():
            linked.unlink()
    # Restore proves the negative was not merely an invalid original fixture.
    assert op._verify_set(tmp_path, final.name) == "COMPLETE"


@pytest.mark.parametrize("boundary", [
    "parent_readback",
    "stage_fsync",
    "atomic_rename",
    "post_rename_parent_fsync",
    "completion_ack_write",
])
def test_complete_set_parent_fault_edges_never_verify(
    tmp_path: Path, monkeypatch, capsys, boundary: str,
):
    """Fault after valid worker output, before durable parent completion."""
    from types import SimpleNamespace

    os.chmod(tmp_path, 0o700)
    monkeypatch.setattr(op, "_checkout", lambda: "synthetic-test-revision")
    monkeypatch.setattr(op, "_limits", lambda: None)
    monkeypatch.setattr(op, "_command", lambda *args: ["synthetic-fake-scope"])
    monkeypatch.setattr(op, "_stop", lambda scope: True)
    real_read = op._read
    real_sync = op._sync_dir
    real_json = op._json
    name = "reference_raw-attempt-1"

    def fail_at_selected_edge(command, **kwargs):
        assert command == ["synthetic-fake-scope"]
        # Only the guarded worker composes genuine synthetic artifacts.
        op._worker(tmp_path, "REFERENCE_RAW", 1)

        if boundary == "parent_readback":
            def read(path, *, root):
                if path.name == op.WORKER_RECEIPT:
                    raise OSError("synthetic-injected-readback-failure")
                return real_read(path, root=root)
            monkeypatch.setattr(op, "_read", read)
        elif boundary in ("stage_fsync", "post_rename_parent_fsync"):
            def sync(path):
                if (boundary == "stage_fsync" and path.name.endswith(".staging")) or (
                    boundary == "post_rename_parent_fsync"
                    and path == tmp_path and (tmp_path / name).exists()
                    and not (tmp_path / (name + ".complete.json")).exists()
                ):
                    raise OSError("synthetic-injected-fsync-failure")
                return real_sync(path)
            monkeypatch.setattr(op, "_sync_dir", sync)
        elif boundary == "atomic_rename":
            def rename(source, target):
                raise OSError("synthetic-injected-rename-failure")
            monkeypatch.setattr(op, "_no_replace_directory", rename)
        elif boundary == "completion_ack_write":
            def write_json(path, value):
                if path.name.endswith(".complete.json"):
                    raise OSError("synthetic-injected-ack-failure")
                return real_json(path, value)
            monkeypatch.setattr(op, "_json", write_json)
        return SimpleNamespace(returncode=0)

    with monkeypatch.context() as fake_scope:
        fake_scope.setattr(op.subprocess, "run", fail_at_selected_edge)
        assert op.main([
            "--run-synthetic", "--root", str(tmp_path),
            "--profile", "REFERENCE_RAW", "--attempt", "1",
        ]) == 1
    captured = capsys.readouterr()
    assert captured.err == ""
    assert json.loads(captured.out) == op._status("VALIDATION_BLOCKED")
    assert (tmp_path / op.MARKER).exists()
    assert not (tmp_path / (name + ".complete.json")).exists()
    with pytest.raises((op.OperatorBlocked, OSError, KeyError)):
        op._verify_set(tmp_path, name)
    # Neither a staged nor an unacknowledged committed directory is accepted.
    assert (tmp_path / (name + ".staging")).exists() != (tmp_path / name).exists()
