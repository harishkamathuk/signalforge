from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

import signalforge.research.delta_historical_qualification as delta_qualification
from signalforge.domain.ids import InstrumentId
from signalforge.research.delta_historical_qualification import (
    DeltaRawCapture,
    DeltaTimestampContract,
    DeltaTimestampLabel,
    canonicalize_delta_one_minute,
    compare_delta_five_minute_candles,
    parse_delta_candles_response,
    parse_delta_product_response,
    summarize_delta_candles,
)
from signalforge.research.historical_bars import (
    CorporateActionPolicy,
    HistoricalPriceBasis,
)
from signalforge.research.historical_dataset_store import LocalHistoricalDatasetStore


def _capture(payload: object) -> DeltaRawCapture:
    content = json.dumps(payload, separators=(",", ":")).encode()
    return DeltaRawCapture(
        request_url="https://api.india.delta.exchange/test",
        acquired_at=datetime(2026, 10, 31, 12, tzinfo=UTC),
        content_sha256=hashlib.sha256(content).hexdigest(),
        content=content,
    )


def _product_capture() -> DeltaRawCapture:
    return _capture(
        {
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
    )


def _candles_payload(start: int, count: int, resolution_seconds: int = 60) -> object:
    rows = []
    for index in range(count):
        base = Decimal("65000") + Decimal(index)
        rows.append(
            {
                "time": start + index * resolution_seconds,
                "open": str(base),
                "high": str(base + Decimal("1.0")),
                "low": str(base - Decimal("1.0")),
                "close": str(base + Decimal("0.5")),
                "volume": str(10 + index),
            }
        )
    return {"success": True, "result": rows}


def test_product_snapshot_is_exact_provider_native_identity() -> None:
    capture = _product_capture()
    product = parse_delta_product_response(capture, expected_symbol="BTCUSD")

    assert product.product_id == 27
    assert product.contract_type == "perpetual_futures"
    assert product.contract_value == Decimal("0.001")
    assert product.tick_size == Decimal("0.5")
    assert product.underlying_asset_symbol == "BTC"
    assert product.quoting_asset_symbol == "USD"
    assert product.settling_asset_symbol == "USD"
    assert product.raw_sha256 == capture.content_sha256

    with pytest.raises(ValueError, match="contradicts requested symbol"):
        parse_delta_product_response(capture, expected_symbol="ETHUSD")


def test_candle_parser_preserves_decimal_values_without_float_round_trip() -> None:
    capture = _capture(
        {
            "success": True,
            "result": [
                {
                    "time": 1793318400,
                    "open": 65000.1,
                    "high": 65000.6,
                    "low": 64999.6,
                    "close": 65000.4,
                    "volume": 12.5,
                }
            ],
        }
    )
    candle = parse_delta_candles_response(capture)[0]

    assert candle.open == Decimal("65000.1")
    assert candle.close == Decimal("65000.4")
    assert candle.volume == Decimal("12.5")


def test_summary_exposes_fractional_volume_and_tick_misalignment() -> None:
    candles = parse_delta_candles_response(
        _capture(
            {
                "success": True,
                "result": [
                    {
                        "time": 1793318400,
                        "open": "65000.1",
                        "high": "65000.6",
                        "low": "64999.6",
                        "close": "65000.4",
                        "volume": "12.5",
                    }
                ],
            }
        )
    )

    summary = summarize_delta_candles(candles, tick_size=Decimal("0.5"))

    assert summary.exact_minute_aligned is True
    assert summary.integral_volume is False
    assert summary.tick_aligned_prices is False


def test_timestamp_contract_translates_half_open_grid_without_session_assumption() -> None:
    start = datetime(2026, 10, 30, tzinfo=UTC)
    end = start + timedelta(days=1)

    inclusive = DeltaTimestampContract(
        timestamp_unit="seconds",
        timestamp_label=DeltaTimestampLabel.CANDLE_OPEN,
        start_inclusive=True,
        end_inclusive=True,
    )
    exclusive = replace(inclusive, end_inclusive=False)

    inclusive_start, inclusive_end = inclusive.provider_bounds(start, end)
    exclusive_start, exclusive_end = exclusive.provider_bounds(start, end)

    assert inclusive_start == exclusive_start
    assert inclusive_end == int((end - timedelta(minutes=1)).timestamp())
    assert exclusive_end == int(end.timestamp())

    with pytest.raises(ValueError, match="candle-open"):
        replace(inclusive, timestamp_label=DeltaTimestampLabel.UNKNOWN).provider_bounds(
            start, end
        )


def test_exact_five_minute_comparison_includes_volume() -> None:
    start = 1793318400
    one_minute = parse_delta_candles_response(
        _capture(_candles_payload(start, 5))
    )
    first, last = one_minute[0], one_minute[-1]
    expected_volume = sum((item.volume for item in one_minute), Decimal(0))
    provider_5m = parse_delta_candles_response(
        _capture(
            {
                "success": True,
                "result": [
                    {
                        "time": start,
                        "open": str(first.open),
                        "high": str(max(item.high for item in one_minute)),
                        "low": str(min(item.low for item in one_minute)),
                        "close": str(last.close),
                        "volume": str(expected_volume),
                    }
                ],
            }
        )
    )

    matched = compare_delta_five_minute_candles(one_minute, provider_5m)
    assert matched.compared_buckets == 1
    assert matched.matching_buckets == 1
    assert matched.mismatches == ()

    changed = (
        replace(provider_5m[0], volume=provider_5m[0].volume + Decimal(1)),
    )
    mismatched = compare_delta_five_minute_candles(one_minute, changed)
    assert mismatched.matching_buckets == 0
    assert mismatched.mismatches[0].fields == ("volume",)


def test_canonical_delta_dataset_has_explicit_price_basis_and_offline_round_trip(
    tmp_path,
) -> None:
    start = datetime(2026, 10, 30, tzinfo=UTC)
    product = parse_delta_product_response(_product_capture(), expected_symbol="BTCUSD")
    candles = parse_delta_candles_response(
        _capture(_candles_payload(int(start.timestamp()), 5))
    )
    contract = DeltaTimestampContract(
        timestamp_unit="seconds",
        timestamp_label=DeltaTimestampLabel.CANDLE_OPEN,
        start_inclusive=True,
        end_inclusive=False,
    )

    dataset = canonicalize_delta_one_minute(
        candles=candles,
        product=product,
        instrument_id=InstrumentId("DELTA:BTCUSD"),
        requested_start=start,
        requested_end=start + timedelta(minutes=5),
        acquired_at=datetime(2026, 10, 31, 12, tzinfo=UTC),
        timestamp_contract=contract,
        acquisition_version="sf087-test",
        canonicalisation_version="delta-traded-v1",
    )

    assert dataset.manifest.price_basis is HistoricalPriceBasis.TRADED
    assert (
        dataset.manifest.corporate_action_policy
        is CorporateActionPolicy.NOT_APPLICABLE
    )
    assert dataset.manifest.expected_session_dates == ()
    assert dataset.manifest.effective_grid.expected_minute_count == 5
    assert dataset.manifest.missing_interval_count == 0

    store = LocalHistoricalDatasetStore(tmp_path)
    dataset_id = store.save(dataset)
    assert store.load(dataset_id) == dataset

    changed_basis = replace(
        dataset.manifest,
        price_basis=HistoricalPriceBasis.MARK,
    )
    changed_dataset = replace(dataset, manifest=changed_basis)
    assert changed_dataset.dataset_id != dataset.dataset_id


def test_canonicalization_refuses_fractional_volume_and_out_of_grid_rows() -> None:
    start = datetime(2026, 10, 30, tzinfo=UTC)
    product = parse_delta_product_response(_product_capture(), expected_symbol="BTCUSD")
    contract = DeltaTimestampContract(
        timestamp_unit="seconds",
        timestamp_label=DeltaTimestampLabel.CANDLE_OPEN,
        start_inclusive=True,
        end_inclusive=False,
    )
    fractional = parse_delta_candles_response(
        _capture(
            {
                "success": True,
                "result": [
                    {
                        "time": int(start.timestamp()),
                        "open": "65000.0",
                        "high": "65000.5",
                        "low": "64999.5",
                        "close": "65000.0",
                        "volume": "1.5",
                    }
                ],
            }
        )
    )

    with pytest.raises(ValueError, match="integer volume"):
        canonicalize_delta_one_minute(
            candles=fractional,
            product=product,
            instrument_id=InstrumentId("DELTA:BTCUSD"),
            requested_start=start,
            requested_end=start + timedelta(minutes=5),
            acquired_at=datetime(2026, 10, 31, 12, tzinfo=UTC),
            timestamp_contract=contract,
            acquisition_version="sf087-test",
            canonicalisation_version="delta-traded-v1",
        )

    outside = parse_delta_candles_response(
        _capture(_candles_payload(int((start - timedelta(minutes=1)).timestamp()), 1))
    )
    with pytest.raises(ValueError, match="outside canonical requested coverage"):
        canonicalize_delta_one_minute(
            candles=outside,
            product=product,
            instrument_id=InstrumentId("DELTA:BTCUSD"),
            requested_start=start,
            requested_end=start + timedelta(minutes=5),
            acquired_at=datetime(2026, 10, 31, 12, tzinfo=UTC),
            timestamp_contract=contract,
            acquisition_version="sf087-test",
            canonicalisation_version="delta-traded-v1",
        )


def test_capture_bundle_makes_independent_requests_and_records_hashes(
    tmp_path, monkeypatch
) -> None:
    calls: list[tuple[str, dict[str, str | int] | None]] = []

    def fake_acquire(
        path: str,
        *,
        params: dict[str, str | int] | None = None,
        api_origin: str,
        timeout_seconds: float = 30.0,
    ) -> DeltaRawCapture:
        del timeout_seconds
        calls.append((path, params))
        suffix = len(calls)
        payload = (
            _product_capture().content
            if path.startswith("/v2/products/")
            else _capture(_candles_payload(1793318400, 1)).content
        )
        return DeltaRawCapture(
            request_url=f"{api_origin}{path}?call={suffix}",
            acquired_at=datetime(2026, 10, 31, 12, suffix, tzinfo=UTC),
            content_sha256=hashlib.sha256(payload).hexdigest(),
            content=payload,
        )

    monkeypatch.setattr(delta_qualification, "acquire_delta_response", fake_acquire)
    manifest = delta_qualification.capture_delta_bundle(
        symbol="BTCUSD",
        resolution="1m",
        start_epoch=1793318400,
        end_epoch=1793319000,
        repeats=2,
        output_dir=tmp_path,
    )

    assert [call[0] for call in calls] == [
        "/v2/products/BTCUSD",
        "/v2/history/candles",
        "/v2/history/candles",
    ]
    assert (tmp_path / "product.json").exists()
    assert (tmp_path / "candles-1m-1.json").exists()
    assert (tmp_path / "candles-1m-2.json").exists()
    assert (tmp_path / "capture-manifest.json").exists()
    candles = manifest["candles"]
    assert isinstance(candles, list)
    assert len(candles) == 2
    assert candles[0]["request_url"] != candles[1]["request_url"]
