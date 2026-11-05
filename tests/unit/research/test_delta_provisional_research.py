"""Contract tests for unqualified, read-only SF-088 price exploration."""
from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal, getcontext
from hashlib import sha256
from pathlib import Path

import pytest

from signalforge.research import delta_provisional_research as provisional
from signalforge.research import delta_historical_evidence_audit as evidence_audit
from signalforge.research.delta_historical_qualification import DeltaCandle


def _candles(count: int = 100) -> list[DeltaCandle]:
    start = 1_761_782_400  # 2025-10-30T00:00:00Z
    return [
        DeltaCandle(
            time=start + 60 * n,
            open=Decimal("65000.1") if n == 0 else Decimal("65000"),
            high=Decimal("65100"),
            low=Decimal("65000"),
            close=Decimal("65000.1") if n == 0 else Decimal(65000 + n),
            volume=Decimal(1),
        )
        for n in range(count)
    ]


def test_exploratory_sma_is_completed_only_and_deterministic() -> None:
    values = _candles()
    before = getcontext().prec
    first = provisional.summarize_completed_five_minute_closes(values)
    getcontext().prec = 12
    try:
        second = provisional.summarize_completed_five_minute_closes(iter(values))
    finally:
        getcontext().prec = before

    assert first == second
    assert first["one_minute_candles"] == 100
    assert first["completed_five_minute_closes"] == 20
    assert first["sma20_completed_points"] == 1
    assert first["sma20_warmup_completed_bars"] == 19
    assert len(first["sma20_sha256"]) == 64
    # Price irregularities are not snapped to any assumed historical tick.
    changed = values.copy()
    changed[0] = replace(changed[0], close=Decimal("65000.0"))
    assert (
        provisional.summarize_completed_five_minute_closes(changed)[
            "five_minute_close_sha256"
        ] == first["five_minute_close_sha256"]
    )
    changed[4] = replace(changed[4], close=Decimal("65000.1"))
    assert (
        provisional.summarize_completed_five_minute_closes(changed)[
            "five_minute_close_sha256"
        ] != first["five_minute_close_sha256"]
    )


@pytest.mark.parametrize("mode", ["missing", "duplicate", "unaligned", "partial", "empty"])
def test_incomplete_or_ambiguous_minutes_fail(mode: str) -> None:
    candles = _candles(10)
    if mode == "missing":
        candles.pop(4)
    elif mode == "duplicate":
        candles[4] = replace(candles[4], time=candles[3].time)
    elif mode == "unaligned":
        candles[0] = replace(candles[0], time=candles[0].time + 1)
    elif mode == "partial":
        candles.pop()
    else:
        candles.clear()
    with pytest.raises(ValueError):
        provisional.summarize_completed_five_minute_closes(candles)


def test_audit_failure_blocks_all_provisional_reading(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "generation-0001"
    root.mkdir()

    def reject(_root: Path) -> dict[str, object]:
        return {
            "audit_status": "FAIL",
            "frozen_start": provisional.SF088_START.isoformat(),
            "frozen_end": provisional.SF088_END.isoformat(),
            "observed_unique_minutes_pass_1": provisional.SF088_EXPECTED_MINUTES,
            "two_pass_semantic_match_independently_recomputed": True,
        }

    monkeypatch.setattr(provisional, "audit_generation", reject)
    with pytest.raises(ValueError, match="complete, audited"):
        provisional.explore_generation(root)


def test_command_refuses_output_overwrite_and_immutable_source(
    tmp_path: Path,
) -> None:
    root = tmp_path / ".signalforge-data" / "generation-0001"
    root.mkdir(parents=True)
    output = tmp_path / ".signalforge-data" / "report.json"
    output.write_text("existing report", encoding="utf-8")
    with pytest.raises(SystemExit):
        provisional.main([
            "--generation-dir", str(root), "--output", str(output),
        ])
    assert output.read_text(encoding="utf-8") == "existing report"

    with pytest.raises(SystemExit):
        provisional.main([
            "--generation-dir", str(root),
            "--output", str(root / "diagnostics.json"),
        ])
    with pytest.raises(SystemExit):
        provisional.main([
            "--generation-dir", str(root),
            "--output", str(tmp_path / "public-report.json"),
        ])


def test_provisional_report_preserves_unqualified_status_and_detects_tampering(
    tmp_path: Path, monkeypatch,
) -> None:
    """Exercise local-only derivation on a bounded synthetic source fixture."""
    from signalforge.research import delta_historical_dataset_acquisition as acquisition

    start = provisional.SF088_START
    end = start + timedelta(minutes=5)
    plan = acquisition.build_sf088_chunk_plan(
        start=start, end=end, chunk_minutes=5,
    )
    monkeypatch.setattr(provisional, "build_sf088_chunk_plan", lambda: plan)
    monkeypatch.setattr(provisional, "SF088_END", end)
    monkeypatch.setattr(provisional, "SF088_EXPECTED_MINUTES", 5)
    root = tmp_path / "generation-0001"
    folder = root / "pass-1"
    folder.mkdir(parents=True)
    candles = _candles(5)
    raw = json.dumps({
        "success": True,
        "result": [
            {
                "time": item.time,
                "open": str(item.open),
                "high": str(item.high),
                "low": str(item.low),
                "close": str(item.close),
                "volume": str(item.volume),
            }
            for item in reversed(candles)
        ],
    }).encode("ascii")
    raw_digest = sha256(raw).hexdigest()
    semantic_digest = acquisition._candle_semantic_sha256(tuple(reversed(candles)))
    stem = folder / "chunk-000000"
    stem.with_suffix(".json").write_bytes(raw)
    stem.with_suffix(".meta.json").write_text(json.dumps({
        "raw_sha256": raw_digest, "semantic_sha256": semantic_digest,
        "request_url": "https://api.india.delta.exchange/v2/history/candles",
        "acquired_at": "2026-11-01T00:00:00+00:00",
    }))
    (root / "evidence-only-report.json").write_text(json.dumps({
        "report_sha256": "b" * 64,
        "first_pass_raw_sha256": [raw_digest],
        "first_pass_semantic_sha256": [semantic_digest],
    }))

    def audited(_root: Path) -> dict[str, object]:
        return {
            "audit_status": "PASS_WITH_UNQUALIFIED_METADATA",
            "frozen_start": start.isoformat(),
            "frozen_end": end.isoformat(),
            "observed_unique_minutes_pass_1": 5,
            "two_pass_semantic_match_independently_recomputed": True,
            "audit_sha256": "a" * 64,
            "passes": {"pass_1": {
                "anomaly_examples": [{"field": "open", "value": "65000.1"}],
                "issues": {"off_current_snapshot_tick_price_fields": 1},
            }},
        }

    monkeypatch.setattr(provisional, "audit_generation", audited)
    result = provisional.explore_generation(root)
    assert result["historical_metadata_status"] == "UNQUALIFIED_HISTORICAL_METADATA"
    assert result["canonical_dataset_published"] is False
    assert result["historical_tick_size_assumed"] is False
    assert result["source_prices_repaired"] is False
    assert result["current_snapshot_tick_observations"][0]["value"] == "65000.1"
    assert result["derived_price_diagnostics"]["completed_five_minute_closes"] == 1

    stem.with_suffix(".json").write_bytes(raw + b" ")
    with pytest.raises(ValueError, match="raw digest mismatch"):
        provisional.explore_generation(root)


def test_canonical_hashes_preserve_numeric_identity() -> None:
    """Equivalent Decimal scales cannot change semantic diagnostic hashes."""
    rows = _candles(10)
    scaled = [replace(row, close=row.close.quantize(Decimal("0.00"))) for row in rows]
    a = provisional.summarize_completed_five_minute_closes(rows)
    b = provisional.summarize_completed_five_minute_closes(scaled)
    assert a["five_minute_close_sha256"] == b["five_minute_close_sha256"]
    assert a["sma20_sha256"] == b["sma20_sha256"]

    actual_change = scaled.copy()
    actual_change[9] = replace(actual_change[9], close=Decimal("65009.25"))
    assert provisional.summarize_completed_five_minute_closes(
        actual_change
    )["five_minute_close_sha256"] != a["five_minute_close_sha256"]


def test_independent_completed_bar_sma_oracle_and_utc_timestamp() -> None:
    """21 fixed closes 1..21 give first SMA=10.5 and second=11.5."""
    start = int(provisional.SF088_START.timestamp())
    rows = [
        DeltaCandle(
            time=start + 60 * index, open=Decimal(index // 5 + 1),
            high=Decimal(index // 5 + 1), low=Decimal(index // 5 + 1),
            close=Decimal(index // 5 + 1), volume=Decimal(1),
        )
        for index in range(105)
    ]
    actual = provisional.summarize_completed_five_minute_closes(rows)
    expected_closes = "".join(
        f"{start + i * 300}:{i + 1}\\n" for i in range(21)
    ).encode("ascii")
    expected_smas = (
        f"{start + 19 * 300}:10.5\\n"
        f"{start + 20 * 300}:11.5\\n"
    ).encode("ascii")
    assert actual["five_minute_close_sha256"] == sha256(expected_closes).hexdigest()
    assert actual["sma20_sha256"] == sha256(expected_smas).hexdigest()
    assert actual["completed_five_minute_closes"] == 21
    assert actual["sma20_completed_points"] == 2
    assert actual["sma20_warmup_completed_bars"] == 19
    assert actual["sma20_first_available_at_utc"] == "2025-10-30T01:40:00+00:00"
    assert actual["sma20_last_available_at_utc"] == "2025-10-30T01:45:00+00:00"


def test_output_location_bound_to_same_protected_root(
    tmp_path: Path, monkeypatch,
) -> None:
    """Reject similarly named, unrelated or symlink-escaped output directories."""
    protected = tmp_path / ".signalforge-data"
    root = protected / "sf088" / "evidence" / "evidence-only" / "generation-0001"
    root.mkdir(parents=True)
    other = tmp_path / "elsewhere" / ".signalforge-data"
    other.mkdir(parents=True)
    unignored = tmp_path / "signalforge-data"
    unignored.mkdir()
    escape = protected / "symlink-escape"
    escape.symlink_to(tmp_path / "elsewhere", target_is_directory=True)
    for destination in (
        unignored / "output.json",
        other / "output.json",
        escape / "output.json",
        root / "output.json",
    ):
        with pytest.raises(SystemExit):
            provisional.main([
                "--generation-dir", str(root), "--output", str(destination),
            ])

    def refused(_root: Path) -> dict[str, object]:
        raise RuntimeError("input checked only after valid output root")

    monkeypatch.setattr(provisional, "explore_generation", refused)
    with pytest.raises(RuntimeError, match="input checked"):
        provisional.main([
            "--generation-dir", str(root),
            "--output", str(protected / "sf088" / "audits" / "new.json"),
        ])


def test_end_to_end_provisional_cli_with_real_two_pass_audit(
    tmp_path: Path, monkeypatch,
) -> None:
    """A complete synthetic two-pass generation exercises the unstubbed audit."""
    from signalforge.research import delta_historical_dataset_acquisition as acquisition
    from signalforge.research.delta_historical_qualification import (
        DeltaRawCapture, parse_delta_product_response,
    )

    start = provisional.SF088_START
    end = start + timedelta(minutes=5)
    plan = acquisition.build_sf088_chunk_plan(
        start=start, end=end, chunk_minutes=5,
    )
    for module in (evidence_audit, provisional):
        monkeypatch.setattr(module, "SF088_END", end)
        monkeypatch.setattr(module, "SF088_EXPECTED_MINUTES", 5)
        monkeypatch.setattr(module, "build_sf088_chunk_plan", lambda: plan)

    protected = tmp_path / ".signalforge-data" / "sf088"
    root = protected / "evidence" / "evidence-only" / "generation-0001"
    product = {"success": True, "result": {
        "id": 27, "symbol": "BTCUSD",
        "contract_type": "perpetual_futures",
        "contract_value": "0.001", "contract_unit_currency": "BTC",
        "tick_size": "0.5",
        "underlying_asset": {"symbol": "BTC"},
        "quoting_asset": {"symbol": "USD"},
        "settling_asset": {"symbol": "USD"},
    }}
    raw_product = json.dumps(product).encode("ascii")
    product_capture = DeltaRawCapture(
        request_url="https://api.india.delta.exchange/v2/products/BTCUSD",
        acquired_at=datetime(2026, 11, 1, tzinfo=UTC),
        content_sha256=sha256(raw_product).hexdigest(), content=raw_product,
    )
    product_semantic = parse_delta_product_response(
        product_capture, expected_symbol="BTCUSD"
    ).semantic_sha256

    candle_rows = [
        {
            "time": int(start.timestamp()) + 60 * minute,
            "open": "65000.1" if minute == 0 else "65000",
            "high": "65010", "low": "65000",
            "close": str(65000 + minute), "volume": "1",
        }
        for minute in range(5)
    ]
    # Delta provides newest-first candles; the analysis must sort them explicitly.
    candle_raw = json.dumps({"success": True, "result": candle_rows[::-1]}).encode("ascii")
    captured = DeltaRawCapture(
        request_url="https://api.india.delta.exchange/v2/history/candles"
        f"?resolution=1m&symbol=BTCUSD&start={plan[0].provider_start}"
        f"&end={plan[0].provider_end}",
        acquired_at=product_capture.acquired_at,
        content_sha256=sha256(candle_raw).hexdigest(),
        content=candle_raw,
    )
    semantic = acquisition._candle_semantic_sha256(
        evidence_audit.parse_delta_candles_response(captured)
    )
    for pass_number in (1, 2):
        folder = root / f"pass-{pass_number}"
        folder.mkdir(parents=True)
        (folder / "product.json").write_bytes(raw_product)
        (folder / "product.meta.json").write_text(json.dumps({
            "raw_sha256": product_capture.content_sha256,
            "request_url": product_capture.request_url,
            "acquired_at": product_capture.acquired_at.isoformat(),
            "acquisition_version": acquisition.SF088_ACQUISITION_VERSION,
        }))
        (folder / "chunk-000000.json").write_bytes(candle_raw)
        (folder / "chunk-000000.meta.json").write_text(json.dumps({
            "chunk_identity": plan[0].identity,
            "canonical_start": plan[0].start.isoformat(),
            "canonical_end": plan[0].end.isoformat(),
            "provider_start": plan[0].provider_start,
            "provider_end": plan[0].provider_end,
            "request_url": captured.request_url,
            "acquired_at": captured.acquired_at.isoformat(),
            "row_count": 5, "duplicate_count": 0, "missing_count": 0,
            "raw_sha256": captured.content_sha256,
            "semantic_sha256": semantic,
            "acquisition_version": acquisition.SF088_ACQUISITION_VERSION,
        }))
    report = {
        "mode": "EVIDENCE_ONLY",
        "generation_namespace": "generation-0001",
        "frozen_start": start.isoformat(), "frozen_end": end.isoformat(),
        "expected_minutes": 5, "chunk_identities": [plan[0].identity],
        "chunk_count_per_pass": 1,
        "source_product_id": 27, "source_symbol": "BTCUSD",
        "source_api_origin": "https://api.india.delta.exchange",
        "source_product_semantic_sha256": product_semantic,
        "acquisition_version": acquisition.SF088_ACQUISITION_VERSION,
        "first_pass_raw_sha256": [captured.content_sha256],
        "second_pass_raw_sha256": [captured.content_sha256],
        "first_pass_semantic_sha256": [semantic],
        "second_pass_semantic_sha256": [semantic],
    }
    report["report_sha256"] = acquisition._sha256_json(report)
    (root / "evidence-only-report.json").write_text(json.dumps(report))
    output = protected / "audits" / "price-exploration.json"
    assert provisional.main([
        "--generation-dir", str(root), "--output", str(output),
    ]) == 0
    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["independent_audit_status"] == "PASS_WITH_UNQUALIFIED_METADATA"
    assert result["historical_metadata_status"] == "UNQUALIFIED_HISTORICAL_METADATA"
    assert result["canonical_dataset_published"] is False
    assert result["current_snapshot_tick_observation_count"] == 1
    assert result["derived_price_diagnostics"]["completed_five_minute_closes"] == 1
    assert result["report_sha256"] == acquisition._sha256_json({
        key: value for key, value in result.items() if key != "report_sha256"
    })
    assert len(list(root.rglob("*.json"))) == 9
    assert not list(protected.glob("store/*"))

    # Neither an old report nor a prior successful run may be overwritten.
    before = output.read_bytes()
    with pytest.raises(SystemExit):
        provisional.main([
            "--generation-dir", str(root), "--output", str(output),
        ])
    assert output.read_bytes() == before

    raw_path = root / "pass-2" / "chunk-000000.json"
    raw_path.write_bytes(candle_raw + b" ")
    with pytest.raises(ValueError, match="raw digest mismatch"):
        provisional.explore_generation(root)
