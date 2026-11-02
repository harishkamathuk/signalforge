"""Focused regression coverage for SF-088 read-only evidence audit."""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from hashlib import sha256

import pytest

from signalforge.research import delta_historical_dataset_acquisition as acquisition
from signalforge.research import delta_historical_evidence_audit as audit
from signalforge.research.delta_historical_qualification import (
    DeltaRawCapture,
    parse_delta_product_response,
)


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

def test_complete_fixture_and_tick_observation(tmp_path, monkeypatch) -> None:
    start = acquisition.SF088_START
    plan = acquisition.build_sf088_chunk_plan(
        start=start, end=start + timedelta(minutes=2), chunk_minutes=1,
    )
    monkeypatch.setattr(audit, "build_sf088_chunk_plan", lambda: plan)
    monkeypatch.setattr(audit, "SF088_END", start + timedelta(minutes=2))
    monkeypatch.setattr(audit, "SF088_EXPECTED_MINUTES", 2)
    root = tmp_path / "generation-0001"
    product = {"success": True, "result": {
        "id": 27, "symbol": "BTCUSD", "contract_type": "perpetual_futures",
        "contract_value": "0.001", "contract_unit_currency": "BTC", "tick_size": "0.5",
    }}
    now = datetime(2026, 11, 1, tzinfo=UTC)
    prod_raw = json.dumps(product).encode()
    prod_capture = DeltaRawCapture(
        request_url="https://api.india.delta.exchange/v2/products/BTCUSD",
        acquired_at=now, content_sha256=sha256(prod_raw).hexdigest(), content=prod_raw,
    )
    prod = parse_delta_product_response(prod_capture, expected_symbol="BTCUSD")
    hashes = []
    semantic = []
    for pass_no in (1, 2):
        folder = root / f"pass-{pass_no}"
        folder.mkdir(parents=True)
        (folder / "product.json").write_bytes(prod_raw)
        (folder / "product.meta.json").write_text(json.dumps({
            "raw_sha256": sha256(prod_raw).hexdigest(),
            "request_url": prod_capture.request_url,
            "acquired_at": now.isoformat(),
            "acquisition_version": acquisition.SF088_ACQUISITION_VERSION,
        }))
        pass_hashes = []
        pass_semantic = []
        for chunk in plan:
            row = {"time": chunk.provider_start, "open": "65000.1" if chunk.index == 0 else "65000",
                   "high": "65001", "low": "65000", "close": "65000", "volume": "1"}
            # The first row must still pass OHLC invariants.
            raw = json.dumps({"success": True, "result": [row]}).encode()
            url = ("https://api.india.delta.exchange/v2/history/candles"
                   f"?resolution=1m&symbol=BTCUSD&start={chunk.provider_start}"
                   f"&end={chunk.provider_end}")
            capture = DeltaRawCapture(
                request_url=url, acquired_at=now,
                content_sha256=sha256(raw).hexdigest(), content=raw,
            )
            candles = audit.parse_delta_candles_response(capture)
            digest = audit._candle_semantic_sha256(candles)
            pass_hashes.append(capture.content_sha256)
            pass_semantic.append(digest)
            stem = f"chunk-{chunk.index:06d}"
            (folder / f"{stem}.json").write_bytes(raw)
            (folder / f"{stem}.meta.json").write_text(json.dumps({
                "chunk_identity": chunk.identity, "canonical_start": chunk.start.isoformat(),
                "canonical_end": chunk.end.isoformat(), "provider_start": chunk.provider_start,
                "provider_end": chunk.provider_end,
                "request_url": url, "acquired_at": now.isoformat(),
                "row_count": 1, "duplicate_count": 0, "missing_count": 0,
                "raw_sha256": capture.content_sha256, "semantic_sha256": digest,
                "acquisition_version": acquisition.SF088_ACQUISITION_VERSION,
            }))
        hashes.append(pass_hashes)
        semantic.append(pass_semantic)
    report = {
        "mode": "EVIDENCE_ONLY", "generation_namespace": "generation-0001",
        "frozen_start": start.isoformat(), "frozen_end": (start + timedelta(minutes=2)).isoformat(),
        "expected_minutes": 2, "chunk_identities": [c.identity for c in plan],
        "chunk_count_per_pass": 2,
        "source_product_id": 27, "source_symbol": "BTCUSD",
        "source_api_origin": "https://api.india.delta.exchange",
        "source_product_semantic_sha256": prod.semantic_sha256,
        "acquisition_version": acquisition.SF088_ACQUISITION_VERSION,
        "first_pass_raw_sha256": hashes[0], "second_pass_raw_sha256": hashes[1],
        "first_pass_semantic_sha256": semantic[0], "second_pass_semantic_sha256": semantic[1],
    }
    report["report_sha256"] = audit._sha256_json(report)
    (root / "evidence-only-report.json").write_text(json.dumps(report))
    result = audit.audit_generation(root)
    assert result["audit_status"] == "PASS_WITH_UNQUALIFIED_METADATA"
    assert result["observed_unique_minutes_pass_1"] == 2
    assert result["passes"]["pass_1"]["issues"]["off_current_snapshot_tick_price_fields"] == 1
    assert result["passes"]["pass_1"]["anomaly_examples"][0]["field"] == "open"
    assert result["passes"]["pass_1"]["anomaly_examples"][0]["value"] == "65000.1"

    # Rehash internally consistent evidence with missing/duplicate source observations.
    first_raw = root / "pass-1" / "chunk-000000.json"
    first_meta = root / "pass-1" / "chunk-000000.meta.json"
    original_raw = first_raw.read_bytes()
    original_meta = first_meta.read_bytes()
    original_report = json.dumps(report)

    for kind in ("missing", "duplicate"):
        baseline_row = json.loads(original_raw)["result"][0]
        rows = [] if kind == "missing" else [baseline_row, baseline_row]
        changed = json.dumps({"success": True, "result": rows}).encode()
        meta = json.loads(original_meta)
        capture = DeltaRawCapture(
            request_url=meta["request_url"], acquired_at=now,
            content_sha256=sha256(changed).hexdigest(), content=changed,
        )
        meta["raw_sha256"] = capture.content_sha256
        meta["semantic_sha256"] = audit._candle_semantic_sha256(
            audit.parse_delta_candles_response(capture)
        )
        meta["row_count"] = len(rows)
        meta["missing_count"] = 1 if kind == "missing" else 0
        meta["duplicate_count"] = 1 if kind == "duplicate" else 0
        first_raw.write_bytes(changed)
        first_meta.write_text(json.dumps(meta))
        report["first_pass_raw_sha256"][0] = meta["raw_sha256"]
        report["first_pass_semantic_sha256"][0] = meta["semantic_sha256"]
        report["report_sha256"] = audit._sha256_json(
            {k: v for k, v in report.items() if k != "report_sha256"}
        )
        (root / "evidence-only-report.json").write_text(json.dumps(report))
        diagnostic = audit.audit_generation(root)
        assert diagnostic["audit_status"] == "FAIL"
        if kind == "missing":
            assert diagnostic["passes"]["pass_1"]["missing_minute_count"] == 1
        else:
            assert diagnostic["passes"]["pass_1"]["issues"]["duplicate_minute"] == 1

        output = tmp_path / ".signalforge-data" / f"{kind}-audit.json"
        assert audit.main([
            "--generation-dir", str(root), "--output", str(output),
        ]) == 1
        assert json.loads(output.read_text())["audit_status"] == "FAIL"

        first_raw.write_bytes(original_raw)
        first_meta.write_bytes(original_meta)
        report = json.loads(original_report)
        (root / "evidence-only-report.json").write_text(original_report)

    # Contradicting product provenance must fail closed.
    report["source_product_semantic_sha256"] = "0" * 64
    report["report_sha256"] = audit._sha256_json(
        {k: v for k, v in report.items() if k != "report_sha256"}
    )
    (root / "evidence-only-report.json").write_text(json.dumps(report))
    with pytest.raises(ValueError, match="product semantics contradict"):
        audit.audit_generation(root)

    # A contradictory chunk-sidecar quality count must fail closed.
    report["source_product_semantic_sha256"] = prod.semantic_sha256
    report["report_sha256"] = audit._sha256_json(
        {k: v for k, v in report.items() if k != "report_sha256"}
    )
    (root / "evidence-only-report.json").write_text(json.dumps(report))
    sidecar = root / "pass-1" / "chunk-000000.meta.json"
    tampered = json.loads(sidecar.read_text())
    tampered["row_count"] = 99
    sidecar.write_text(json.dumps(tampered))
    with pytest.raises(ValueError, match="sidecar quality counts mismatch"):
        audit.audit_generation(root)
