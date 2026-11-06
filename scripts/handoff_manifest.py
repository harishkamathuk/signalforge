"""Manifest sanitized /tmp handoff files for operator-approved Google Drive transfer.

This utility never executes an agent, sanitizes content, or uploads files.
Human review of every staged file is required before Codex transfers it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

MANIFEST = "sha256-manifest.json"
TASK_DIR = re.compile(r"signalforge-[a-z0-9][a-z0-9-]{2,63}")
SAFE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")
SUFFIXES = {".md", ".txt", ".json"}
MAX_FILES = 20
MAX_FILE_BYTES = 1_048_576
MAX_TOTAL_BYTES = 4_194_304


class HandoffError(ValueError):
    """Handoff files or integrity manifest violate the bounded contract."""


def _directory(path: Path) -> Path:
    """Restrict transfer staging to a direct, non-symlink /tmp directory."""
    if path.parent != Path("/tmp") or not TASK_DIR.fullmatch(path.name):
        raise HandoffError("directory must be /tmp/signalforge-<task-id>")
    if path.is_symlink() or not path.is_dir():
        raise HandoffError("staging directory missing or symlinked")
    return path


def _files(folder: Path) -> list[Path]:
    """List small, regular, operator-reviewed candidate transfer files."""
    files: list[Path] = []
    total = 0
    for path in sorted(folder.iterdir()):
        if path.name == MANIFEST:
            continue
        if (
            not SAFE_NAME.fullmatch(path.name)
            or path.suffix not in SUFFIXES
            or path.is_symlink()
            or not path.is_file()
        ):
            raise HandoffError(f"unsafe file in staging directory: {path.name}")
        length = path.stat().st_size
        total += length
        if length > MAX_FILE_BYTES or total > MAX_TOTAL_BYTES:
            raise HandoffError("handoff exceeds byte limit")
        files.append(path)
        if len(files) > MAX_FILES:
            raise HandoffError("handoff exceeds file limit")
    if not files or not (folder / "report.md").is_file():
        raise HandoffError("handoff requires report.md and at least one file")
    return files


def _entries(files: list[Path]) -> list[dict[str, Any]]:
    return [
        {
            "name": path.name,
            "bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        for path in files
    ]


def create(folder: Path) -> Path:
    """Write a manifest once; existing manifests are never overwritten."""
    folder = _directory(folder)
    if (folder / MANIFEST).exists() or (folder / MANIFEST).is_symlink():
        raise HandoffError("manifest already exists; use a new task directory")
    entries = _entries(_files(folder))
    data = {"version": 1, "task_id": folder.name, "files": entries}
    manifest = folder / MANIFEST
    # Exclusive creation prevents silently changing an already shared identity.
    with manifest.open("x", encoding="utf-8") as stream:
        json.dump(data, stream, sort_keys=True, indent=2)
        stream.write("\n")
    return manifest


def verify(folder: Path) -> None:
    """Verify file names, byte lengths and SHA-256s before/after transport."""
    folder = _directory(folder)
    manifest = folder / MANIFEST
    if manifest.is_symlink() or not manifest.is_file():
        raise HandoffError("manifest missing or symlinked")
    if manifest.stat().st_size > 8192:
        raise HandoffError("manifest too large")
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise HandoffError("invalid manifest JSON") from exc
    if (
        not isinstance(data, dict)
        or set(data) != {"version", "task_id", "files"}
        or type(data["version"]) is not int
        or data["version"] != 1
        or data["task_id"] != folder.name
        or not isinstance(data["files"], list)
    ):
        raise HandoffError("manifest contract mismatch")
    expected = _entries(_files(folder))
    if data["files"] != expected:
        raise HandoffError("staged files differ from SHA-256 manifest")


def main() -> int:
    """Operate a local manifest only; never communicate with Google Drive."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("create", "verify"))
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    try:
        if args.action == "create":
            path = create(args.directory)
            print(f"manifest={path}")
        else:
            verify(args.directory)
            print("SHA256_VERIFIED")
    except (HandoffError, OSError) as exc:
        parser.exit(1, f"BLOCKED: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
