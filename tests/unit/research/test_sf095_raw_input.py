"""SF-095 offline raw-input protections; no real provider data or network."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

from signalforge.research.delta_historical_qualification import DeltaCandle, DeltaRawCapture

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


def test_offline_diagnostic_bridge_preserves_unrounded_raw_prices(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    """Small synthetic source exercises the full transient HistoricalBarDataset."""
    protected = tmp_path / ".signalforge-data" / "sf088" / "evidence-only" / "generation-0001"
    protected.mkdir(parents=True)
    start = datetime(2025, 10, 30, tzinfo=UTC)
    end = start + timedelta(minutes=5)
    monkeypatch.setattr(source, "SF088_START", start)
    monkeypatch.setattr(source, "SF088_END", end)
    monkeypatch.setattr(source, "SF088_EXPECTED_MINUTES", 5)
    monkeypatch.setattr(source, "FROZEN_PROVISIONAL_REPORT_SHA256", "test-report")
    monkeypatch.setattr(source, "FROZEN_FIVE_MINUTE_CLOSE_SHA256", "test-close")
    monkeypatch.setattr(source, "build_sf088_chunk_plan", lambda: (
        SimpleNamespace(index=0),
    ))
    monkeypatch.setattr(source, "explore_generation", lambda _: {
        "report_sha256": "test-report",
        "derived_price_diagnostics": {"five_minute_close_sha256": "test-close"},
        "historical_metadata_status": "UNQUALIFIED_HISTORICAL_METADATA",
        "canonical_dataset_published": False,
        "independent_audit_status": "PASS_WITH_UNQUALIFIED_METADATA",
    })
    content = b"test-raw-capture"
    digest = sha256(content).hexdigest()
    (protected / "evidence-only-report.json").write_text(
        '{"first_pass_raw_sha256":["' + digest +
        '"],"first_pass_semantic_sha256":["test-semantic"]}',
        encoding="utf-8",
    )
    capture = DeltaRawCapture(
        request_url="https://api.india.delta.exchange/v2/history/candles",
        acquired_at=start,
        content_sha256=digest,
        content=content,
    )
    monkeypatch.setattr(
        source, "_load_capture",
        lambda raw, meta: (capture, {"semantic_sha256": "test-semantic"}),
    )
    candles = tuple(
        DeltaCandle(
            time=int(start.timestamp()) + i * 60,
            open=Decimal("100.03"), high=Decimal("100.04"),
            low=Decimal("100.02"), close=Decimal("100.03"), volume=Decimal("2"),
        )
        for i in range(5)
    )
    monkeypatch.setattr(source, "parse_delta_candles_response", lambda _: candles)
    monkeypatch.setattr(source, "_candle_semantic_sha256", lambda _: "test-semantic")
    evidence = source.load_sf095_raw_diagnostic_source(protected)
    assert not evidence.execution_valid
    assert evidence.source_diagnostic_id == "test-report"
    assert evidence.dataset.manifest.price_basis.value == "traded"
    assert evidence.dataset.manifest.missing_interval_count == 0
    assert len(evidence.dataset.bars) == 5
    assert evidence.dataset.bars[0].open.value == Decimal("100.03")
    assert "UNQUALIFIED_HISTORICAL_METADATA" in evidence.dataset.manifest.limitations
    assert not (protected / "canonical-dataset.json").exists()
