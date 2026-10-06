"""Authoritative completed-bar history adapter for SF-073 preparation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from signalforge.adapters.openalgo.config import OpenAlgoConfig
from signalforge.adapters.openalgo.transport import (
    OpenAlgoHttpResponse,
    OpenAlgoTransport,
    OpenAlgoTransportUnavailable,
    StdlibOpenAlgoTransport,
)
from signalforge.domain.ids import InstrumentId
from signalforge.domain.market import CandleQuality
from signalforge.domain.money import Price
from signalforge.domain.time import IST, CandleInterval


class OpenAlgoHistoryError(RuntimeError):
    """Historical-data acquisition or validation failed."""


class OpenAlgoHistoryAcquisitionError(OpenAlgoHistoryError):
    """Historical provider request could not be completed successfully."""


class OpenAlgoHistoryValidationError(OpenAlgoHistoryError):
    """Historical provider response cannot be trusted as canonical completed bars."""


class OpenAlgoHistoryContinuityUnproven(OpenAlgoHistoryValidationError):
    """Provider rows cannot prove a complete regular-session candle sequence."""


@dataclass(frozen=True, slots=True)
class HistoricalCompletedCandle:
    """Completed provider OHLCV bar without invented source-event chronology."""

    instrument_id: InstrumentId
    interval: CandleInterval
    quality: CandleQuality
    open: Price
    high: Price
    low: Price
    close: Price
    volume: int
    source: str

    def __post_init__(self) -> None:
        if self.quality is not CandleQuality.VALID:
            raise ValueError("historical completed candle must be VALID")
        if any(
            price.value <= 0
            for price in (self.open, self.high, self.low, self.close)
        ):
            raise ValueError("historical candle prices must be strictly positive")
        if self.high.value < max(self.open.value, self.close.value, self.low.value):
            raise ValueError("historical candle high violates OHLC invariants")
        if self.low.value > min(self.open.value, self.close.value, self.high.value):
            raise ValueError("historical candle low violates OHLC invariants")
        if self.volume < 0:
            raise ValueError("historical candle volume must not be negative")
        if not self.source.strip():
            raise ValueError("historical candle source must not be empty")


def fetch_openalgo_history(
    *,
    config: OpenAlgoConfig,
    instrument_id: InstrumentId,
    start_date: date,
    end_date: date,
    transport: OpenAlgoTransport | None = None,
) -> tuple[HistoricalCompletedCandle, ...]:
    """Fetch and strictly parse OpenAlgo 5-minute NSE completed OHLCV bars."""

    if end_date < start_date:
        raise ValueError("OpenAlgo history end_date must not precede start_date")
    raw_id = str(instrument_id)
    if not raw_id.startswith("NSE:") or raw_id.count(":") != 1:
        raise ValueError("SF-073 history requires canonical NSE:<SYMBOL> identity")
    symbol = raw_id.removeprefix("NSE:")
    selected = transport or StdlibOpenAlgoTransport(config.host)
    request: dict[str, object] = {
        "apikey": config.api_key.get_secret_value(),
        "symbol": symbol,
        "exchange": "NSE",
        "interval": "5m",
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
    }
    try:
        response = selected.post_json(
            path="/api/v1/history",
            payload=request,
            connect_timeout_seconds=config.connect_timeout_seconds,
            request_timeout_seconds=config.request_timeout_seconds,
        )
    except OpenAlgoTransportUnavailable:
        raise OpenAlgoHistoryAcquisitionError(
            "OpenAlgo historical-data request was unreachable"
        ) from None
    payload = _decode(response)
    if response.status_code != 200 or payload.get("status") != "success":
        raise OpenAlgoHistoryAcquisitionError(
            "OpenAlgo historical-data request did not succeed"
        )
    data = payload.get("data")
    if not isinstance(data, list):
        raise OpenAlgoHistoryValidationError("OpenAlgo history omitted an array data payload")

    candles = tuple(_parse_row(item, instrument_id) for item in data)
    previous: HistoricalCompletedCandle | None = None
    for candle in candles:
        if previous is not None and candle.interval.start < previous.interval.end:
            raise OpenAlgoHistoryValidationError(
                "OpenAlgo history contains duplicate, overlapping, or out-of-order intervals"
            )
        previous = candle
    return candles


def _decode(response: OpenAlgoHttpResponse) -> dict[str, Any]:
    if (
        response.content_type is not None
        and "application/json" not in response.content_type.lower()
    ):
        raise OpenAlgoHistoryValidationError("OpenAlgo history returned a non-JSON content type")
    try:
        payload = json.loads(response.body.decode("utf-8"), parse_float=Decimal)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise OpenAlgoHistoryValidationError("OpenAlgo history returned malformed JSON") from None
    if not isinstance(payload, dict):
        raise OpenAlgoHistoryValidationError("OpenAlgo history returned non-object JSON")
    return payload


def _parse_row(raw: object, instrument_id: InstrumentId) -> HistoricalCompletedCandle:
    if not isinstance(raw, dict):
        raise OpenAlgoHistoryValidationError("OpenAlgo history contains a malformed row")
    timestamp = raw.get("timestamp")
    if isinstance(timestamp, bool):
        raise OpenAlgoHistoryValidationError(
            "OpenAlgo history timestamp must be Unix epoch seconds"
        )
    if isinstance(timestamp, Decimal):
        if timestamp != timestamp.to_integral_value():
            raise OpenAlgoHistoryValidationError("OpenAlgo history timestamp must be integral")
        epoch = int(timestamp)
    elif isinstance(timestamp, int):
        epoch = timestamp
    else:
        raise OpenAlgoHistoryValidationError(
            "OpenAlgo history timestamp must be Unix epoch seconds"
        )
    start = datetime.fromtimestamp(epoch, tz=UTC).astimezone(IST)
    if start.second or start.microsecond or start.minute % 5:
        raise OpenAlgoHistoryValidationError("OpenAlgo history timestamp is not 5-minute aligned")
    end = start + timedelta(minutes=5)
    local_time = start.timetz().replace(tzinfo=None)
    if local_time.hour < 9 or (local_time.hour == 9 and local_time.minute < 15):
        raise OpenAlgoHistoryValidationError("OpenAlgo history contains a pre-market row")
    if start.hour > 15 or (start.hour == 15 and start.minute > 25):
        raise OpenAlgoHistoryValidationError("OpenAlgo history contains a post-market row")
    if end.hour > 15 or (end.hour == 15 and end.minute > 30):
        raise OpenAlgoHistoryValidationError(
            "OpenAlgo history interval exceeds regular-session boundary"
        )

    volume = raw.get("volume")
    if isinstance(volume, bool) or not isinstance(volume, int) or volume < 0:
        raise OpenAlgoHistoryValidationError(
            "OpenAlgo history volume must be a non-negative integer"
        )

    try:
        return HistoricalCompletedCandle(
            instrument_id=instrument_id,
            interval=CandleInterval(start, end),
            quality=CandleQuality.VALID,
            open=_price(raw.get("open"), "open"),
            high=_price(raw.get("high"), "high"),
            low=_price(raw.get("low"), "low"),
            close=_price(raw.get("close"), "close"),
            volume=volume,
            source="openalgo:/api/v1/history",
        )
    except ValueError as exc:
        raise OpenAlgoHistoryValidationError(
            "OpenAlgo history row violates canonical candle invariants"
        ) from exc


def _price(value: object, field: str) -> Price:
    if isinstance(value, bool) or value is None or isinstance(value, float):
        raise OpenAlgoHistoryValidationError(
            f"OpenAlgo history {field} must be exact decimal-compatible"
        )
    try:
        decimal_value = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise OpenAlgoHistoryValidationError(f"OpenAlgo history {field} is invalid") from None
    try:
        return Price(decimal_value)
    except (TypeError, ValueError) as exc:
        raise OpenAlgoHistoryValidationError(f"OpenAlgo history {field} is invalid") from exc
