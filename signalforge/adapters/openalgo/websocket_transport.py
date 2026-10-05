"""Provider-private synchronous WebSocket transport for OpenAlgo."""

from __future__ import annotations

from typing import Protocol

from websockets.exceptions import WebSocketException
from websockets.sync.client import ClientConnection, connect


class OpenAlgoWebSocketUnavailable(RuntimeError):
    """Raised when the OpenAlgo WebSocket transport cannot complete an operation."""


class OpenAlgoWebSocketConnection(Protocol):
    """Narrow connection contract used by the live adapter and deterministic fakes."""

    def send_text(self, message: str) -> None: ...

    def receive_text(self, timeout_seconds: float) -> str: ...

    def close(self) -> None: ...


class OpenAlgoWebSocketConnector(Protocol):
    """Factory contract for OpenAlgo WebSocket connections."""

    def connect(
        self,
        *,
        url: str,
        timeout_seconds: float,
    ) -> OpenAlgoWebSocketConnection: ...


class _WebsocketsConnection:
    def __init__(self, connection: ClientConnection) -> None:
        self._connection = connection

    def send_text(self, message: str) -> None:
        try:
            self._connection.send(message)
        except (OSError, WebSocketException) as exc:
            raise OpenAlgoWebSocketUnavailable("OpenAlgo WebSocket send failed") from exc

    def receive_text(self, timeout_seconds: float) -> str:
        try:
            message = self._connection.recv(timeout=timeout_seconds)
        except TimeoutError as exc:
            raise OpenAlgoWebSocketUnavailable("OpenAlgo WebSocket receive timed out") from exc
        except (OSError, WebSocketException) as exc:
            raise OpenAlgoWebSocketUnavailable("OpenAlgo WebSocket receive failed") from exc
        if not isinstance(message, str):
            raise OpenAlgoWebSocketUnavailable("OpenAlgo WebSocket returned a non-text frame")
        return message

    def close(self) -> None:
        try:
            self._connection.close()
        except (OSError, WebSocketException) as exc:
            raise OpenAlgoWebSocketUnavailable("OpenAlgo WebSocket close failed") from exc


class WebsocketsOpenAlgoConnector:
    """Concrete connector backed by the mature websockets package."""

    def connect(
        self,
        *,
        url: str,
        timeout_seconds: float,
    ) -> OpenAlgoWebSocketConnection:
        try:
            connection = connect(url, open_timeout=timeout_seconds)
        except (OSError, WebSocketException, TimeoutError) as exc:
            raise OpenAlgoWebSocketUnavailable("OpenAlgo WebSocket connect failed") from exc
        return _WebsocketsConnection(connection)
