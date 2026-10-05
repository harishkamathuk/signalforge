from __future__ import annotations

from dataclasses import dataclass

import pytest

import signalforge.adapters.openalgo.websocket_transport as ws_transport
from signalforge.adapters.openalgo.websocket_transport import (
    OpenAlgoWebSocketReceiveTimeout,
    OpenAlgoWebSocketUnavailable,
    WebsocketsOpenAlgoConnector,
)


@dataclass
class RawConnection:
    recv_value: object = "message"
    send_error: Exception | None = None
    recv_error: Exception | None = None
    close_error: Exception | None = None
    sent: object | None = None
    recv_timeout: float | None = None
    closed: bool = False

    def send(self, message: object) -> None:
        if self.send_error is not None:
            raise self.send_error
        self.sent = message

    def recv(self, *, timeout: float) -> object:
        self.recv_timeout = timeout
        if self.recv_error is not None:
            raise self.recv_error
        return self.recv_value

    def close(self) -> None:
        if self.close_error is not None:
            raise self.close_error
        self.closed = True


def test_connector_wraps_successful_websocket_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    raw = RawConnection()
    calls: list[tuple[str, float]] = []

    def fake_connect(url: str, *, open_timeout: float) -> RawConnection:
        calls.append((url, open_timeout))
        return raw

    monkeypatch.setattr(ws_transport, "connect", fake_connect)
    connection = WebsocketsOpenAlgoConnector().connect(
        url="ws://127.0.0.1:8765",
        timeout_seconds=4.5,
    )

    connection.send_text("hello")
    assert connection.receive_text(2.5) == "message"
    connection.close()

    assert calls == [("ws://127.0.0.1:8765", 4.5)]
    assert raw.sent == "hello"
    assert raw.recv_timeout == 2.5
    assert raw.closed


@pytest.mark.parametrize("error", [OSError("network"), TimeoutError("timeout")])
def test_connector_maps_connection_failures(
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
) -> None:
    def fake_connect(url: str, *, open_timeout: float) -> RawConnection:
        raise error

    monkeypatch.setattr(ws_transport, "connect", fake_connect)

    with pytest.raises(OpenAlgoWebSocketUnavailable, match="connect failed"):
        WebsocketsOpenAlgoConnector().connect(
            url="ws://127.0.0.1:8765",
            timeout_seconds=1,
        )


def test_receive_timeout_has_distinct_class(monkeypatch: pytest.MonkeyPatch) -> None:
    raw = RawConnection(recv_error=TimeoutError("quiet"))
    monkeypatch.setattr(ws_transport, "connect", lambda *_args, **_kwargs: raw)
    connection = WebsocketsOpenAlgoConnector().connect(
        url="ws://127.0.0.1:8765",
        timeout_seconds=1,
    )

    with pytest.raises(OpenAlgoWebSocketReceiveTimeout):
        connection.receive_text(1)


def test_receive_transport_failure_maps_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    raw = RawConnection(recv_error=OSError("lost"))
    monkeypatch.setattr(ws_transport, "connect", lambda *_args, **_kwargs: raw)
    connection = WebsocketsOpenAlgoConnector().connect(
        url="ws://127.0.0.1:8765",
        timeout_seconds=1,
    )

    with pytest.raises(OpenAlgoWebSocketUnavailable, match="receive failed"):
        connection.receive_text(1)


def test_non_text_frame_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    raw = RawConnection(recv_value=b"bytes")
    monkeypatch.setattr(ws_transport, "connect", lambda *_args, **_kwargs: raw)
    connection = WebsocketsOpenAlgoConnector().connect(
        url="ws://127.0.0.1:8765",
        timeout_seconds=1,
    )

    with pytest.raises(OpenAlgoWebSocketUnavailable, match="non-text"):
        connection.receive_text(1)


def test_send_failure_maps_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    raw = RawConnection(send_error=OSError("lost"))
    monkeypatch.setattr(ws_transport, "connect", lambda *_args, **_kwargs: raw)
    connection = WebsocketsOpenAlgoConnector().connect(
        url="ws://127.0.0.1:8765",
        timeout_seconds=1,
    )

    with pytest.raises(OpenAlgoWebSocketUnavailable, match="send failed"):
        connection.send_text("message")


def test_close_failure_maps_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    raw = RawConnection(close_error=OSError("lost"))
    monkeypatch.setattr(ws_transport, "connect", lambda *_args, **_kwargs: raw)
    connection = WebsocketsOpenAlgoConnector().connect(
        url="ws://127.0.0.1:8765",
        timeout_seconds=1,
    )

    with pytest.raises(OpenAlgoWebSocketUnavailable, match="close failed"):
        connection.close()
