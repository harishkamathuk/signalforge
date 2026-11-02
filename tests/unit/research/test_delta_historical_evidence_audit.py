"""Focused regression coverage for SF-088 read-only evidence audit."""
from __future__ import annotations

import json
from datetime import timedelta

import pytest

from signalforge.research import delta_historical_dataset_acquisition as acquisition
from signalforge.research import delta_historical_evidence_audit as audit


def test_missing_evidence_fails(tmp_path) -> None:
    with pytest.raises(FileNotFoundError):
        audit.audit_generation(tmp_path / "missing")


def test_tampered_report_fails_before_reading_chunks(tmp_path, monkeypatch) -> None:
    start = acquisition.SF088_START
    plan = acquisition.build_sf088_chunk_plan(
        start=start, end=start + timedelta(minutes=1), chunk_minutes=1,
    )
    monkeypatch.setattr(audit, "build_sf088_chunk_plan", lambda: plan)
    folder = tmp_path / "evidence"
    folder.mkdir()
    (folder / "evidence-only-report.json").write_text(
        json.dumps({"report_sha256": "invalid"}), encoding="utf-8",
    )
    with pytest.raises(ValueError, match="report digest mismatch"):
        audit.audit_generation(folder)


def test_cli_refuses_to_overwrite(tmp_path) -> None:
    folder = tmp_path / "generation"
    folder.mkdir()
    output = tmp_path / "existing.json"
    output.write_text("{}")
    with pytest.raises(SystemExit):
        audit.main(["--generation-dir", str(folder), "--output", str(output)])


def test_cli_refuses_to_write_within_generation(tmp_path) -> None:
    folder = tmp_path / "generation"
    folder.mkdir()
    with pytest.raises(SystemExit):
        audit.main(["--generation-dir", str(folder), "--output", str(folder / "audit.json")])
