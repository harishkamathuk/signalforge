from __future__ import annotations

from dataclasses import dataclass

import pytest

from signalforge.adapters.openalgo.config import OpenAlgoConfig
from signalforge.adapters.openalgo.health import OpenAlgoPreflightStatus, preflight
from signalforge.adapters.openalgo.transport import (
    OpenAlgoHttpResponse,
    OpenAlgoTransportUnavailable,
)


SECRET = "super-secret-openalgo-key"
CONFIG = OpenAlgoConfig(host="http://127.0.0.1:5000", api_key=SECRET)


@dataclass
class FakeTransport:
    response: OpenAlgoHttpResponse | None = None
    failure: Exception | None = None
    seen_payload: dict[str, object] | None = None

    def post_json(
        self,
        *,
        path: str,
        payload: dict[str, object],
        connect_timeout_seconds: float,
        request_timeout_seconds: float,
    ) -> OpenAlgoHttpResponse:
        assert path == "/api/v1/ping"
        assert connect_timeout_seconds == CONFIG.connect_timeout_seconds
        assert request_timeout_seconds == CONFIG.request_timeout_seconds
        self.seen_payload = payload
        if self.failure is not None:
            raise self.failure
        assert self.response is not None
        return self.response


def response(status: int, body: bytes, content_type: str | None = "application/json") -> OpenAlgoHttpResponse:
    return OpenAlgoHttpResponse(status_code=status, body=body, content_type=content_type)


def test_ready_preflight_returns_only_signalforge_owned_result() -> None:
    transport = FakeTransport(
        response=response(200, b'{"status":"success","data":{"message":"pong","broker":"zerodha"}}')
    )

    result = preflight(CONFIG, transport=transport)

    assert result.status is OpenAlgoPreflightStatus.READY
    assert result.broker == "zerodha"
    assert result.detail is None
    assert transport.seen_payload == {"apikey": SECRET}
    assert SECRET not in repr(result)


def test_transport_failure_is_unreachable_and_secret_safe() -> None:
    result = preflight(
        CONFIG,
        transport=FakeTransport(failure=OpenAlgoTransportUnavailable("network down")),
    )

    assert result.status is OpenAlgoPreflightStatus.UNREACHABLE
    assert SECRET not in repr(result)
    assert SECRET not in (result.detail or "")


@pytest.mark.parametrize(
    "message",
    ["Invalid openalgo apikey", "Invalid API key"],
)
def test_invalid_api_key_is_classified_separately(message: str) -> None:
    result = preflight(
        CONFIG,
        transport=FakeTransport(
            response=response(403, ('{"status":"error","message":"' + message + '"}').encode())
        ),
    )

    assert result.status is OpenAlgoPreflightStatus.API_AUTH_FAILED


def test_other_ping_403_is_broker_session_unavailable() -> None:
    result = preflight(
        CONFIG,
        transport=FakeTransport(
            response=response(403, b'{"status":"error","message":"Broker session not available"}')
        ),
    )

    assert result.status is OpenAlgoPreflightStatus.BROKER_SESSION_UNAVAILABLE


@pytest.mark.parametrize(
    "provider_response",
    [
        response(200, b'{"status":"error","message":"broker error"}'),
        response(200, b'not-json'),
        response(200, b'[]'),
        response(200, b'{"status":"success","data":{}}'),
        response(500, b'{"status":"error","message":"internal"}'),
        response(200, b'{"status":"success","data":{"message":"pong","broker":"zerodha"}}', "text/html"),
    ],
)
def test_unexpected_provider_responses_fail_closed(provider_response: OpenAlgoHttpResponse) -> None:
    result = preflight(CONFIG, transport=FakeTransport(response=provider_response))

    assert result.status is OpenAlgoPreflightStatus.PROTOCOL_ERROR
    assert SECRET not in repr(result)
