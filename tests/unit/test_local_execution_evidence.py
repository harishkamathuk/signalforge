"""SF-247 bounded local execution/evidence contract tests."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from scripts.local_execution_evidence import (
    HandoffError,
    canonical_bytes,
    digest,
    execute,
    validate_request,
    verify_report,
    write_once,
)


def request_for(revision: str) -> dict[str, object]:
    """Produce one valid request with deterministic self-hash."""
    request: dict[str, object] = {
        "version": 1,
        "request_id": "sf247-smoke-0001",
        "issue": 247,
        "repository": "harishkamathuk/signalforge",
        "revision": revision,
        "argv": ["python", "-V"],
        "preflight": [
            "exact_git_head", "trusted_origin", "clean_tracked_worktree",
            "gitignored_report_path",
        ],
        "expected_exit_code": 0,
        "expected_output": "Python 3.12.x",
        "stop_conditions": [
            "preflight_failure", "request_mismatch", "unsafe_output",
        ],
        "classification": "SANITIZED_SMOKE_ONLY",
    }
    request["request_sha256"] = digest(request, "request_sha256")
    return request


@pytest.fixture
def checkout(tmp_path: Path) -> tuple[Path, str]:
    """Create an isolated Git checkout without network access or local credentials."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.email", "test@example.invalid"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.name", "Test"], check=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "remote", "add", "origin",
         "https://github.com/harishkamathuk/signalforge.git"], check=True,
    )
    (repo / ".gitignore").write_text(".signalforge-data/\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", ".gitignore"], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-qm", "test"], check=True,
    )
    revision = subprocess.check_output(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], text=True,
    ).strip()
    return repo, revision


def test_real_offline_command_and_roundtrip(
    checkout: tuple[Path, str], tmp_path: Path,
) -> None:
    """Use a synthetic Git checkout for an unstubbed subprocess oracle."""
    repo, revision = checkout
    request = request_for(revision)
    request_path = tmp_path / "request.json"
    request_path.write_bytes(canonical_bytes(request) + b"\n")
    report_path = execute(request_path, repo, request["request_id"])
    report = verify_report(report_path, request_path)
    assert report["local_status"] == "PASS"
    assert report["exit_code"] == 0
    assert report["output"].startswith("Python 3.12.")
    assert report["output_sha256"] == hashlib.sha256(
        report["output"].encode()
    ).hexdigest()
    assert report["transport_status"] == "NOT_ATTEMPTED"
    with pytest.raises(HandoffError, match="already exists"):
        execute(request_path, repo, request["request_id"])
    # Simulate transfer bytes only; this is not a real Google Drive acceptance.
    downloaded = tmp_path / "downloaded.json"
    downloaded.write_bytes(report_path.read_bytes())
    assert verify_report(downloaded, request_path) == report


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"argv": ["sh", "-c", "echo leaked"]}, "only the offline"),
        ({"repository": "attacker/another"}, "unexpected repository"),
        ({"classification": "PRIVATE"}, "classification"),
        ({"revision": "develop"}, "exact lowercase"),
        ({"request_id": "../../escape"}, "request ID"),
        ({"issue": True}, "positive"),
        ({"version": 2}, "version"),
    ],
)
def test_reject_unsafe_requests(
    checkout: tuple[Path, str],
    change: dict[str, object],
    message: str,
) -> None:
    """Safety policy cannot be bypassed by a correctly rehashed request."""
    _, revision = checkout
    request = request_for(revision)
    request.update(change)
    request["request_sha256"] = digest(request, "request_sha256")
    with pytest.raises(HandoffError, match=message):
        validate_request(request)


def test_tampered_request_rejected(checkout: tuple[Path, str]) -> None:
    """A changed byte of request semantics invalidates its identity."""
    _, revision = checkout
    request = request_for(revision)
    request["issue"] = 248
    with pytest.raises(HandoffError, match="hash mismatch"):
        validate_request(request)


def test_wrong_revision_or_approval_blocks_without_report(
    checkout: tuple[Path, str], tmp_path: Path,
) -> None:
    """Neither Git drift nor approval mismatch may run a command."""
    repo, revision = checkout
    request = request_for("0" * 40)
    path = tmp_path / "request.json"
    path.write_bytes(canonical_bytes(request))
    with pytest.raises(HandoffError, match="approval"):
        execute(path, repo, "different-id")
    with pytest.raises(HandoffError, match="HEAD"):
        execute(path, repo, request["request_id"])
    assert not (repo / ".signalforge-data").exists()
    assert revision != request["revision"]


def test_tampered_downloaded_report_rejected(
    checkout: tuple[Path, str], tmp_path: Path,
) -> None:
    """Changing transported evidence breaks verification."""
    repo, revision = checkout
    request = request_for(revision)
    path = tmp_path / "request.json"
    path.write_bytes(canonical_bytes(request))
    report = execute(path, repo, request["request_id"])
    copied = json.loads(report.read_text(encoding="utf-8"))
    copied["output"] = "Python 3.12.999"
    tampered = tmp_path / "tampered.json"
    tampered.write_bytes(canonical_bytes(copied))
    with pytest.raises(HandoffError, match="SHA-256 mismatch"):
        verify_report(tampered, path)


def test_exclusive_write_rejects_overwrite_and_symlink(tmp_path: Path) -> None:
    """Neither existing evidence nor symlink destinations can be overwritten."""
    report = tmp_path / "report.json"
    write_once(report, b"original")
    with pytest.raises(FileExistsError):
        write_once(report, b"replacement")
    assert report.read_bytes() == b"original"
    alias = tmp_path / "alias.json"
    alias.symlink_to(report)
    with pytest.raises(FileExistsError):
        write_once(alias, b"replacement")
    assert report.read_bytes() == b"original"


def test_dirty_checkout_is_rejected(
    checkout: tuple[Path, str], tmp_path: Path,
) -> None:
    """Tracked worktree differences cannot be misreported as committed code."""
    repo, revision = checkout
    (repo / ".gitignore").write_text("changed\n", encoding="utf-8")
    request = request_for(revision)
    path = tmp_path / "request.json"
    path.write_bytes(canonical_bytes(request))
    with pytest.raises(HandoffError, match="uncommitted"):
        execute(path, repo, request["request_id"])


def test_missing_python_executable_records_failure(
    checkout: tuple[Path, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A missing executable produces FAIL evidence rather than a PASS claim."""
    import scripts.local_execution_evidence as handoff

    repo, revision = checkout
    request = request_for(revision)
    path = tmp_path / "request.json"
    path.write_bytes(canonical_bytes(request))
    monkeypatch.setattr(handoff.sys, "executable", "/missing-sf247-python")
    report = execute(path, repo, request["request_id"])
    result = verify_report(report, path)
    assert result["local_status"] == "FAIL"
    assert result["termination"] == "EXECUTION_ERROR"
    assert result["exit_code"] is None


def test_unignored_output_root_blocks_execution(
    checkout: tuple[Path, str], tmp_path: Path,
) -> None:
    """The helper will not publish evidence into a Git-visible directory."""
    repo, revision = checkout
    (repo / ".gitignore").write_text("other-root/\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", ".gitignore"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "new ignore"], check=True)
    new_revision = subprocess.check_output(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], text=True,
    ).strip()
    assert new_revision != revision
    request = request_for(new_revision)
    path = tmp_path / "request.json"
    path.write_bytes(canonical_bytes(request))
    with pytest.raises(HandoffError, match="not Git-ignored"):
        execute(path, repo, request["request_id"])


def test_protected_root_symlink_blocks_execution(
    checkout: tuple[Path, str], tmp_path: Path,
) -> None:
    """A symlinked data root cannot redirect output to another directory."""
    repo, revision = checkout
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (repo / ".signalforge-data").symlink_to(elsewhere, target_is_directory=True)
    request = request_for(revision)
    path = tmp_path / "request.json"
    path.write_bytes(canonical_bytes(request))
    with pytest.raises(HandoffError, match="symlink"):
        execute(path, repo, request["request_id"])
    assert list(elsewhere.iterdir()) == []
