"""Bounded Delta historical-data qualification helpers for SF-087.

This module is intentionally provider-specific. It translates Delta REST evidence
into existing provider-neutral historical research contracts without introducing a
general broker/provider framework.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
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

    def provider_bounds(self, start: datetime, end: datetime) -> tuple[int, int]:
        """Translate canonical half-open minute coverage to provider request bounds."""

        require_aware(start)
        require_aware(end)
        start_utc, end_utc = to_utc(start), to_utc(end)
        if start_utc.second or start_utc.microsecond or end_utc.second or end_utc.microsecond:
            raise ValueError("Delta qualification bounds must align to exact minutes")
        if end_utc <= start_utc:
            raise ValueError("Delta qualification range must be increasing")
        if self.timestamp_label is not DeltaTimestampLabel.CANDLE_OPEN:
            raise ValueError("Canonical mapping requires candle-open timestamp evidence")
        if not self.start_inclusive:
            raise ValueError("Unsupported Delta start-bound semantics for canonical mapping")
        if self.end_inclusive:
            provider_end = end_utc - _ONE_MINUTE
        else:
            provider_end = end_utc
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

    def __post_init__(self) -> None:
        if not self.api_origin.strip() or not self.symbol.strip() or not self.contract_type.strip():
            raise ValueError("Delta product identity fields must not be empty")
        if self.product_id <= 0:
            raise ValueError("Delta product_id must be positive")
        if self.contract_value <= 0 or self.tick_size <= 0:
            raise ValueError("Delta contract value and tick size must be positive")
        if len(self.raw_sha256) != 64:
            raise ValueError("Delta product snapshot requires a SHA-256 digest")


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

    times = [candle.time for candle in candles]
    duplicates = tuple(sorted({value for value in times if times.count(value) > 1}))
    return DeltaCandleSummary(
        row_count=len(candles),
        strictly_increasing=all(left < right for left, right in zip(times, times[1:])),
        duplicate_times=duplicates,
        exact_minute_aligned=all(candle.time % 60 == 0 for candle in candles),
        integral_volume=all(candle.volume == candle.volume.to_integral_value() for candle in candles),
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
                f"delta_api_origin={product.api_origin}",
                f"delta_product_id={product.product_id}",
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
