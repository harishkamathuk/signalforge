"""Bounded, operator-approved SF-247 local execution evidence handoff.

This helper deliberately permits only the offline Python-version smoke test.
Google Drive transport and GitHub publication are independent operator actions.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CONTRACT_VERSION = 1
REPOSITORY = "harishkamathuk/signalforge"
ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{7,63}$")
SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
HEX256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
ALLOWED_REQUEST_KEYS = {
    "version", "request_id", "issue", "repository", "revision",
    "argv", "classification", "request_sha256",
}
ALLOWED_REPORT_KEYS = {
    "version", "request_id", "request_sha256", "issue", "repository",
    "revision", "argv", "started_utc", "finished_utc", "exit_code",
    "termination", "output", "output_sha256", "local_status",
    "transport_status", "classification", "report_sha256",
}
MAX_REQUEST_BYTES = 8192
MAX_OUTPUT_BYTES = 512
TIMEOUT_SECONDS = 10


class HandoffError(ValueError):
    """A request, local environment or output boundary is unsafe."""


def canonical_bytes(payload: dict[str, Any]) -> bytes:
    """Serialize a contract deterministically as canonical UTF-8 JSON.

    Hashing excludes the matching self-hash field; encoded JSON contains no
    insignificant whitespace and all keys are lexically ordered.
    """
    return json.dumps(
        payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def digest(payload: dict[str, Any], hash_field: str) -> str:
    """Calculate the SHA-256 identity excluding its own identity field."""
    return hashlib.sha256(
        canonical_bytes({k: v for k, v in payload.items() if k != hash_field})
    ).hexdigest()


def utc_now() -> str:
    """Return an unambiguous UTC timestamp with explicit UTC offset."""
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _read_request(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise HandoffError("request must be a regular, non-symlink file")
    if path.stat().st_size > MAX_REQUEST_BYTES:
        raise HandoffError("request exceeds maximum size")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeError) as exc:
        raise HandoffError("request is not valid UTF-8 JSON") from exc
    if not isinstance(data, dict) or set(data) != ALLOWED_REQUEST_KEYS:
        raise HandoffError("unexpected or missing request fields")
    return data


def validate_request(data: dict[str, Any]) -> None:
    """Reject ambiguous requests before any command or write is attempted."""
    if type(data["version"]) is not int or data["version"] != CONTRACT_VERSION:
        raise HandoffError("unsupported request contract version")
    if not isinstance(data["request_id"], str) or not ID_PATTERN.fullmatch(
        data["request_id"]
    ):
        raise HandoffError("invalid request ID")
    if type(data["issue"]) is not int or data["issue"] <= 0:
        raise HandoffError("issue must be a positive GitHub issue number")
    if data["repository"] != REPOSITORY:
        raise HandoffError("unexpected repository")
    if not isinstance(data["revision"], str) or not SHA_PATTERN.fullmatch(
        data["revision"]
    ):
        raise HandoffError("revision must be the exact lowercase 40-char SHA")
    if data["argv"] != ["python", "-V"]:
        raise HandoffError("only the offline python -V command is allowed")
    if data["classification"] != "SANITIZED_SMOKE_ONLY":
        raise HandoffError("unsupported evidence classification")
    if not isinstance(data["request_sha256"], str) or not HEX256_PATTERN.fullmatch(
        data["request_sha256"]
    ):
        raise HandoffError("invalid request hash")
    if data["request_sha256"] != digest(data, "request_sha256"):
        raise HandoffError("request hash mismatch")


def _git(repo: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), *args], check=True,
            capture_output=True, text=True, timeout=TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise HandoffError("unable to verify Git repository identity") from exc
    return result.stdout.strip()


def validate_checkout(repo: Path, revision: str) -> None:
    """Ensure the operator's working checkout is the exact requested revision."""
    if repo.is_symlink() or not repo.is_dir():
        raise HandoffError("invalid repository directory")
    root = _git(repo, "rev-parse", "--show-toplevel")
    if Path(root).resolve() != repo.resolve():
        raise HandoffError("execution must start at repository root")
    actual = _git(repo, "rev-parse", "HEAD")
    if actual != revision:
        raise HandoffError("local Git HEAD does not match request")
    remote = _git(repo, "remote", "get-url", "origin")
    if remote not in {
        "https://github.com/harishkamathuk/signalforge.git",
        "git@github.com:harishkamathuk/signalforge.git",
    }:
        raise HandoffError("Git origin does not match SignalForge")
    # A dirty checkout could execute altered local source despite matching HEAD.
    if _git(repo, "status", "--porcelain", "--untracked-files=no"):
        raise HandoffError("tracked working tree has uncommitted modifications")


def _output_dir(repo: Path) -> Path:
    """Choose a single Git-ignored root; do not accept paths from requests."""
    base = repo / ".signalforge-data"
    if base.is_symlink():
        raise HandoffError("protected data root may not be a symlink")
    out = base / "handoff" / "reports"
    for part in (base, base / "handoff", out):
        if part.is_symlink():
            raise HandoffError("protected report path contains a symlink")
    try:
        ignored = subprocess.run(
            ["git", "-C", str(repo), "check-ignore", "-q",
             ".signalforge-data/handoff/reports/probe.json"],
            check=False, timeout=TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise HandoffError("cannot verify Git exclusion") from exc
    if ignored.returncode != 0:
        raise HandoffError("output location is not Git-ignored")
    return out


def write_once(path: Path, data: bytes) -> None:
    """Create a private report exactly once without following a final symlink."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        # An incomplete report is never success; retain failed-write diagnosis
        # only via an exception and clean up the partial destination.
        path.unlink(missing_ok=True)
        raise


def execute(request_path: Path, repo: Path, approval: str) -> Path:
    """Run the sole authorized offline smoke test and write its local result.

    Args:
        request_path: Operator-inspected versioned request file.
        repo: Existing SignalForge checkout.
        approval: Exact request ID typed explicitly by the operator.

    Returns:
        Path to the exclusive, private and Git-ignored report file.

    Raises:
        HandoffError: Unsafe request, checkout or report location.
    """
    request = _read_request(request_path)
    validate_request(request)
    if approval != request["request_id"]:
        raise HandoffError("explicit operator approval does not match request")
    validate_checkout(repo, request["revision"])
    reports = _output_dir(repo)
    result_file = reports / f'{request["request_id"]}.json'
    if result_file.exists() or result_file.is_symlink():
        raise HandoffError("report already exists; request IDs cannot be reused")
    reports.mkdir(parents=True, exist_ok=True, mode=0o700)
    if reports.is_symlink():
        raise HandoffError("report directory changed into a symlink")
    started = utc_now()
    # No untrusted executable lookup: use the active Python interpreter, not PATH.
    # Python -V has no external-provider, market-data, DB or broker side effects.
    try:
        completed = subprocess.run(
            [sys.executable, "-V"], cwd=repo, capture_output=True,
            timeout=TIMEOUT_SECONDS, check=False,
        )
        raw = completed.stdout + completed.stderr
        if len(raw) > MAX_OUTPUT_BYTES:
            raise HandoffError("smoke output exceeds safe publication limit")
        output = raw.decode("ascii", errors="strict").strip()
        if not re.fullmatch(r"Python 3\.12\.\d+", output):
            raise HandoffError("unexpected Python version output; export blocked")
        exit_code: int | None = completed.returncode
        termination = "EXITED"
        status = "PASS" if exit_code == 0 else "FAIL"
    except (OSError, subprocess.TimeoutExpired, UnicodeError) as exc:
        output = ""
        exit_code = None
        termination = "TIMEOUT" if isinstance(
            exc, subprocess.TimeoutExpired
        ) else "EXECUTION_ERROR"
        status = "FAIL"
    finished = utc_now()
    report: dict[str, Any] = {
        "version": CONTRACT_VERSION,
        "request_id": request["request_id"],
        "request_sha256": request["request_sha256"],
        "issue": request["issue"],
        "repository": REPOSITORY,
        "revision": request["revision"],
        "argv": request["argv"],
        "started_utc": started,
        "finished_utc": finished,
        "exit_code": exit_code,
        "termination": termination,
        "output": output,
        "output_sha256": hashlib.sha256(output.encode("utf-8")).hexdigest(),
        "local_status": status,
        "transport_status": "NOT_ATTEMPTED",
        "classification": "SANITIZED_SMOKE_ONLY",
    }
    report["report_sha256"] = digest(report, "report_sha256")
    write_once(result_file, canonical_bytes(report) + b"\n")
    return result_file


def verify_report(path: Path, request_path: Path) -> dict[str, Any]:
    """Verify a downloaded report against the original request and hashes."""
    request = _read_request(request_path)
    validate_request(request)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 8192:
        raise HandoffError("invalid report file")
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeError, ValueError) as exc:
        raise HandoffError("invalid report JSON") from exc
    if not isinstance(report, dict) or set(report) != ALLOWED_REPORT_KEYS:
        raise HandoffError("invalid report fields")
    if report["version"] != CONTRACT_VERSION or report["classification"] != (
        "SANITIZED_SMOKE_ONLY"
    ):
        raise HandoffError("invalid report version/classification")
    for key in ("request_id", "request_sha256", "issue", "repository", "revision", "argv"):
        if report[key] != request[key]:
            raise HandoffError(f"request/report mismatch: {key}")
    if report["transport_status"] != "NOT_ATTEMPTED":
        raise HandoffError("transport status is not part of local execution evidence")
    if report["report_sha256"] != digest(report, "report_sha256"):
        raise HandoffError("report SHA-256 mismatch")
    if not isinstance(report["output"], str) or not re.fullmatch(
        r"Python 3\.12\.\d+|", report["output"]
    ):
        raise HandoffError("invalid sanitized output")
    if report["output_sha256"] != hashlib.sha256(
        report["output"].encode("utf-8")
    ).hexdigest():
        raise HandoffError("output hash mismatch")
    for key in ("started_utc", "finished_utc"):
        if not isinstance(report[key], str) or not report[key].endswith("+00:00"):
            raise HandoffError("timestamps must be explicit UTC")
    if report["local_status"] not in ("PASS", "FAIL"):
        raise HandoffError("invalid local status")
    if report["local_status"] == "PASS" and (
        report["exit_code"] != 0 or report["termination"] != "EXITED"
        or not report["output"].startswith("Python 3.12.")
    ):
        raise HandoffError("contradictory PASS report")
    return report


def main() -> int:
    """Operate the controlled local CLI; never initiate a Drive transfer."""
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    make = sub.add_parser("prepare", help="generate an untrusted request for operator review")
    make.add_argument("--issue", required=True, type=int)
    make.add_argument("--revision", required=True)
    make.add_argument("--request-id", required=True)
    make.add_argument("--output", required=True, type=Path)
    run = sub.add_parser("run", help="explicitly approve and execute a request")
    run.add_argument("--request", required=True, type=Path)
    run.add_argument("--repo", required=True, type=Path)
    run.add_argument("--approve-request-id", required=True)
    check = sub.add_parser("verify", help="validate a downloaded report")
    check.add_argument("--request", required=True, type=Path)
    check.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    try:
        if args.action == "prepare":
            obj: dict[str, Any] = {
                "version": CONTRACT_VERSION, "request_id": args.request_id,
                "issue": args.issue, "repository": REPOSITORY,
                "revision": args.revision, "argv": ["python", "-V"],
                "classification": "SANITIZED_SMOKE_ONLY",
            }
            obj["request_sha256"] = digest(obj, "request_sha256")
            validate_request(obj)
            # Requests too are created once; never overwrite operator intent.
            write_once(args.output, canonical_bytes(obj) + b"\n")
            print(f"request_sha256={obj['request_sha256']}")
        elif args.action == "run":
            result = execute(args.request, args.repo, args.approve_request_id)
            print(f"local_report={result}")
        else:
            result = verify_report(args.report, args.request)
            print(f"verified_report_sha256={result['report_sha256']}")
    except (HandoffError, OSError) as exc:
        parser.exit(1, f"BLOCKED: {exc}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
