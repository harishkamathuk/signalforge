"""SF-095 offline raw-input protections; no real provider data or network."""

from pathlib import Path

import pytest

from signalforge.research import btc_raw_diagnostic_input as source


def test_protected_source_path_and_missing_evidence_fail_closed(tmp_path: Path):
    other = tmp_path / "generation-0001"
    other.mkdir()
    with pytest.raises(ValueError, match="protected"):
        source.load_sf095_raw_diagnostic_source(other)
    protected = tmp_path / ".signalforge-data" / "sf088" / "evidence-only" / "generation-0001"
    protected.mkdir(parents=True)
    with pytest.raises(FileNotFoundError):
        source.load_sf095_raw_diagnostic_source(protected)


def test_frozen_identity_mismatch_rejected_before_materialization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    protected = tmp_path / ".signalforge-data" / "sf088" / "evidence-only" / "generation-0001"
    protected.mkdir(parents=True)
    monkeypatch.setattr(source, "explore_generation", lambda _: {
        "report_sha256": "bad-report",
        "derived_price_diagnostics": {
            "five_minute_close_sha256": source.FROZEN_FIVE_MINUTE_CLOSE_SHA256
        },
        "historical_metadata_status": "UNQUALIFIED_HISTORICAL_METADATA",
        "canonical_dataset_published": False,
        "independent_audit_status": "PASS_WITH_UNQUALIFIED_METADATA",
    })
    with pytest.raises(ValueError, match="frozen SF-094"):
        source.load_sf095_raw_diagnostic_source(protected)
