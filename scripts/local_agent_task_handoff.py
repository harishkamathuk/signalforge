"""Validate source-controlled SF-247 supervised coding-agent handoff packages.

A task package describes an explicitly approved local-agent job. This module
does not launch an agent, execute a command, access protected data, or upload
anything to Google Drive.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from scripts.local_execution_evidence import (
    REPOSITORY,
    HandoffError,
    canonical_bytes,
    digest,
    validate_checkout,
    write_once,
)

VERSION = 1
TASK_KEYS = {
    "version", "task_id", "issue", "repository", "base_revision",
    "agent", "task", "allowed_paths", "acceptance", "permissions",
    "classification", "task_sha256",
}
REPORT_KEYS = {
    "version", "task_id", "task_sha256", "repository", "base_revision",
    "observed_base_revision", "observed_head_revision", "agent",
    "changed_files", "checks", "operator_approvals", "findings",
    "classification", "local_status", "report_sha256",
}
TASK_ID_RE = re.compile(r"^sf247-[a-z0-9][a-z0-9-]{5,55}$")
SHA_RE = re.compile(r"^[a-f0-9]{40}$")
HASH_RE = re.compile(r"^[a-f0-9]{64}$")
SAFE_PATH_RE = re.compile(r"^(?:docs|tests)/[A-Za-z0-9_./-]+$")
MAX_BYTES = 16384
MAX_PATHS = 12
PERMISSIONS = {
    "mode": "SUPERVISED",
    "allowed": ["scoped_source_edits", "focused_tests", "read_only_git"],
    "approval_required": [
        "dependency_install", "network_access", "git_push", "pull_request_changes",
        "protected_data_access", "database_changes", "destructive_git",
        "out_of_scope_edits",
    ],
    "prohibited": [
        "live_or_paper_orders", "credential_export", "raw_market_data_export",
        "qualification_guard_change", "unapproved_strategy_change",
        "unattended_agent",
    ],
}
CLASSIFICATION = "SANITIZED_AGENT_HANDOFF"


def _is_safe_path(value: Any) -> bool:
    """Forbid traversal, hidden paths, absolute roots and protected locations."""
    if not isinstance(value, str) or not SAFE_PATH_RE.fullmatch(value):
        return False
    return all(segment not in ("", ".", "..") for segment in value.split("/"))


def _checked_strings(values: Any, *, limit: int, length: int) -> bool:
    return (
        isinstance(values, list)
        and 0 < len(values) <= limit
        and all(isinstance(v, str) and 0 < len(v) <= length for v in values)
    )


def validate_task(obj: dict[str, Any]) -> None:
    """Validate the precise, intentionally narrow supervised-task contract."""
    if set(obj) != TASK_KEYS or type(obj["version"]) is not int or obj["version"] != VERSION:
        raise HandoffError("unsupported or incomplete task contract")
    if not isinstance(obj["task_id"], str) or not TASK_ID_RE.fullmatch(obj["task_id"]):
        raise HandoffError("invalid task ID")
    if type(obj["issue"]) is not int or obj["issue"] <= 0:
        raise HandoffError("invalid issue reference")
    if obj["repository"] != REPOSITORY:
        raise HandoffError("incorrect repository identity")
    if not isinstance(obj["base_revision"], str) or not SHA_RE.fullmatch(obj["base_revision"]):
        raise HandoffError("exact base SHA required")
    if obj["agent"] != "operator-selected-local-coding-agent":
        raise HandoffError("unsupported agent mode")
    if not isinstance(obj["task"], str) or not 24 <= len(obj["task"]) <= 1500:
        raise HandoffError("task instructions missing or too long")
    if any(ord(ch) < 32 and ch not in "\n\t" for ch in obj["task"]):
        raise HandoffError("invalid task control characters")
    paths = obj["allowed_paths"]
    if (
        not isinstance(paths, list) or not 1 <= len(paths) <= MAX_PATHS
        or len(set(paths)) != len(paths) or not all(map(_is_safe_path, paths))
    ):
        raise HandoffError("unsafe or ambiguous allowed paths")
    if not _checked_strings(obj["acceptance"], limit=12, length=200):
        raise HandoffError("missing bounded acceptance conditions")
    if obj["permissions"] != PERMISSIONS:
        raise HandoffError("permissions must equal approved supervised scope")
    if obj["classification"] != CLASSIFICATION:
        raise HandoffError("unapproved classification")
    if not isinstance(obj["task_sha256"], str) or not HASH_RE.fullmatch(obj["task_sha256"]):
        raise HandoffError("invalid task digest")
    if obj["task_sha256"] != digest(obj, "task_sha256"):
        raise HandoffError("tampered task package")


def load_json(path: Path, expected_size: int = MAX_BYTES) -> dict[str, Any]:
    """Load a small regular JSON file, rejecting duplicate and unsafe keys."""
    if path.is_symlink() or not path.is_file() or path.stat().st_size > expected_size:
        raise HandoffError("missing, linked or oversized package")
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise HandoffError("duplicate JSON key")
            result[key] = value
        return result
    try:
        data = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=pairs)
    except (ValueError, UnicodeError) as exc:
        raise HandoffError("invalid JSON package") from exc
    if not isinstance(data, dict):
        raise HandoffError("package must be a JSON object")
    return data


def make_task(
    *,
    task_id: str,
    issue: int,
    base_revision: str,
    task: str,
    allowed_paths: list[str],
    acceptance: list[str],
) -> dict[str, Any]:
    """Build a task package without granting the receiver execution authority."""
    data: dict[str, Any] = {
        "version": VERSION, "task_id": task_id, "issue": issue,
        "repository": REPOSITORY, "base_revision": base_revision,
        "agent": "operator-selected-local-coding-agent",
        "task": task, "allowed_paths": allowed_paths, "acceptance": acceptance,
        "permissions": PERMISSIONS, "classification": CLASSIFICATION,
    }
    data["task_sha256"] = digest(data, "task_sha256")
    validate_task(data)
    return data


def validate_report(report: dict[str, Any], task: dict[str, Any]) -> None:
    """Validate a *sanitized operator declaration*, not attest an agent sandbox.

    Report integrity cannot independently certify execution, approvals, or
    source preservation. Corroborate its fields against actual Git and test
    evidence before recording readiness.
    """
    validate_task(task)
    if (
        set(report) != REPORT_KEYS
        or type(report["version"]) is not int
        or report["version"] != VERSION
    ):
        raise HandoffError("unsupported agent report contract")
    for key, source in (
        ("task_id", "task_id"), ("task_sha256", "task_sha256"),
        ("repository", "repository"), ("base_revision", "base_revision"),
        ("agent", "agent"), ("classification", "classification"),
    ):
        if report[key] != task[source]:
            raise HandoffError("report/task identity mismatch")
    for field in ("observed_base_revision", "observed_head_revision"):
        if not isinstance(report[field], str) or not SHA_RE.fullmatch(report[field]):
            raise HandoffError("invalid observed Git SHA")
    if report["observed_base_revision"] != task["base_revision"]:
        raise HandoffError("agent started at unexpected Git revision")
    changed = report["changed_files"]
    if (
        not isinstance(changed, list)
        or len(changed) > MAX_PATHS
        or len(set(changed)) != len(changed)
    ):
        raise HandoffError("invalid changed-file listing")
    if any(not _is_safe_path(p) or p not in task["allowed_paths"] for p in changed):
        raise HandoffError("agent claims out-of-scope changes")
    if not isinstance(report["checks"], list) or len(report["checks"]) > 12:
        raise HandoffError("invalid checks")
    for entry in report["checks"]:
        if not isinstance(entry, dict) or set(entry) != {"name", "status", "exit_code"}:
            raise HandoffError("invalid check entry")
        if (
            not isinstance(entry["name"], str) or not 0 < len(entry["name"]) <= 100
            or entry["status"] not in ("PASS", "FAIL", "NOT_RUN")
            or not (entry["exit_code"] is None or type(entry["exit_code"]) is int)
        ):
            raise HandoffError("invalid test evidence")
        if entry["status"] == "PASS" and entry["exit_code"] != 0:
            raise HandoffError("contradictory PASS check")
    if (
        not _checked_strings(report["operator_approvals"], limit=12, length=120)
        and report["operator_approvals"] != []
    ):
        raise HandoffError("invalid operator approval declarations")
    if not isinstance(report["findings"], list) or len(report["findings"]) > 12 or any(
        not isinstance(v, str) or len(v) > 200 for v in report["findings"]
    ):
        raise HandoffError("invalid findings")
    if report["local_status"] not in ("PASS", "FAIL", "BLOCKED"):
        raise HandoffError("invalid local status")
    if report["local_status"] == "PASS" and (
        not changed or not report["checks"] or
        any(c["status"] != "PASS" for c in report["checks"])
    ):
        raise HandoffError("PASS without changed files and passing checks")
    if (
        not isinstance(report["report_sha256"], str)
        or not HASH_RE.fullmatch(report["report_sha256"])
        or report["report_sha256"] != digest(report, "report_sha256")
    ):
        raise HandoffError("invalid agent report digest")


def _root(repo: Path) -> Path:
    base = repo / ".signalforge-data"
    if base.is_symlink():
        raise HandoffError("protected root may not be symlink")
    folder = base / "handoff" / "agent-tasks"
    if any(p.is_symlink() for p in (base / "handoff", folder)):
        raise HandoffError("protected path may not contain symlinks")
    check = subprocess.run(
        ["git", "-C", str(repo), "check-ignore", "-q",
         ".signalforge-data/handoff/agent-tasks/probe.json"],
        capture_output=True, check=False, timeout=10,
    )
    if check.returncode != 0:
        raise HandoffError("task package directory is not ignored by Git")
    folder.mkdir(parents=True, mode=0o700, exist_ok=True)
    return folder


def main() -> int:
    """Provide package preparation and validation, never execute a coding agent."""
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    prepare = sub.add_parser("prepare")
    prepare.add_argument("--repo", required=True, type=Path)
    prepare.add_argument("--task-id", required=True)
    prepare.add_argument("--issue", required=True, type=int)
    prepare.add_argument("--task-file", required=True, type=Path)
    prepare.add_argument("--allowed-path", required=True, action="append")
    prepare.add_argument("--acceptance", required=True, action="append")
    inspect = sub.add_parser("verify")
    inspect.add_argument("--task", required=True, type=Path)
    inspect.add_argument("--report", type=Path)
    args = parser.parse_args()
    try:
        if args.action == "prepare":
            repo = args.repo.resolve()
            head = subprocess.check_output(
                ["git", "-C", str(repo), "rev-parse", "HEAD"],
                text=True, timeout=10,
            ).strip()
            validate_checkout(repo, head)
            source = args.task_file
            if source.is_symlink() or not source.is_file() or source.stat().st_size > 1500:
                raise HandoffError("task instructions must be a small local regular file")
            task = make_task(
                task_id=args.task_id, issue=args.issue, base_revision=head,
                task=source.read_text(encoding="utf-8"),
                allowed_paths=args.allowed_path,
                acceptance=args.acceptance,
            )
            folder = _root(repo)
            target = folder / f"{args.task_id}.json"
            write_once(target, canonical_bytes(task) + b"\n")
            print(f"task_sha256={task['task_sha256']}")
            print(f"local_task={target}")
        else:
            task = load_json(args.task)
            validate_task(task)
            if args.report:
                report = load_json(args.report)
                validate_report(report, task)
                print(f"verified_report_sha256={report['report_sha256']}")
            else:
                print(f"verified_task_sha256={task['task_sha256']}")
    except (HandoffError, OSError, subprocess.SubprocessError, UnicodeError) as exc:
        parser.exit(1, f"BLOCKED: {exc}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
