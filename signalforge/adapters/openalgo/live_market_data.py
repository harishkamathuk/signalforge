"""Live single-security OpenAlgo Quote adapter and feed-state machine."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from signalforge.adapters.openalgo.config import OpenAlgoConfig
from signalforge.adapters.openalgo.market_data_config import OpenAlgoMarketDataConfig
from signalforge.adapters.openalgo.reference import OpenAlgoSubscriptionIdentity
from signalforge.adapters.openalgo.websocket_transport import (
    OpenAlgoWebSocketConnection,
    OpenAlgoWebSocketConnector,
    OpenAlgoWebSocketUnavailable,
    WebsocketsOpenAlgoConnector,
)
from signalforge.domain.ids import InstrumentId
from signalforge.domain.market import MarketEvent
from signalforge.domain.money import Price
from signalforge.runtime.eligibility import MarketDataFeedState

OPENALGO_MARKET_DATA_SOURCE = "openalgo:quote"


class OpenAlgoMarketDataError(RuntimeError):
    """Base live market-data adapter failure."""


class OpenAlgoMarketDataProtocolError(OpenAlgoMarketDataError):
    """Raised for malformed or contradictory provider protocol data."""


class OpenAlgoMarketDataContinuityError(OpenAlgoMarketDataError):
    """Raised when quote chronology or cumulative volume regresses."""


class OpenAlgoMarketDataDisconnected(OpenAlgoMarketDataError):
    """Raised when the active WebSocket transport is lost."""


class OpenAlgoMarketDataAdapter:
    """Own OpenAlgo WebSocket lifecycle and emit canonical observed trade events."""

    def __init__(
        self,
        *,
        config: OpenAlgoConfig,
        market_data_config: OpenAlgoMarketDataConfig,
        instrument_id: InstrumentId,
        subscription: OpenAlgoSubscriptionIdentity,
        connector: OpenAlgoWebSocketConnector | None = None,
        wall_clock: Callable[[], datetime],
        monotonic_clock: Callable[[], float],
        sleep: Callable[[float], None],
    ) -> None:
        expected = f"{subscription.exchange}:{subscription.symbol}"
        if str(instrument_id) != expected:
            raise ValueError("InstrumentId and OpenAlgo subscription identity must match exactly")
        self._config = config
        self._md_config = market_data_config
        self._instrument_id = instrument_id
        self._subscription = subscription
        self._connector = connector or WebsocketsOpenAlgoConnector()
        self._wall_clock = wall_clock
        self._monotonic_clock = monotonic_clock
        self._sleep = sleep
        self._connection: OpenAlgoWebSocketConnection | None = None
        self._state = MarketDataFeedState.STARTING
        self._baseline_volume: int | None = None
        self._last_timestamp_ms: int | None = None
        self._last_valid_monotonic: float | None = None

    @property
    def state(self) -> MarketDataFeedState:
        return self._state

    def start(self) -> None:
        """Connect, authenticate and subscribe; remain STARTING until valid quote data arrives."""

        self._state = MarketDataFeedState.STARTING
        self._reset_stream_baseline()
        try:
            self._connection = self._connector.connect(
                url=self._md_config.ws_url,
                timeout_seconds=self._md_config.connect_timeout_seconds,
            )
            self._authenticate_and_subscribe()
        except (OpenAlgoWebSocketUnavailable, OpenAlgoMarketDataError):
            self._state = MarketDataFeedState.FAILED
            self._close_transport()
            raise

    def receive_once(self) -> MarketEvent | None:
        """Receive and apply one provider message, returning an event only for positive volume delta."""

        connection = self._require_connection()
        try:
            raw = connection.receive_text(self._md_config.receive_timeout_seconds)
        except OpenAlgoWebSocketUnavailable as exc:
            self._state = MarketDataFeedState.DISCONNECTED
            self._connection = None
            self._reset_stream_baseline()
            raise OpenAlgoMarketDataDisconnected("OpenAlgo market-data connection was lost") from exc

        payload = _decode_object(raw)
        return self._apply_market_data(payload)

    def check_stale(self) -> MarketDataFeedState:
        """Advance HEALTHY to STALE when the operational no-data threshold is exceeded."""

        if self._state not in {MarketDataFeedState.HEALTHY, MarketDataFeedState.STALE}:
            return self._state
        if self._last_valid_monotonic is None:
            return self._state
        age = self._monotonic_clock() - self._last_valid_monotonic
        if age > self._md_config.stale_after_seconds:
            self._state = MarketDataFeedState.STALE
        return self._state

    def recover(self) -> None:
        """Reconnect, re-authenticate and re-subscribe after a transport disconnect."""

        if self._state is not MarketDataFeedState.DISCONNECTED:
            raise OpenAlgoMarketDataError("Recovery requires DISCONNECTED feed state")
        self._state = MarketDataFeedState.RECOVERING
        self._reset_stream_baseline()

        attempts = self._md_config.reconnect_attempts
        for attempt in range(attempts):
            if attempt:
                self._sleep(self._md_config.reconnect_delay_seconds)
            try:
                self._connection = self._connector.connect(
                    url=self._md_config.ws_url,
                    timeout_seconds=self._md_config.connect_timeout_seconds,
                )
                self._authenticate_and_subscribe()
                return
            except (OpenAlgoWebSocketUnavailable, OpenAlgoMarketDataError):
                self._close_transport()
        self._state = MarketDataFeedState.FAILED
        raise OpenAlgoMarketDataError("OpenAlgo market-data recovery attempts were exhausted")

    def close(self) -> None:
        """Best-effort unsubscribe and close without leaking the API key."""

        connection = self._connection
        if connection is None:
            return
        try:
            connection.send_text(
                json.dumps(
                    {
                        "action": "unsubscribe",
                        "symbols": [_symbol_payload(self._subscription)],
                        "mode": "Quote",
                    },
                    separators=(",", ":"),
                )
            )
        except OpenAlgoWebSocketUnavailable:
            pass
        self._close_transport()

    def _authenticate_and_subscribe(self) -> None:
        connection = self._require_connection()
        connection.send_text(
            json.dumps(
                {
                    "action": "authenticate",
                    "api_key": self._config.api_key.get_secret_value(),
                },
                separators=(",", ":"),
            )
        )
        auth = _decode_object(connection.receive_text(self._md_config.receive_timeout_seconds))
        if auth.get("type") != "auth" or auth.get("status") != "success":
            raise OpenAlgoMarketDataProtocolError("OpenAlgo WebSocket authentication failed")

        connection.send_text(
            json.dumps(
                {
                    "action": "subscribe",
                    "symbols": [_symbol_payload(self._subscription)],
                    "mode": "Quote",
                },
                separators=(",", ":"),
            )
        )
        ack = _decode_object(connection.receive_text(self._md_config.receive_timeout_seconds))
        if ack.get("type") != "subscribe" or ack.get("status") != "success":
            raise OpenAlgoMarketDataProtocolError("OpenAlgo Quote subscription failed")
        subscriptions = ack.get("subscriptions")
        if subscriptions is not None:
            if not isinstance(subscriptions, list) or len(subscriptions) != 1:
                raise OpenAlgoMarketDataProtocolError("OpenAlgo subscription acknowledgement is ambiguous")
            item = subscriptions[0]
            if not isinstance(item, dict):
                raise OpenAlgoMarketDataProtocolError("OpenAlgo subscription acknowledgement is malformed")
            if (
                item.get("symbol") != self._subscription.symbol
                or item.get("exchange") != self._subscription.exchange
                or str(item.get("mode", "")).upper() != "QUOTE"
            ):
                raise OpenAlgoMarketDataProtocolError(
                    "OpenAlgo subscription acknowledgement contradicts requested identity"
                )

    def _apply_market_data(self, payload: dict[str, Any]) -> MarketEvent | None:
        if payload.get("type") != "market_data":
            raise OpenAlgoMarketDataProtocolError("Expected OpenAlgo market_data message")
        if (
            payload.get("symbol") != self._subscription.symbol
            or payload.get("exchange") != self._subscription.exchange
        ):
            raise OpenAlgoMarketDataProtocolError("OpenAlgo market data is for another instrument")
        mode = payload.get("mode")
        if not (mode == 2 or (isinstance(mode, str) and mode.lower() == "quote")):
            raise OpenAlgoMarketDataProtocolError("OpenAlgo market data must use Quote mode")
        data = payload.get("data")
        if not isinstance(data, dict):
            raise OpenAlgoMarketDataProtocolError("OpenAlgo Quote data must be an object")

        price = _positive_decimal(data.get("ltp"), field="ltp")
        volume = _non_negative_int(data.get("volume"), field="volume")
        timestamp_ms = _non_negative_int(data.get("timestamp"), field="timestamp")
        if self._last_timestamp_ms is not None and timestamp_ms < self._last_timestamp_ms:
            raise OpenAlgoMarketDataContinuityError("OpenAlgo provider timestamp regressed")

        now_mono = self._monotonic_clock()
        received_at = self._wall_clock()
        if received_at.tzinfo is None or received_at.utcoffset() is None:
            raise ValueError("Injected wall clock must return a timezone-aware datetime")

        prior_volume = self._baseline_volume
        self._baseline_volume = volume
        self._last_timestamp_ms = timestamp_ms
        self._last_valid_monotonic = now_mono
        self._state = MarketDataFeedState.HEALTHY

        if prior_volume is None or volume == prior_volume:
            return None
        if volume < prior_volume:
            raise OpenAlgoMarketDataContinuityError("OpenAlgo cumulative volume regressed")

        exchange_timestamp = datetime(1970, 1, 1, tzinfo=UTC) + timedelta(milliseconds=timestamp_ms)
        return MarketEvent(
            instrument_id=self._instrument_id,
            exchange_timestamp=exchange_timestamp,
            received_timestamp=received_at,
            price=Price(price),
            quantity=volume - prior_volume,
            source=OPENALGO_MARKET_DATA_SOURCE,
            source_event_id=None,
        )

    def _require_connection(self) -> OpenAlgoWebSocketConnection:
        if self._connection is None:
            raise OpenAlgoMarketDataDisconnected("OpenAlgo market-data connection is not active")
        return self._connection

    def _reset_stream_baseline(self) -> None:
        self._baseline_volume = None
        self._last_timestamp_ms = None
        self._last_valid_monotonic = None

    def _close_transport(self) -> None:
        connection, self._connection = self._connection, None
        if connection is not None:
            try:
                connection.close()
            except OpenAlgoWebSocketUnavailable:
                pass


def _symbol_payload(subscription: OpenAlgoSubscriptionIdentity) -> dict[str, str]:
    return {"symbol": subscription.symbol, "exchange": subscription.exchange}


def _decode_object(raw: str) -> dict[str, Any]:
    try:
        payload = json.loads(raw, parse_float=Decimal)
    except json.JSONDecodeError:
        raise OpenAlgoMarketDataProtocolError("OpenAlgo WebSocket returned malformed JSON") from None
    if not isinstance(payload, dict):
        raise OpenAlgoMarketDataProtocolError("OpenAlgo WebSocket message must be a JSON object")
    return payload


def _positive_decimal(value: object, *, field: str) -> Decimal:
    if isinstance(value, bool) or value is None or isinstance(value, float):
        raise OpenAlgoMarketDataProtocolError(f"OpenAlgo {field} must be exact decimal-compatible")
    try:
        result = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise OpenAlgoMarketDataProtocolError(f"OpenAlgo {field} is not a valid decimal") from None
    if not result.is_finite() or result <= 0:
        raise OpenAlgoMarketDataProtocolError(f"OpenAlgo {field} must be finite and positive")
    return result


def _non_negative_int(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise OpenAlgoMarketDataProtocolError(
            f"OpenAlgo {field} must be a non-negative integer"
        )
    return value
