"""Bounded Delta historical-data qualification helpers for SF-087.

This module is intentionally provider-specific. It translates Delta REST evidence
into existing provider-neutral historical research contracts without introducing a
general broker/provider framework.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from signalforge.domain.ids import InstrumentId
from signalforge.domain.market import CandleQuality
from signalforge.domain.money import Price
from signalforge.domain.time import CandleInterval, require_aware, to_utc
from signalforge.research.historical_bars import (
    CorporateActionPolicy,
    HistoricalBar,
    HistoricalBarDataset,
    HistoricalDatasetManifest,
    HistoricalPriceBasis,
)
from signalforge.research.historical_grid import HistoricalBarGrid

_DELTA_PRODUCTION_ORIGIN = "https://api.india.delta.exchange"
_ONE_MINUTE = timedelta(minutes=1)


class DeltaTimestampLabel(StrEnum):
    """Provider candle timestamp interpretation established by qualification."""

    CANDLE_OPEN = "candle_open"
    CANDLE_CLOSE = "candle_close"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class DeltaTimestampContract:
    """Empirically established REST timestamp and request-bound semantics."""

    timestamp_unit: str
    timestamp_label: DeltaTimestampLabel
    start_inclusive: bool
    end_inclusive: bool

    def __post_init__(self) -> None:
        if self.timestamp_unit != "seconds":
            raise ValueError("Delta qualification currently requires epoch-second timestamps")

    def provider_bounds(
        self,
        start: datetime,
        end: datetime,
        *,
        interval: timedelta = _ONE_MINUTE,
    ) -> tuple[int, int]:
        """Translate canonical half-open coverage to provider request bounds."""

        require_aware(start)
        require_aware(end)
        start_utc, end_utc = to_utc(start), to_utc(end)
        if start_utc.second or start_utc.microsecond or end_utc.second or end_utc.microsecond:
            raise ValueError("Delta qualification bounds must align to exact minutes")
        if interval <= timedelta(0) or interval % _ONE_MINUTE:
            raise ValueError("Delta qualification interval must be positive whole minutes")
        if end_utc <= start_utc or (end_utc - start_utc) % interval:
            raise ValueError("Delta qualification range must contain complete intervals")
        if self.timestamp_label is not DeltaTimestampLabel.CANDLE_OPEN:
            raise ValueError("Canonical mapping requires candle-open timestamp evidence")
        if not self.start_inclusive:
            raise ValueError("Unsupported Delta start-bound semantics for canonical mapping")
        provider_end = end_utc - interval if self.end_inclusive else end_utc
        return int(start_utc.timestamp()), int(provider_end.timestamp())


@dataclass(frozen=True, slots=True)
class DeltaRawCapture:
    """One independently acquired provider response and immutable local evidence."""

    request_url: str
    acquired_at: datetime
    content_sha256: str
    content: bytes

    def __post_init__(self) -> None:
        require_aware(self.acquired_at)
        object.__setattr__(self, "acquired_at", to_utc(self.acquired_at))
        if hashlib.sha256(self.content).hexdigest() != self.content_sha256:
            raise ValueError("Delta raw capture digest does not match content")


@dataclass(frozen=True, slots=True)
class DeltaProductSnapshot:
    """Provider-native product identity needed to qualify one historical series."""

    api_origin: str
    product_id: int
    symbol: str
    contract_type: str
    contract_value: Decimal
    contract_unit_currency: str
    tick_size: Decimal
    underlying_asset_symbol: str | None
    quoting_asset_symbol: str | None
    settling_asset_symbol: str | None
    raw_sha256: str
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.api_origin.strip() or not self.symbol.strip() or not self.contract_type.strip():
            raise ValueError("Delta product identity fields must not be empty")
        if self.product_id <= 0:
            raise ValueError("Delta product_id must be positive")
        if self.contract_value <= 0 or self.tick_size <= 0:
            raise ValueError("Delta contract value and tick size must be positive")
        if len(self.raw_sha256) != 64:
            raise ValueError("Delta product snapshot requires a SHA-256 digest")
        for field_name in ("created_at", "updated_at"):
            value = getattr(self, field_name)
            if value is not None:
                require_aware(value)
                object.__setattr__(self, field_name, to_utc(value))

    @property
    def semantic_sha256(self) -> str:
        """Stable digest of the product metadata used to interpret canonical data."""

        payload = {
            "product_id": self.product_id,
            "symbol": self.symbol,
            "contract_type": self.contract_type,
            "contract_value": str(self.contract_value),
            "contract_unit_currency": self.contract_unit_currency,
            "tick_size": str(self.tick_size),
            "underlying_asset_symbol": self.underlying_asset_symbol,
            "quoting_asset_symbol": self.quoting_asset_symbol,
            "settling_asset_symbol": self.settling_asset_symbol,
        }
        encoded = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("ascii")
        return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class DeltaCandle:
    """Exact provider OHLCV row parsed without binary floating-point conversion."""

    time: int
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal

    def __post_init__(self) -> None:
        if self.time <= 0:
            raise ValueError("Delta candle time must be positive")
        if min(self.open, self.high, self.low, self.close) <= 0:
            raise ValueError("Delta candle prices must be strictly positive")
        if self.high < max(self.open, self.close, self.low):
            raise ValueError("Delta candle high violates OHLC invariant")
        if self.low > min(self.open, self.close, self.high):
            raise ValueError("Delta candle low violates OHLC invariant")
        if self.volume < 0:
            raise ValueError("Delta candle volume must not be negative")

    @property
    def start_utc(self) -> datetime:
        """Interpret the raw integer as an epoch-second instant for evidence checks."""

        return datetime.fromtimestamp(self.time, tz=UTC)


@dataclass(frozen=True, slots=True)
class DeltaCandleSummary:
    """Mechanical source-shape evidence independent of strategy semantics."""

    row_count: int
    strictly_increasing: bool
    strictly_decreasing: bool
    duplicate_times: tuple[int, ...]
    exact_minute_aligned: bool
    integral_volume: bool
    tick_aligned_prices: bool


@dataclass(frozen=True, slots=True)
class DeltaFiveMinuteMismatch:
    """Exact provider-5m versus deterministic 1m aggregation difference."""

    start: datetime
    fields: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DeltaFiveMinuteComparison:
    """Exact aggregation comparison for complete five-minute source buckets."""

    compared_buckets: int
    matching_buckets: int
    mismatches: tuple[DeltaFiveMinuteMismatch, ...]


def _exact_json(content: bytes) -> object:
    """Parse JSON while preserving decimal numeric values exactly."""

    return json.loads(content.decode("utf-8"), parse_float=Decimal)


def _mapping(value: object, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"Delta {field} must be an object")
    return cast(dict[str, Any], value)


def _decimal(value: object, field: str) -> Decimal:
    if isinstance(value, bool):
        raise ValueError(f"Delta {field} must be numeric")
    if isinstance(value, Decimal | int | str):
        try:
            result = Decimal(str(value))
        except ArithmeticError as exc:
            raise ValueError(f"Delta {field} must be numeric") from exc
        if not result.is_finite():
            raise ValueError(f"Delta {field} must be finite")
        return result
    raise ValueError(f"Delta {field} must be numeric")


def _optional_datetime(value: object, field: str) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Delta {field} must be an ISO datetime string or null")
    parsed = datetime.fromisoformat(value)
    require_aware(parsed)
    return to_utc(parsed)


def _optional_asset_symbol(value: object) -> str | None:
    if value is None:
        return None
    mapping = _mapping(value, "asset")
    symbol = mapping.get("symbol")
    if symbol is None:
        return None
    if not isinstance(symbol, str) or not symbol.strip():
        raise ValueError("Delta asset symbol must be a non-empty string")
    return symbol


def parse_delta_product_response(
    capture: DeltaRawCapture,
    *,
    expected_symbol: str,
    api_origin: str = _DELTA_PRODUCTION_ORIGIN,
) -> DeltaProductSnapshot:
    """Parse exact provider product identity from a captured REST response."""

    payload = _mapping(_exact_json(capture.content), "product response")
    if payload.get("success") is not True:
        raise ValueError("Delta product response success must be true")
    result = _mapping(payload.get("result"), "product result")
    symbol = result.get("symbol")
    if symbol != expected_symbol:
        raise ValueError("Delta product response symbol contradicts requested symbol")
    product_id = result.get("id")
    if isinstance(product_id, bool) or not isinstance(product_id, int):
        raise ValueError("Delta product id must be an integer")
    contract_type = result.get("contract_type")
    contract_unit = result.get("contract_unit_currency")
    if not isinstance(contract_type, str) or not contract_type.strip():
        raise ValueError("Delta contract_type must be a non-empty string")
    if not isinstance(contract_unit, str) or not contract_unit.strip():
        raise ValueError("Delta contract_unit_currency must be a non-empty string")
    return DeltaProductSnapshot(
        api_origin=api_origin,
        product_id=product_id,
        symbol=expected_symbol,
        contract_type=contract_type,
        contract_value=_decimal(result.get("contract_value"), "contract_value"),
        contract_unit_currency=contract_unit,
        tick_size=_decimal(result.get("tick_size"), "tick_size"),
        underlying_asset_symbol=_optional_asset_symbol(result.get("underlying_asset")),
        quoting_asset_symbol=_optional_asset_symbol(result.get("quoting_asset")),
        settling_asset_symbol=_optional_asset_symbol(result.get("settling_asset")),
        raw_sha256=capture.content_sha256,
        created_at=_optional_datetime(result.get("created_at"), "created_at"),
        updated_at=_optional_datetime(result.get("updated_at"), "updated_at"),
    )


def parse_delta_candles_response(capture: DeltaRawCapture) -> tuple[DeltaCandle, ...]:
    """Parse exact historical candles from a captured REST response."""

    payload = _mapping(_exact_json(capture.content), "candle response")
    if payload.get("success") is not True:
        raise ValueError("Delta candle response success must be true")
    rows = payload.get("result")
    if not isinstance(rows, list):
        raise ValueError("Delta candle response result must be an array")
    candles: list[DeltaCandle] = []
    for index, value in enumerate(rows):
        row = _mapping(value, f"candle[{index}]")
        raw_time = row.get("time")
        if isinstance(raw_time, bool) or not isinstance(raw_time, int):
            raise ValueError(f"Delta candle[{index}].time must be an integer")
        candles.append(
            DeltaCandle(
                time=raw_time,
                open=_decimal(row.get("open"), f"candle[{index}].open"),
                high=_decimal(row.get("high"), f"candle[{index}].high"),
                low=_decimal(row.get("low"), f"candle[{index}].low"),
                close=_decimal(row.get("close"), f"candle[{index}].close"),
                volume=_decimal(row.get("volume"), f"candle[{index}].volume"),
            )
        )
    return tuple(candles)


def summarize_delta_candles(
    candles: tuple[DeltaCandle, ...],
    *,
    tick_size: Decimal,
) -> DeltaCandleSummary:
    """Return mechanical quality evidence without inventing missing observations."""

    if tick_size <= 0:
        raise ValueError("Delta tick_size must be positive")
    times = [candle.time for candle in candles]
    duplicates = tuple(sorted({value for value in times if times.count(value) > 1}))
    return DeltaCandleSummary(
        row_count=len(candles),
        strictly_increasing=all(
            left < right for left, right in zip(times, times[1:], strict=False)
        ),
        strictly_decreasing=all(
            left > right for left, right in zip(times, times[1:], strict=False)
        ),
        duplicate_times=duplicates,
        exact_minute_aligned=all(candle.time % 60 == 0 for candle in candles),
        integral_volume=all(
            candle.volume == candle.volume.to_integral_value() for candle in candles
        ),
        tick_aligned_prices=all(
            value % tick_size == 0
            for candle in candles
            for value in (candle.open, candle.high, candle.low, candle.close)
        ),
    )


def compare_delta_five_minute_candles(
    one_minute: tuple[DeltaCandle, ...],
    five_minute: tuple[DeltaCandle, ...],
) -> DeltaFiveMinuteComparison:
    """Compare provider 5m candles with exact aggregation of complete 1m buckets."""

    by_time = {candle.time: candle for candle in one_minute}
    mismatches: list[DeltaFiveMinuteMismatch] = []
    compared = 0
    matching = 0
    for provider in five_minute:
        constituents = tuple(by_time.get(provider.time + offset * 60) for offset in range(5))
        if any(item is None for item in constituents):
            continue
        complete = cast(tuple[DeltaCandle, ...], constituents)
        compared += 1
        expected = {
            "open": complete[0].open,
            "high": max(item.high for item in complete),
            "low": min(item.low for item in complete),
            "close": complete[-1].close,
            "volume": sum((item.volume for item in complete), Decimal(0)),
        }
        actual = {
            "open": provider.open,
            "high": provider.high,
            "low": provider.low,
            "close": provider.close,
            "volume": provider.volume,
        }
        fields = tuple(name for name in expected if expected[name] != actual[name])
        if fields:
            mismatches.append(DeltaFiveMinuteMismatch(provider.start_utc, fields))
        else:
            matching += 1
    return DeltaFiveMinuteComparison(compared, matching, tuple(mismatches))


def canonicalize_delta_one_minute(
    *,
    candles: tuple[DeltaCandle, ...],
    product: DeltaProductSnapshot,
    instrument_id: InstrumentId,
    requested_start: datetime,
    requested_end: datetime,
    acquired_at: datetime,
    timestamp_contract: DeltaTimestampContract,
    acquisition_version: str,
    canonicalisation_version: str,
) -> HistoricalBarDataset:
    """Map qualified traded-price 1m evidence into the canonical historical contract."""

    start, end = to_utc(requested_start), to_utc(requested_end)
    timestamp_contract.provider_bounds(start, end)
    if not candles:
        raise ValueError("Delta canonicalization requires at least one source candle")

    unique: dict[int, DeltaCandle] = {}
    duplicate_count = 0
    for candle in candles:
        existing = unique.get(candle.time)
        if existing is not None:
            if existing != candle:
                raise ValueError("Contradictory duplicate Delta historical candle")
            duplicate_count += 1
            continue
        unique[candle.time] = candle
    ordered = tuple(unique[key] for key in sorted(unique))

    for candle in ordered:
        if candle.start_utc < start or candle.start_utc >= end:
            raise ValueError("Delta candle lies outside canonical requested coverage")
        if candle.time % 60:
            raise ValueError("Delta candle does not align to an exact UTC minute")
        if candle.volume != candle.volume.to_integral_value():
            raise ValueError("Delta volume is not losslessly representable as integer volume")
        if any(
            value % product.tick_size
            for value in (candle.open, candle.high, candle.low, candle.close)
        ):
            raise ValueError("Delta price is not aligned to provider product tick size")

    grid = HistoricalBarGrid(
        grid_id="continuous-explicit-utc",
        version="1",
        coverage=(CandleInterval(start, end),),
    )
    bars = tuple(
        HistoricalBar(
            instrument_id=instrument_id,
            interval=CandleInterval(candle.start_utc, candle.start_utc + _ONE_MINUTE),
            open=Price(candle.open),
            high=Price(candle.high),
            low=Price(candle.low),
            close=Price(candle.close),
            volume=int(candle.volume),
            quality=CandleQuality.VALID,
            source_provider="delta_exchange_india",
            source_record_count=1,
            provider_timestamp_raw=str(candle.time),
            provider_timestamp_interpreted=candle.start_utc,
            canonicalisation_version=canonicalisation_version,
        )
        for candle in ordered
    )
    return HistoricalBarDataset(
        manifest=HistoricalDatasetManifest(
            provider="delta_exchange_india",
            acquisition_adapter="sf087_delta_rest_qualification",
            acquisition_version=acquisition_version,
            requested_instrument=product.symbol,
            resolved_provider_instrument=f"{product.symbol}#{product.product_id}",
            instrument_id=instrument_id,
            requested_start=start,
            requested_end=end,
            returned_start=bars[0].interval.start,
            returned_end=bars[-1].interval.end,
            interval_minutes=1,
            acquired_at=acquired_at,
            provider_timestamp_representation="unix_seconds",
            timezone_interpretation="UTC",
            canonicalisation_version=canonicalisation_version,
            expected_session_dates=(),
            raw_row_count=len(candles),
            canonical_row_count=len(bars),
            missing_interval_count=grid.expected_minute_count - len(bars),
            duplicate_observation_count=duplicate_count,
            corrupt_rejected_count=0,
            corporate_action_policy=CorporateActionPolicy.NOT_APPLICABLE,
            limitations=(
                f"source_api_origin={product.api_origin}",
                f"source_product_id={product.product_id}",
                f"source_instrument_metadata_sha256={product.semantic_sha256}",
            ),
            grid=grid,
            price_basis=HistoricalPriceBasis.TRADED,
        ),
        bars=bars,
    )


def acquire_delta_response(
    path: str,
    *,
    params: dict[str, str | int] | None = None,
    api_origin: str = _DELTA_PRODUCTION_ORIGIN,
    timeout_seconds: float = 30.0,
) -> DeltaRawCapture:
    """Acquire one public Delta REST response without caching or authentication."""

    if not path.startswith("/"):
        raise ValueError("Delta REST path must begin with '/'")
    query = "" if not params else "?" + urlencode(params)
    url = api_origin.rstrip("/") + path + query
    request = Request(url, headers={"Accept": "application/json"}, method="GET")
    with urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310
        content = response.read()
    return DeltaRawCapture(
        request_url=url,
        acquired_at=datetime.now(tz=UTC),
        content_sha256=hashlib.sha256(content).hexdigest(),
        content=content,
    )


def capture_delta_bundle(
    *,
    symbol: str,
    resolution: str,
    start_epoch: int,
    end_epoch: int,
    repeats: int,
    output_dir: Path,
    api_origin: str = _DELTA_PRODUCTION_ORIGIN,
) -> dict[str, object]:
    """Capture uncached provider evidence without canonicalizing or running strategy logic."""

    if not symbol.strip():
        raise ValueError("Delta capture symbol must not be empty")
    if resolution not in {"1m", "5m"}:
        raise ValueError("SF-087 capture resolution must be 1m or 5m")
    if start_epoch <= 0 or end_epoch <= start_epoch:
        raise ValueError("Delta capture epoch bounds must be positive and increasing")
    if repeats <= 0:
        raise ValueError("Delta capture repeats must be positive")

    # Raw qualification evidence is write-once. Reusing a directory would destroy
    # the acquisition/repeatability audit trail by replacing prior provider bytes.
    output_dir.mkdir(parents=True, exist_ok=False)
    product = acquire_delta_response(
        f"/v2/products/{symbol}",
        api_origin=api_origin,
    )
    product_name = "product.json"
    (output_dir / product_name).write_bytes(product.content)

    candle_entries: list[dict[str, object]] = []
    for index in range(repeats):
        capture = acquire_delta_response(
            "/v2/history/candles",
            params={
                "resolution": resolution,
                "symbol": symbol,
                "start": start_epoch,
                "end": end_epoch,
            },
            api_origin=api_origin,
        )
        file_name = f"candles-{resolution}-{index + 1}.json"
        (output_dir / file_name).write_bytes(capture.content)
        candle_entries.append(
            {
                "file": file_name,
                "request_url": capture.request_url,
                "acquired_at": capture.acquired_at.isoformat(),
                "sha256": capture.content_sha256,
            }
        )

    manifest: dict[str, object] = {
        "provider": "delta_exchange_india",
        "api_origin": api_origin,
        "symbol": symbol,
        "resolution": resolution,
        "start_epoch": start_epoch,
        "end_epoch": end_epoch,
        "product": {
            "file": product_name,
            "request_url": product.request_url,
            "acquired_at": product.acquired_at.isoformat(),
            "sha256": product.content_sha256,
        },
        "candles": candle_entries,
    }
    manifest_path = output_dir / "capture-manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def _capture_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m signalforge.research.delta_historical_qualification",
        description="Capture bounded Delta public historical evidence for SF-087.",
    )
    parser.add_argument("--symbol", default="BTCUSD")
    parser.add_argument("--resolution", choices=("1m", "5m"), required=True)
    parser.add_argument("--start-epoch", type=int, required=True)
    parser.add_argument("--end-epoch", type=int, required=True)
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--api-origin", default=_DELTA_PRODUCTION_ORIGIN)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the explicit SF-087 raw evidence capture command."""

    args = _capture_parser().parse_args(argv)
    manifest = capture_delta_bundle(
        symbol=args.symbol,
        resolution=args.resolution,
        start_epoch=args.start_epoch,
        end_epoch=args.end_epoch,
        repeats=args.repeats,
        output_dir=args.output_dir,
        api_origin=args.api_origin,
    )
    print(json.dumps(manifest, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
