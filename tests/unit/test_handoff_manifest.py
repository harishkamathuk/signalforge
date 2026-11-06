"""Tests for SF-247 manual /tmp handoff manifest and transport integrity."""

from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path

import pytest

from scripts.handoff_manifest import HandoffError, create, verify


@pytest.fixture
def staging() -> Path:
    """Create a disposable, uniquely named, direct child of /tmp."""
    folder = Path("/tmp") / f"signalforge-test-{uuid.uuid4().hex}"
    folder.mkdir(mode=0o700)
    try:
        yield folder
    finally:
        shutil.rmtree(folder)


def test_create_and_verify(staging: Path) -> None:
    """A real content digest verifies without any service credentials."""
    (staging / "report.md").write_text(
        "Task: SF-247\nAgent: OpenCode\nGit HEAD: example\n",
        encoding="utf-8",
    )
    (staging / "test-summary.txt").write_text("PASS\n", encoding="utf-8")
    manifest = create(staging)
    data = json.loads(manifest.read_text(encoding="utf-8"))
    assert data["version"] == 1
    assert [entry["name"] for entry in data["files"]] == [
        "report.md", "test-summary.txt",
    ]
    verify(staging)


def test_write_once(staging: Path) -> None:
    """Existing signed-off evidence identity is not silently replaced."""
    (staging / "report.md").write_text("ready\n", encoding="utf-8")
    original = create(staging).read_bytes()
    with pytest.raises(HandoffError, match="already exists"):
        create(staging)
    assert (staging / "sha256-manifest.json").read_bytes() == original


def test_detects_changed_bytes_or_extra_file(staging: Path) -> None:
    """Any change in transferred files invalidates the manifest."""
    report = staging / "report.md"
    report.write_text("original\n", encoding="utf-8")
    create(staging)
    report.write_text("changed\n", encoding="utf-8")
    with pytest.raises(HandoffError, match="differ"):
        verify(staging)
    report.write_text("original\n", encoding="utf-8")
    (staging / "other.txt").write_text("unexpected\n", encoding="utf-8")
    with pytest.raises(HandoffError, match="differ"):
        verify(staging)


def test_missing_report_rejected(staging: Path) -> None:
    """Every transfer must include a human-readable report."""
    (staging / "other.txt").write_text("not a report", encoding="utf-8")
    with pytest.raises(HandoffError, match="requires report.md"):
        create(staging)


def test_secret_filename_and_symlink_rejected(staging: Path) -> None:
    """Never silently include obvious secret filenames or symlink targets."""
    (staging / "report.md").write_text("safe\n", encoding="utf-8")
    (staging / "credentials.key").write_text("secret\n", encoding="utf-8")
    with pytest.raises(HandoffError, match="unsafe"):
        create(staging)
    (staging / "credentials.key").unlink()
    (staging / "alias.txt").symlink_to(staging / "report.md")
    with pytest.raises(HandoffError, match="unsafe"):
        create(staging)


def test_oversized_file_rejected(staging: Path) -> None:
    """Large accidental logs/market exports do not enter the transfer set."""
    (staging / "report.md").write_bytes(b"a" * (1_048_576 + 1))
    with pytest.raises(HandoffError, match="byte limit"):
        create(staging)


def test_directory_must_be_directly_under_tmp(tmp_path: Path) -> None:
    """No arbitrary directory or protected data root is accepted."""
    folder = tmp_path / "signalforge-task"
    folder.mkdir()
    (folder / "report.md").write_text("safe\n", encoding="utf-8")
    with pytest.raises(HandoffError, match="directory must be"):
        create(folder)


def test_manifest_tamper_rejected(staging: Path) -> None:
    """Declared task identity and file digests must match actual bytes."""
    (staging / "report.md").write_text("safe\n", encoding="utf-8")
    manifest = create(staging)
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["files"][0]["sha256"] = "0" * 64
    manifest.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(HandoffError, match="differ"):
        verify(staging)
