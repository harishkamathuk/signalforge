from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from signalforge.adapters.openalgo.config import OpenAlgoConfig
from signalforge.adapters.openalgo.live_market_data import (
    OPENALGO_MARKET_DATA_SOURCE,
    OpenAlgoMarketDataAdapter,
    OpenAlgoMarketDataContinuityError,
    OpenAlgoMarketDataDisconnected,
    OpenAlgoMarketDataError,
    OpenAlgoMarketDataProtocolError,
)
from signalforge.adapters.openalgo.market_data_config import OpenAlgoMarketDataConfig
from signalforge.adapters.openalgo.reference import OpenAlgoSubscriptionIdentity
from signalforge.adapters.openalgo.websocket_transport import (
    OpenAlgoWebSocketReceiveTimeout,
    OpenAlgoWebSocketUnavailable,
)
from signalforge.domain.ids import InstrumentId
from signalforge.runtime.eligibility import MarketDataFeedState


REST_CONFIG = OpenAlgoConfig(host="http://127.0.0.1:5000", api_key="super-secret-key")
MD_CONFIG = OpenAlgoMarketDataConfig(
    ws_url="ws://127.0.0.1:8765",
    stale_after_seconds=10,
    reconnect_attempts=2,
    reconnect_delay_seconds=0,
    receive_timeout_seconds=1,
)
IDENTITY = OpenAlgoSubscriptionIdentity(symbol="RELIANCE", exchange="NSE")
INSTRUMENT_ID = InstrumentId("NSE:RELIANCE")
WALL_TIME = datetime(2026, 10, 5, 4, 0, tzinfo=UTC)


def auth_success() -> str:
    return '{"type":"auth","status":"success","broker":"zerodha"}'


def subscribe_success() -> str:
    return (
        '{"type":"subscribe","status":"success","subscriptions":['
        '{"symbol":"RELIANCE","exchange":"NSE","mode":"QUOTE"}]}'
    )


def quote(
    *,
    price: str = "1424.05",
    volume: int = 100_000,
    timestamp: int = 1_756_376_445_123,
    symbol: str = "RELIANCE",
    exchange: str = "NSE",
    mode: object = 2,
) -> str:
    mode_json = json.dumps(mode)
    return (
        '{"type":"market_data",'
        f'"symbol":"{symbol}","exchange":"{exchange}","mode":{mode_json},'
        f'"data":{{"ltp":{price},"volume":{volume},"timestamp":{timestamp},'
        '"open":1400.0,"high":1430.0,"low":1395.0,"close":1410.0}}}'
    )


@dataclass
class FakeConnection:
    messages: list[object]
    sent: list[str] = field(default_factory=list)
    closed: bool = False

    def send_text(self, message: str) -> None:
        if self.closed:
            raise OpenAlgoWebSocketUnavailable("closed")
        self.sent.append(message)

    def receive_text(self, timeout_seconds: float) -> str:
        assert timeout_seconds > 0
        if not self.messages:
            raise OpenAlgoWebSocketReceiveTimeout("timeout")
        item = self.messages.pop(0)
        if isinstance(item, Exception):
            raise item
        assert isinstance(item, str)
        return item

    def close(self) -> None:
        self.closed = True


@dataclass
class FakeConnector:
    connections: list[object]
    urls: list[str] = field(default_factory=list)

    def connect(self, *, url: str, timeout_seconds: float) -> FakeConnection:
        self.urls.append(url)
        assert timeout_seconds > 0
        if not self.connections:
            raise OpenAlgoWebSocketUnavailable("no connection")
        item = self.connections.pop(0)
        if isinstance(item, Exception):
            raise item
        assert isinstance(item, FakeConnection)
        return item


@dataclass
class Clocks:
    monotonic: float = 100.0
    wall: datetime = WALL_TIME

    def mono(self) -> float:
        return self.monotonic

    def now(self) -> datetime:
        return self.wall


def adapter_for(
    connection: FakeConnection,
    *,
    clocks: Clocks | None = None,
    connector: FakeConnector | None = None,
    config: OpenAlgoMarketDataConfig = MD_CONFIG,
) -> tuple[OpenAlgoMarketDataAdapter, Clocks, FakeConnector]:
    actual_clocks = clocks or Clocks()
    actual_connector = connector or FakeConnector([connection])
    adapter = OpenAlgoMarketDataAdapter(
        config=REST_CONFIG,
        market_data_config=config,
        instrument_id=INSTRUMENT_ID,
        subscription=IDENTITY,
        connector=actual_connector,
        wall_clock=actual_clocks.now,
        monotonic_clock=actual_clocks.mono,
        sleep=lambda _: None,
    )
    return adapter, actual_clocks, actual_connector


def started(*extra_messages: object) -> tuple[
    OpenAlgoMarketDataAdapter,
    FakeConnection,
    Clocks,
    FakeConnector,
]:
    connection = FakeConnection([auth_success(), subscribe_success(), *extra_messages])
    adapter, clocks, connector = adapter_for(connection)
    adapter.start()
    return adapter, connection, clocks, connector


@pytest.mark.parametrize(
    "url",
    [
        "ws://127.0.0.1:8765",
        "ws://127.22.1.8:8765",
        "ws://localhost:8765",
        "ws://[::1]:8765",
        "wss://feed.example.com/ws",
    ],
)
def test_websocket_url_security_allows_loopback_ws_and_remote_wss(url: str) -> None:
    assert OpenAlgoMarketDataConfig(ws_url=url).ws_url == url


@pytest.mark.parametrize(
    "url",
    [
        "ws://feed.example.com:8765",
        "ws://192.168.1.10:8765",
        "wss://user:pass@feed.example.com/ws",
        "ftp://feed.example.com",
        "wss://feed.example.com/ws?key=secret",
        "ws://localhost:abc",
    ],
)
def test_websocket_url_security_rejects_unsafe_or_invalid_urls(url: str) -> None:
    with pytest.raises(ValueError):
        OpenAlgoMarketDataConfig(ws_url=url)


def test_start_authenticates_and_subscribes_quote_without_becoming_healthy() -> None:
    adapter, connection, _, connector = started()

    assert adapter.state is MarketDataFeedState.STARTING
    assert connector.urls == ["ws://127.0.0.1:8765"]
    auth = json.loads(connection.sent[0])
    subscribe = json.loads(connection.sent[1])
    assert auth == {"action": "authenticate", "api_key": "super-secret-key"}
    assert subscribe == {
        "action": "subscribe",
        "symbols": [{"symbol": "RELIANCE", "exchange": "NSE"}],
        "mode": "Quote",
    }


@pytest.mark.parametrize(
    "first_response",
    [
        '{"type":"auth","status":"error","message":"Authentication failed"}',
        '{"type":"wrong","status":"success"}',
    ],
)
def test_authentication_failure_is_failed_without_secret_leak(first_response: str) -> None:
    connection = FakeConnection([first_response])
    adapter, _, _ = adapter_for(connection)

    with pytest.raises(OpenAlgoMarketDataProtocolError) as exc_info:
        adapter.start()

    assert adapter.state is MarketDataFeedState.FAILED
    assert "super-secret-key" not in str(exc_info.value)


def test_subscription_success_without_exact_confirmation_is_failed() -> None:
    connection = FakeConnection(
        [auth_success(), '{"type":"subscribe","status":"success"}']
    )
    adapter, _, _ = adapter_for(connection)

    with pytest.raises(OpenAlgoMarketDataProtocolError):
        adapter.start()

    assert adapter.state is MarketDataFeedState.FAILED


def test_subscription_rejection_is_failed() -> None:
    connection = FakeConnection(
        [auth_success(), '{"type":"subscribe","status":"partial","message":"rejected"}']
    )
    adapter, _, _ = adapter_for(connection)

    with pytest.raises(OpenAlgoMarketDataProtocolError):
        adapter.start()

    assert adapter.state is MarketDataFeedState.FAILED


def test_starting_feed_becomes_stale_if_no_first_quote_arrives() -> None:
    adapter, connection, clocks, _ = started()
    clocks.monotonic += 11
    connection.messages.append(OpenAlgoWebSocketReceiveTimeout("quiet"))

    assert adapter.receive_once() is None
    assert adapter.state is MarketDataFeedState.STALE


def test_first_quote_establishes_baseline_and_becomes_healthy() -> None:
    adapter, _, _, _ = started(quote(volume=100))

    assert adapter.receive_once() is None
    assert adapter.state is MarketDataFeedState.HEALTHY


def test_unchanged_volume_emits_no_event() -> None:
    adapter, connection, _, _ = started(quote(volume=100))
    assert adapter.receive_once() is None
    connection.messages.append(quote(volume=100, timestamp=1_756_376_445_124))

    assert adapter.receive_once() is None


def test_positive_volume_delta_emits_canonical_market_event_with_decimal_precision() -> None:
    precise = "1424.01234567890123456789"
    adapter, connection, _, _ = started(quote(price=precise, volume=100))
    assert adapter.receive_once() is None
    connection.messages.append(
        quote(price=precise, volume=137, timestamp=1_756_376_445_124)
    )

    event = adapter.receive_once()

    assert event is not None
    assert event.instrument_id == INSTRUMENT_ID
    assert event.price.value == Decimal(precise)
    assert event.quantity == 37
    assert event.source == OPENALGO_MARKET_DATA_SOURCE
    assert event.source_event_id is None
    assert event.received_timestamp == WALL_TIME
    assert event.exchange_timestamp == datetime(
        2025, 8, 28, 10, 20, 45, 124000, tzinfo=UTC
    )


def test_same_timestamp_with_higher_volume_is_allowed() -> None:
    timestamp = 1_756_376_445_123
    adapter, connection, _, _ = started(quote(volume=100, timestamp=timestamp))
    assert adapter.receive_once() is None
    connection.messages.append(quote(volume=102, timestamp=timestamp))

    event = adapter.receive_once()

    assert event is not None
    assert event.quantity == 2


def test_volume_regression_fails_closed_without_rebasing() -> None:
    adapter, connection, _, _ = started(quote(volume=100))
    assert adapter.receive_once() is None
    connection.messages.append(quote(volume=99, timestamp=1_756_376_445_124))

    with pytest.raises(OpenAlgoMarketDataContinuityError):
        adapter.receive_once()

    assert adapter.state is MarketDataFeedState.FAILED


def test_timestamp_regression_fails_closed() -> None:
    timestamp = 1_756_376_445_123
    adapter, connection, _, _ = started(quote(volume=100, timestamp=timestamp))
    assert adapter.receive_once() is None
    connection.messages.append(quote(volume=101, timestamp=timestamp - 1))

    with pytest.raises(OpenAlgoMarketDataContinuityError):
        adapter.receive_once()

    assert adapter.state is MarketDataFeedState.FAILED


def test_second_based_timestamp_is_rejected_instead_of_guessed_as_milliseconds() -> None:
    adapter, _, _, _ = started(quote(timestamp=1_756_376_445))

    with pytest.raises(OpenAlgoMarketDataProtocolError, match="epoch-millisecond"):
        adapter.receive_once()


@pytest.mark.parametrize(
    "payload",
    [
        quote(symbol="TCS"),
        quote(exchange="BSE"),
        quote(mode=1),
        quote(mode="ltp"),
        '{"type":"market_data","symbol":"RELIANCE","exchange":"NSE","mode":2,"data":{}}',
        "not-json",
    ],
)
def test_wrong_instrument_mode_or_malformed_data_is_rejected(payload: str) -> None:
    adapter, _, _, _ = started(payload)

    with pytest.raises(OpenAlgoMarketDataProtocolError):
        adapter.receive_once()


def test_receive_timeout_drives_stale_not_disconnect() -> None:
    adapter, connection, clocks, _ = started(quote(volume=100))
    assert adapter.receive_once() is None
    clocks.monotonic += 11
    connection.messages.append(OpenAlgoWebSocketReceiveTimeout("quiet"))

    assert adapter.receive_once() is None
    assert adapter.state is MarketDataFeedState.STALE


def test_stale_threshold_boundary_is_not_early() -> None:
    adapter, _, clocks, _ = started(quote(volume=100))
    assert adapter.receive_once() is None
    clocks.monotonic += 10

    assert adapter.check_stale() is MarketDataFeedState.HEALTHY
    clocks.monotonic += 0.001
    assert adapter.check_stale() is MarketDataFeedState.STALE


def test_valid_quote_restores_stale_to_healthy() -> None:
    adapter, connection, clocks, _ = started(quote(volume=100))
    assert adapter.receive_once() is None
    clocks.monotonic += 11
    assert adapter.check_stale() is MarketDataFeedState.STALE
    connection.messages.append(quote(volume=100, timestamp=1_756_376_445_124))

    assert adapter.receive_once() is None
    assert adapter.state is MarketDataFeedState.HEALTHY


def test_transport_loss_enters_disconnected() -> None:
    adapter, connection, _, _ = started()
    connection.messages.append(OpenAlgoWebSocketUnavailable("lost"))

    with pytest.raises(OpenAlgoMarketDataDisconnected):
        adapter.receive_once()

    assert adapter.state is MarketDataFeedState.DISCONNECTED


def test_reconnect_reauthenticates_resubscribes_and_rebaselines() -> None:
    first = FakeConnection(
        [auth_success(), subscribe_success(), quote(volume=100), OpenAlgoWebSocketUnavailable("lost")]
    )
    second = FakeConnection(
        [
            auth_success(),
            subscribe_success(),
            quote(volume=150, timestamp=1_756_376_445_200),
            quote(volume=155, timestamp=1_756_376_445_201),
        ]
    )
    connector = FakeConnector([first, second])
    adapter, _, _ = adapter_for(first, connector=connector)
    adapter.start()
    assert adapter.receive_once() is None
    with pytest.raises(OpenAlgoMarketDataDisconnected):
        adapter.receive_once()

    adapter.recover()
    assert adapter.state is MarketDataFeedState.RECOVERING
    assert adapter.receive_once() is None
    assert adapter.state is MarketDataFeedState.HEALTHY
    event = adapter.receive_once()
    assert event is not None
    assert event.quantity == 5
    assert len(second.sent) == 2


def test_exhausted_recovery_enters_failed() -> None:
    first = FakeConnection([auth_success(), subscribe_success(), OpenAlgoWebSocketUnavailable("lost")])
    connector = FakeConnector(
        [
            first,
            OpenAlgoWebSocketUnavailable("retry1"),
            OpenAlgoWebSocketUnavailable("retry2"),
        ]
    )
    adapter, _, _ = adapter_for(first, connector=connector)
    adapter.start()
    with pytest.raises(OpenAlgoMarketDataDisconnected):
        adapter.receive_once()

    with pytest.raises(OpenAlgoMarketDataError, match="exhausted"):
        adapter.recover()

    assert adapter.state is MarketDataFeedState.FAILED


def test_close_unsubscribes_and_disconnects() -> None:
    adapter, connection, _, _ = started()

    adapter.close()

    assert connection.closed
    assert adapter.state is MarketDataFeedState.DISCONNECTED
    assert json.loads(connection.sent[-1]) == {
        "action": "unsubscribe",
        "symbols": [{"symbol": "RELIANCE", "exchange": "NSE"}],
        "mode": "Quote",
    }


def test_adapter_repr_and_config_repr_do_not_leak_api_key() -> None:
    adapter, _, _, _ = started()

    assert "super-secret-key" not in repr(adapter)
    assert "super-secret-key" not in repr(REST_CONFIG)


def test_adapter_has_no_order_methods() -> None:
    public_names = {name for name in dir(OpenAlgoMarketDataAdapter) if not name.startswith("_")}

    assert not public_names & {
        "place_order",
        "modify_order",
        "cancel_order",
        "placeorder",
        "modifyorder",
        "cancelorder",
    }
