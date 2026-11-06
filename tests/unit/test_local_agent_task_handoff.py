"""Adversarial tests for the supervised-agent task package boundary."""

from __future__ import annotations

import subprocess

import pytest

from scripts.local_agent_task_handoff import (
    CLASSIFICATION,
    HandoffError,
    canonical_bytes,
    digest,
    load_json,
    make_task,
    seal_report,
    validate_report,
    validate_task,
)


def task() -> dict[str, object]:
    """Produce a test-only, non-executable local agent work package."""
    return make_task(
        task_id="sf247-supervised-pilot-001",
        issue=247,
        base_revision="a" * 40,
        task="Update one documentation example and run focused checks without network access.",
        allowed_paths=["docs/validation/sf247-pilot.md"],
        acceptance=["Documentation change is reviewable", "Focused checks exit zero"],
    )


def report_for(t: dict[str, object]) -> dict[str, object]:
    """Produce a declared, sanitized report linked to a task."""
    report: dict[str, object] = {
        "version": 1,
        "task_id": t["task_id"],
        "task_sha256": t["task_sha256"],
        "repository": t["repository"],
        "base_revision": t["base_revision"],
        "observed_base_revision": t["base_revision"],
        "observed_head_revision": "b" * 40,
        "agent": t["agent"],
        "changed_files": ["docs/validation/sf247-pilot.md"],
        "checks": [{"name": "focused docs check", "status": "PASS", "exit_code": 0}],
        "operator_approvals": [],
        "findings": [],
        "classification": CLASSIFICATION,
        "local_status": "PASS",
    }
    report["report_sha256"] = digest(report, "report_sha256")
    return report


def test_task_report_roundtrip() -> None:
    """Contract digests match without claiming real agent acceptance."""
    t = task()
    validate_task(t)
    report = report_for(t)
    validate_report(report, t)
    assert canonical_bytes(t) == canonical_bytes(t)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("repository", "not/signalforge", "repository"),
        ("agent", "unattended-daemon", "agent mode"),
        ("base_revision", "develop", "base SHA"),
        ("classification", "RAW_MARKET_DATA", "classification"),
        ("allowed_paths", ["../.env"], "unsafe"),
        ("allowed_paths", [".signalforge-data/evidence"], "unsafe"),
        ("allowed_paths", ["docs/../secrets.txt"], "unsafe"),
        ("allowed_paths", ["docs/a.md", "docs/a.md"], "unsafe"),
        ("permissions", {"mode": "UNATTENDED"}, "permissions"),
        ("acceptance", [], "acceptance"),
    ],
)
def test_task_policy_rejects_broadened_scope(
    field: str, value: object, message: str,
) -> None:
    """A rehashed task still cannot widen the approved security boundary."""
    t = task()
    t[field] = value
    t["task_sha256"] = digest(t, "task_sha256")
    with pytest.raises(HandoffError, match=message):
        validate_task(t)


def test_tampering_rejected() -> None:
    """Task changes invalidate digest when no new digest was approved."""
    t = task()
    t["issue"] = 248
    with pytest.raises(HandoffError, match="tampered"):
        validate_task(t)


def test_report_rejects_out_of_scope_edit() -> None:
    """A published report cannot claim a PASS with out-of-scope paths."""
    t = task()
    r = report_for(t)
    r["changed_files"] = ["signalforge/trading/orders.py"]
    r["report_sha256"] = digest(r, "report_sha256")
    with pytest.raises(HandoffError, match="out-of-scope"):
        validate_report(r, t)


def test_report_rejects_forged_base_and_failed_check() -> None:
    """Reject contradictory Git provenance and successful status claims."""
    t = task()
    r = report_for(t)
    r["observed_base_revision"] = "c" * 40
    r["report_sha256"] = digest(r, "report_sha256")
    with pytest.raises(HandoffError, match="unexpected Git revision"):
        validate_report(r, t)
    r = report_for(t)
    r["checks"] = [{"name": "focused docs check", "status": "FAIL", "exit_code": 1}]
    r["report_sha256"] = digest(r, "report_sha256")
    with pytest.raises(HandoffError, match="PASS without"):
        validate_report(r, t)


def test_report_digest_tamper_and_identity() -> None:
    """Verification rejects any modification of linked task or report."""
    t = task()
    r = report_for(t)
    r["findings"] = ["unexpected failures"]
    with pytest.raises(HandoffError, match="digest"):
        validate_report(r, t)
    r = report_for(t)
    r["task_sha256"] = "0" * 64
    r["report_sha256"] = digest(r, "report_sha256")
    with pytest.raises(HandoffError, match="identity"):
        validate_report(r, t)


def test_duplicate_json_keys_rejected(tmp_path) -> None:
    """Duplicate JSON keys cannot silently override trusted task fields."""
    path = tmp_path / "tampered.json"
    path.write_text('{"version":1,"version":2}', encoding="utf-8")
    with pytest.raises(HandoffError, match="duplicate JSON key"):
        load_json(path)


def test_symlinked_package_rejected(tmp_path) -> None:
    """Transport may not redirect a verifier through an arbitrary symlink."""
    target = tmp_path / "package.json"
    target.write_bytes(canonical_bytes(task()))
    alias = tmp_path / "alias.json"
    alias.symlink_to(target)
    with pytest.raises(HandoffError, match="linked"):
        load_json(alias)


def test_seal_report_write_once_and_ignored(tmp_path) -> None:
    """Sealed evidence stays private and can never overwrite its first result."""
    repo = tmp_path / "checkout"
    repo.mkdir()
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
    (repo / ".gitignore").write_text(".signalforge-data/\\n", encoding="utf-8")
    t = task()
    task_path = tmp_path / "task.json"
    task_path.write_bytes(canonical_bytes(t) + b"\\n")
    report_path = tmp_path / "candidate.json"
    report_path.write_bytes(canonical_bytes(report_for(t)) + b"\\n")
    sealed = seal_report(repo=repo, task_path=task_path, candidate_path=report_path)
    assert sealed.is_file()
    assert sealed.read_bytes() == report_path.read_bytes()
    with pytest.raises(FileExistsError):
        seal_report(repo=repo, task_path=task_path, candidate_path=report_path)
