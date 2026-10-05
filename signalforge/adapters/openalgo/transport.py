"""Provider-private HTTP transport for the OpenAlgo REST adapter."""

from __future__ import annotations

import http.client
import socket
import ssl
from dataclasses import dataclass
from json import dumps
from typing import Protocol
from urllib.parse import urlsplit


@dataclass(frozen=True, slots=True)
class OpenAlgoHttpResponse:
    """Raw provider response retained strictly inside the OpenAlgo adapter package."""

    status_code: int
    body: bytes
    content_type: str | None


class OpenAlgoTransportUnavailable(RuntimeError):
    """Raised when the OpenAlgo service cannot be reached or read safely."""


class OpenAlgoTransport(Protocol):
    """Minimal injected transport contract used by the OpenAlgo preflight."""

    def post_json(
        self,
        *,
        path: str,
        payload: dict[str, object],
        connect_timeout_seconds: float,
        request_timeout_seconds: float,
    ) -> OpenAlgoHttpResponse: ...


class StdlibOpenAlgoTransport:
    """Small dependency-free REST transport for the SF-054 preflight boundary."""

    def __init__(self, host: str) -> None:
        parsed = urlsplit(host)
        self._scheme = parsed.scheme
        self._hostname = parsed.hostname or ""
        self._port = parsed.port

    def post_json(
        self,
        *,
        path: str,
        payload: dict[str, object],
        connect_timeout_seconds: float,
        request_timeout_seconds: float,
    ) -> OpenAlgoHttpResponse:
        """POST one JSON document without exposing provider/network exceptions."""

        connection_type = (
            http.client.HTTPSConnection if self._scheme == "https" else http.client.HTTPConnection
        )
        connection = connection_type(
            self._hostname,
            self._port,
            timeout=connect_timeout_seconds,
        )
        encoded = dumps(payload, separators=(",", ":")).encode("utf-8")
        try:
            connection.request(
                "POST",
                path,
                body=encoded,
                headers={"Content-Type": "application/json", "Accept": "application/json"},
            )
            response = connection.getresponse()
            if connection.sock is not None:
                connection.sock.settimeout(request_timeout_seconds)
            body = response.read()
            return OpenAlgoHttpResponse(
                status_code=response.status,
                body=body,
                content_type=response.getheader("Content-Type"),
            )
        except (TimeoutError, socket.timeout):
            raise OpenAlgoTransportUnavailable("OpenAlgo request timed out") from None
        except (OSError, ssl.SSLError, http.client.HTTPException):
            raise OpenAlgoTransportUnavailable("OpenAlgo request failed") from None
        finally:
            connection.close()
