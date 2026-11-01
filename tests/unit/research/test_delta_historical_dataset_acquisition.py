from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

import signalforge.research.delta_historical_dataset_acquisition as acquisition
from signalforge.research.delta_historical_dataset_acquisition import (
    DeltaAcquisitionPass,
    DeltaCapturedChunk,
    DeltaResearchChunk,
    assert_two_pass_coherence,
    build_sf088_chunk_plan,
    validate_product_applicability,
)
from signalforge.research.delta_historical_qualification import (
    DeltaProductSnapshot,
    DeltaRawCapture,
)


def _product(*, updated_at: datetime | None = None) -> DeltaProductSnapshot:
    return DeltaProductSnapshot(
        api_origin="https://api.india.delta.exchange",
        product_id=27,
        symbol="BTCUSD",
        contract_type="perpetual_futures",
        contract_value=Decimal("0.001"),
        contract_unit_currency="BTC",
        tick_size=Decimal("0.5"),
        underlying_asset_symbol="BTC",
        quoting_asset_symbol="USD",
        settling_asset_symbol="USD",
        raw_sha256="a" * 64,
        created_at=datetime(2023, 12, 18, 13, 10, 39, tzinfo=UTC),
        updated_at=updated_at or datetime(2024, 11, 15, 2, 47, 50, tzinfo=UTC),
    )


def test_sf088_chunk_plan_is_exact_and_deterministic() -> None:
    plan = build_sf088_chunk_plan()

    assert len(plan) == 263
    assert plan[0].start == acquisition.SF088_START
    assert plan[-1].end == acquisition.SF088_END
    assert sum(item.expected_minutes for item in plan) == 525_600
    assert plan[0].expected_minutes == 2_000
    assert plan[-1].expected_minutes == 1_600
    assert plan[0].provider_end == int(
        (plan[0].end - timedelta(minutes=1)).timestamp()
    )


def test_product_applicability_requires_snapshot_to_predate_research_window() -> None:
    digest = validate_product_applicability(_product())
    assert len(digest) == 64

    with pytest.raises(ValueError, match="effective-dated metadata"):
        validate_product_applicability(
            _product(updated_at=datetime(2026, 1, 1, tzinfo=UTC))
        )

    missing = _product()
    missing = DeltaProductSnapshot(
        api_origin=missing.api_origin,
        product_id=missing.product_id,
        symbol=missing.symbol,
        contract_type=missing.contract_type,
        contract_value=missing.contract_value,
        contract_unit_currency=missing.contract_unit_currency,
        tick_size=missing.tick_size,
        underlying_asset_symbol=missing.underlying_asset_symbol,
        quoting_asset_symbol=missing.quoting_asset_symbol,
        settling_asset_symbol=missing.settling_asset_symbol,
        raw_sha256=missing.raw_sha256,
    )
    with pytest.raises(ValueError, match="created_at/updated_at"):
        validate_product_applicability(missing)


def test_two_pass_coherence_detects_any_chunk_semantic_revision() -> None:
    start = acquisition.SF088_START
    chunk = DeltaResearchChunk(
        index=0,
        start=start,
        end=start + timedelta(minutes=1),
        provider_start=int(start.timestamp()),
        provider_end=int(start.timestamp()),
    )
    first_chunk = DeltaCapturedChunk(
        chunk=chunk,
        raw_sha256="1" * 64,
        semantic_sha256="2" * 64,
        row_count=1,
        duplicate_count=0,
        missing_count=0,
        request_url="https://example.test/1",
        acquired_at=datetime(2026, 10, 31, tzinfo=UTC),
    )
    first = DeltaAcquisitionPass("pass-1", _product(), (first_chunk,))
    second = DeltaAcquisitionPass(
        "pass-2",
        _product(),
        (first_chunk,),
    )
    assert_two_pass_coherence(first, second)

    revised = DeltaCapturedChunk(
        chunk=chunk,
        raw_sha256="3" * 64,
        semantic_sha256="4" * 64,
        row_count=1,
        duplicate_count=0,
        missing_count=0,
        request_url="https://example.test/2",
        acquired_at=datetime(2026, 10, 31, tzinfo=UTC),
    )
    with pytest.raises(ValueError, match="semantic revision"):
        assert_two_pass_coherence(
            first,
            DeltaAcquisitionPass("pass-2", _product(), (revised,)),
        )

    changed_applicability = _product(
        updated_at=datetime(2025, 1, 1, tzinfo=UTC)
    )
    with pytest.raises(ValueError, match="metadata applicability changed"):
        assert_two_pass_coherence(
            first,
            DeltaAcquisitionPass("pass-2", changed_applicability, (first_chunk,)),
        )


def test_acquisition_pass_is_resumable_without_reacquiring_existing_chunks(
    tmp_path, monkeypatch
) -> None:
    start = acquisition.SF088_START
    plan = build_sf088_chunk_plan(
        start=start,
        end=start + timedelta(minutes=2),
        chunk_minutes=1,
    )
    calls: list[str] = []

    product_payload = {
        "success": True,
        "result": {
            "id": 27,
            "symbol": "BTCUSD",
            "contract_type": "perpetual_futures",
            "contract_value": "0.001",
            "contract_unit_currency": "BTC",
            "tick_size": "0.5",
            "created_at": "2023-12-18T13:10:39Z",
            "updated_at": "2024-11-15T02:47:50Z",
            "underlying_asset": {"symbol": "BTC"},
            "quoting_asset": {"symbol": "USD"},
            "settling_asset": {"symbol": "USD"},
        },
    }

    def fake_acquire(path, *, params=None, api_origin=None, timeout_seconds=30.0):
        del api_origin, timeout_seconds
        calls.append(path)
        if path.startswith("/v2/products/"):
            payload = product_payload
        else:
            assert params is not None
            epoch = int(params["start"])
            payload = {
                "success": True,
                "result": [
                    {
                        "time": epoch,
                        "open": "65000.0",
                        "high": "65000.5",
                        "low": "64999.5",
                        "close": "65000.0",
                        "volume": "10",
                    }
                ],
            }
        content = json.dumps(payload, separators=(",", ":")).encode()
        return DeltaRawCapture(
            request_url=f"https://api.india.delta.exchange{path}",
            acquired_at=datetime(2026, 10, 31, tzinfo=UTC),
            content_sha256=hashlib.sha256(content).hexdigest(),
            content=content,
        )

    monkeypatch.setattr(acquisition, "acquire_delta_response", fake_acquire)
    first = acquisition.acquire_sf088_pass(
        output_dir=tmp_path,
        pass_name="pass-1",
        chunk_plan=plan,
    )
    assert len(first.chunks) == 2
    assert calls == [
        "/v2/products/BTCUSD",
        "/v2/history/candles",
        "/v2/history/candles",
    ]

    calls.clear()
    resumed = acquisition.acquire_sf088_pass(
        output_dir=tmp_path,
        pass_name="pass-1",
        chunk_plan=plan,
    )
    assert resumed.semantic_sha256 == first.semantic_sha256
    assert calls == []



def test_acquisition_evidence_does_not_change_semantic_dataset_identity() -> None:
    from dataclasses import replace
    from pathlib import Path

    from signalforge.research.historical_bars import load_historical_bar_fixture

    fixture = (
        Path(__file__).resolve().parents[3]
        / "examples/research/historical-bars-one-session.json"
    )
    dataset = load_historical_bar_fixture(fixture)
    altered = replace(
        dataset,
        manifest=replace(
            dataset.manifest,
            acquisition_evidence=("source_acquisition_run_manifest_sha256=" + "b" * 64,),
        ),
    )

    assert altered.dataset_id == dataset.dataset_id
    assert altered.manifest != dataset.manifest

def test_missing_minute_evidence_is_explicit_and_classified(monkeypatch) -> None:
    start = acquisition.SF088_START
    monkeypatch.setattr(acquisition, "SF088_END", start + timedelta(minutes=3))
    candle = acquisition.DeltaCandle(
        time=int(start.timestamp()),
        open=Decimal("65000.0"),
        high=Decimal("65000.5"),
        low=Decimal("64999.5"),
        close=Decimal("65000.0"),
        volume=Decimal("10"),
    )
    evidence = acquisition._missing_minute_evidence((candle,))

    assert len(evidence) == 2
    assert evidence[0]["classification"] == "unresolved_absence"
    assert evidence[0]["interval_start"] == (start + timedelta(minutes=1)).isoformat()



def test_offline_verification_is_only_ready_promotion_path(tmp_path, monkeypatch) -> None:
    from pathlib import Path

    from signalforge.research.historical_bars import load_historical_bar_fixture
    from signalforge.research.historical_dataset_store import LocalHistoricalDatasetStore

    fixture = (
        Path(__file__).resolve().parents[3]
        / "examples/research/historical-bars-one-session.json"
    )
    dataset = load_historical_bar_fixture(fixture)
    store_dir = tmp_path / "store"
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()

    real_store = LocalHistoricalDatasetStore(store_dir, parquet_min_rows=1)
    dataset_id = real_store.save(dataset)
    finalization = {
        "disposition": acquisition.DeltaResearchDisposition.PENDING_OFFLINE_VERIFICATION.value,
        "dataset_id": str(dataset_id),
        "offline_verification_required": True,
    }
    (evidence_dir / "sf088-finalization-report.json").write_text(
        json.dumps(finalization),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        acquisition,
        "LocalHistoricalDatasetStore",
        lambda root: LocalHistoricalDatasetStore(root, parquet_min_rows=1),
    )

    report = acquisition.verify_sf088_offline(
        evidence_dir=evidence_dir,
        store_dir=store_dir,
        dataset_id=dataset_id,
    )

    assert report["disposition"] == (
        acquisition.DeltaResearchDisposition.READY.value
    )
    assert report["offline_verification_required"] is False
    assert (evidence_dir / "sf088-offline-verification.json").exists()
    assert (evidence_dir / "sf088-final-report.json").exists()


def test_evidence_only_captures_missing_metadata_without_canonical_store(
    tmp_path, monkeypatch
) -> None:
    """Historical metadata absence must not block protected raw capture."""
    start = acquisition.SF088_START
    monkeypatch.setattr(acquisition, "SF088_END", start + timedelta(minutes=2))
    monkeypatch.setattr(acquisition, "SF088_EXPECTED_MINUTES", 2)
    original_plan = acquisition.build_sf088_chunk_plan
    tiny_plan = original_plan(
        start=start,
        end=start + timedelta(minutes=2),
        chunk_minutes=1,
    )
    monkeypatch.setattr(acquisition, "build_sf088_chunk_plan", lambda: tiny_plan)

    requests: list[str] = []

    def fake_request(path, *, params=None, **kwargs):
        del kwargs
        requests.append(path)
        if path.endswith("/BTCUSD"):
            body = {
                "success": True,
                "result": {
                    "id": 27,
                    "symbol": "BTCUSD",
                    "contract_type": "perpetual_futures",
                    "contract_value": "0.001",
                    "contract_unit_currency": "BTC",
                    "tick_size": "0.5",
                    "underlying_asset": {"symbol": "BTC"},
                    "quoting_asset": {"symbol": "USD"},
                    "settling_asset": {"symbol": "USD"},
                },
            }
        else:
            assert params is not None
            body = {
                "success": True,
                "result": [{
                    "time": int(params["start"]),
                    "open": "65000.1",
                    "high": "65000.1",
                    "low": "65000.1",
                    "close": "65000.1",
                    "volume": "1",
                }],
            }
        raw = json.dumps(body, separators=(",", ":")).encode()
        return DeltaRawCapture(
            request_url=f"https://api.india.delta.exchange{path}",
            acquired_at=datetime(2026, 11, 1, tzinfo=UTC),
            content_sha256=hashlib.sha256(raw).hexdigest(),
            content=raw,
        )

    monkeypatch.setattr(acquisition, "acquire_delta_response", fake_request)
    evidence = tmp_path / "evidence"
    report = acquisition.acquire_sf088_evidence_only(evidence_dir=evidence)
    assert report["disposition"] == "UNQUALIFIED_SOURCE_EVIDENCE"
    assert report["historical_metadata_applicability"] == "UNRESOLVED"
    assert report["missing_product_metadata_fields"] == [
        "created_at", "updated_at"
    ]
    assert report["canonical_dataset_published"] is False
    assert len(requests) == 6
    assert (evidence / "evidence-only" / "pass-1" / "chunk-000000.json").exists()
    assert not (evidence / "sf088-finalization-report.json").exists()

    requests.clear()
    assert acquisition.acquire_sf088_evidence_only(evidence_dir=evidence) == report
    assert requests == []

    with pytest.raises(ValueError, match="created_at/updated_at"):
        acquisition.acquire_sf088_pass(
            output_dir=tmp_path / "strict",
            pass_name="pass-1",
            chunk_plan=acquisition.build_sf088_chunk_plan(),
        )


def test_evidence_only_detects_raw_tampering_without_network(tmp_path, monkeypatch) -> None:
    """A raw/meta pair mismatch must fail closed before attempting acquisition."""
    plan = acquisition.build_sf088_chunk_plan(
        start=acquisition.SF088_START,
        end=acquisition.SF088_START + timedelta(minutes=1),
        chunk_minutes=1,
    )
    # A partially written product pair is never repaired or overwritten.
    output = tmp_path / "evidence"
    path = output / "pass-1"
    path.mkdir(parents=True)
    (path / "product.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="incomplete existing SF-088 product evidence"):
        acquisition.acquire_sf088_pass(
            output_dir=output,
            pass_name="pass-1",
            chunk_plan=plan,
            evidence_only=True,
        )
