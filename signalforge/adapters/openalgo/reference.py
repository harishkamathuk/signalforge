"""Exact OpenAlgo NSE-equity reference-data resolution for the live MVP."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
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
from signalforge.domain.instruments import Instrument, TickSizeRule, TickSizeSchedule
from signalforge.domain.money import Price
from signalforge.domain.time import require_aware, to_ist


class OpenAlgoReferenceError(RuntimeError):
    """Base failure for exact OpenAlgo instrument/reference resolution."""


class OpenAlgoReferenceNotFound(OpenAlgoReferenceError):
    """Raised when no exact configured NSE equity can be resolved."""


class OpenAlgoReferenceAmbiguous(OpenAlgoReferenceError):
    """Raised when multiple exact provider candidates remain."""


class OpenAlgoReferenceContradiction(OpenAlgoReferenceError):
    """Raised when provider reference surfaces materially disagree."""


@dataclass(frozen=True, slots=True)
class OpenAlgoSubscriptionIdentity:
    """Provider subscription identity retained outside SignalForge domain models."""

    symbol: str
    exchange: str


@dataclass(frozen=True, slots=True)
class OpenAlgoReferenceProvenance:
    """Stable audit metadata for one accepted current-trading-date snapshot."""

    trading_date: date
    observed_at: datetime
    sources: tuple[str, ...]
    provider_token: str | None
    broker_symbol: str | None
    broker_exchange: str | None

    def __post_init__(self) -> None:
        require_aware(self.observed_at)
        if not self.sources or any(not source.strip() for source in self.sources):
            raise ValueError("Reference provenance requires non-empty source identities")


@dataclass(frozen=True, slots=True)
class ResolvedOpenAlgoInstrument:
    """SignalForge-owned result of exact OpenAlgo NSE-equity resolution."""

    instrument_id: InstrumentId
    instrument: Instrument
    subscription: OpenAlgoSubscriptionIdentity
    tick_size_schedule: TickSizeSchedule
    provenance: OpenAlgoReferenceProvenance


@dataclass(frozen=True, slots=True)
class _ReferenceRow:
    symbol: str
    exchange: str
    instrument_type: str
    tick_size: Decimal
    token: str | None
    broker_symbol: str | None
    broker_exchange: str | None


def resolve_nse_equity_reference(
    *,
    config: OpenAlgoConfig,
    instrument_id: InstrumentId,
    trading_date: date,
    observed_at: datetime,
    transport: OpenAlgoTransport | None = None,
) -> ResolvedOpenAlgoInstrument:
    """Resolve one configured canonical NSE cash equity against exact OpenAlgo metadata."""

    symbol = _configured_symbol(instrument_id)
    require_aware(observed_at)
    if to_ist(observed_at).date() != trading_date:
        raise ValueError(
            "OpenAlgo reference observation date must match the requested NSE trading date"
        )
    selected_transport = transport or StdlibOpenAlgoTransport(config.host)

    symbol_response = _post_provider(
        selected_transport,
        config,
        path="/api/v1/symbol",
        payload={"symbol": symbol, "exchange": "NSE"},
    )
    search_response = _post_provider(
        selected_transport,
        config,
        path="/api/v1/search",
        payload={"query": symbol, "exchange": "NSE"},
    )

    symbol_row = _parse_symbol_response(symbol_response, symbol=symbol)
    search_row = _parse_search_response(search_response, symbol=symbol)
    _require_consistent(symbol_row, search_row)

    accepted = symbol_row
    canonical_id = InstrumentId(f"NSE:{symbol}")
    instrument = Instrument(
        instrument_id=canonical_id,
        exchange="NSE",
        symbol=symbol,
    )
    schedule = TickSizeSchedule(
        instrument_id=canonical_id,
        rules=(
            TickSizeRule(
                tick_size=Price(accepted.tick_size),
                effective_from=trading_date,
                effective_to=trading_date,
            ),
        ),
    )
    provenance = OpenAlgoReferenceProvenance(
        trading_date=trading_date,
        observed_at=observed_at,
        sources=("/api/v1/symbol", "/api/v1/search"),
        provider_token=accepted.token,
        broker_symbol=accepted.broker_symbol,
        broker_exchange=accepted.broker_exchange,
    )
    return ResolvedOpenAlgoInstrument(
        instrument_id=canonical_id,
        instrument=instrument,
        subscription=OpenAlgoSubscriptionIdentity(symbol=symbol, exchange="NSE"),
        tick_size_schedule=schedule,
        provenance=provenance,
    )


def _configured_symbol(instrument_id: InstrumentId) -> str:
    value = str(instrument_id)
    if not value.startswith("NSE:") or value.count(":") != 1:
        raise ValueError("SF-055 requires canonical InstrumentId in NSE:<SYMBOL> form")
    symbol = value.removeprefix("NSE:")
    if not symbol or symbol != symbol.strip() or symbol != symbol.upper():
        raise ValueError("Configured NSE symbol must be non-empty, trimmed and uppercase")
    return symbol


def _post_provider(
    transport: OpenAlgoTransport,
    config: OpenAlgoConfig,
    *,
    path: str,
    payload: dict[str, object],
) -> OpenAlgoHttpResponse:
    request = {"apikey": config.api_key.get_secret_value(), **payload}
    try:
        return transport.post_json(
            path=path,
            payload=request,
            connect_timeout_seconds=config.connect_timeout_seconds,
            request_timeout_seconds=config.request_timeout_seconds,
        )
    except OpenAlgoTransportUnavailable:
        raise OpenAlgoReferenceError("OpenAlgo reference-data request was unreachable") from None


def _parse_symbol_response(response: OpenAlgoHttpResponse, *, symbol: str) -> _ReferenceRow:
    payload = _decode_provider_object(response, source="/api/v1/symbol")
    if response.status_code != 200 or payload.get("status") != "success":
        raise OpenAlgoReferenceError("OpenAlgo symbol lookup did not succeed")
    data = payload.get("data")
    if not isinstance(data, dict):
        raise OpenAlgoReferenceError("OpenAlgo symbol lookup omitted an object data payload")
    row = _reference_row(data)
    _require_exact_equity(row, symbol=symbol)
    return row


def _parse_search_response(response: OpenAlgoHttpResponse, *, symbol: str) -> _ReferenceRow:
    payload = _decode_provider_object(response, source="/api/v1/search")
    if response.status_code != 200 or payload.get("status") != "success":
        raise OpenAlgoReferenceError("OpenAlgo search lookup did not succeed")
    data = payload.get("data")
    if not isinstance(data, list):
        raise OpenAlgoReferenceError("OpenAlgo search lookup omitted an array data payload")

    exact: list[_ReferenceRow] = []
    for item in data:
        if not isinstance(item, dict):
            raise OpenAlgoReferenceError("OpenAlgo search returned a malformed candidate")
        row = _reference_row(item)
        if row.symbol == symbol and row.exchange == "NSE" and row.instrument_type == "EQ":
            exact.append(row)

    if not exact:
        raise OpenAlgoReferenceNotFound(
            f"No exact OpenAlgo NSE cash-equity reference found for {symbol}"
        )
    if len(exact) != 1:
        raise OpenAlgoReferenceAmbiguous(
            f"Multiple exact OpenAlgo NSE cash-equity references found for {symbol}"
        )
    return exact[0]


def _decode_provider_object(
    response: OpenAlgoHttpResponse,
    *,
    source: str,
) -> dict[str, Any]:
    if response.content_type is not None and "application/json" not in response.content_type.lower():
        raise OpenAlgoReferenceError(f"{source} returned a non-JSON content type")
    try:
        decoded = json.loads(
            response.body.decode("utf-8"),
            parse_float=Decimal,
        )
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise OpenAlgoReferenceError(f"{source} returned malformed JSON") from None
    if not isinstance(decoded, dict):
        raise OpenAlgoReferenceError(f"{source} returned non-object JSON")
    return decoded


def _reference_row(data: dict[str, Any]) -> _ReferenceRow:
    symbol = _required_text(data, "symbol")
    exchange = _required_text(data, "exchange")
    instrument_type = _required_text(data, "instrumenttype")
    tick_size = _required_tick_size(data.get("tick_size"))
    return _ReferenceRow(
        symbol=symbol,
        exchange=exchange,
        instrument_type=instrument_type,
        tick_size=tick_size,
        token=_optional_text(data.get("token")),
        broker_symbol=_optional_text(data.get("brsymbol")),
        broker_exchange=_optional_text(data.get("brexchange")),
    )


def _required_text(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise OpenAlgoReferenceError(f"OpenAlgo reference field {key} must be non-empty text")
    return value.strip()


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise OpenAlgoReferenceError("OpenAlgo optional reference identifiers must be non-empty text")
    return value.strip()


def _required_tick_size(value: object) -> Decimal:
    if isinstance(value, bool) or value is None or isinstance(value, float):
        raise OpenAlgoReferenceError("OpenAlgo tick_size must be an exact decimal-compatible value")
    try:
        tick = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise OpenAlgoReferenceError("OpenAlgo tick_size is not a valid decimal") from None
    if not tick.is_finite() or tick <= 0:
        raise OpenAlgoReferenceError("OpenAlgo tick_size must be finite and strictly positive")
    return tick


def _require_exact_equity(row: _ReferenceRow, *, symbol: str) -> None:
    if row.symbol != symbol:
        raise OpenAlgoReferenceContradiction("OpenAlgo symbol response contradicts configured symbol")
    if row.exchange != "NSE":
        raise OpenAlgoReferenceContradiction("OpenAlgo symbol response contradicts NSE exchange")
    if row.instrument_type != "EQ":
        raise OpenAlgoReferenceContradiction("OpenAlgo symbol response is not an NSE cash equity")


def _require_consistent(primary: _ReferenceRow, secondary: _ReferenceRow) -> None:
    if (
        primary.symbol != secondary.symbol
        or primary.exchange != secondary.exchange
        or primary.instrument_type != secondary.instrument_type
        or primary.tick_size != secondary.tick_size
    ):
        raise OpenAlgoReferenceContradiction(
            "OpenAlgo symbol and search reference data contradict each other"
        )
