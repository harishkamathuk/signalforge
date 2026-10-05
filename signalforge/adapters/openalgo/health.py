"""Read-only OpenAlgo startup preflight and provider-error classification."""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from signalforge.adapters.openalgo.config import OpenAlgoConfig
from signalforge.adapters.openalgo.transport import (
    OpenAlgoHttpResponse,
    OpenAlgoTransport,
    OpenAlgoTransportUnavailable,
    StdlibOpenAlgoTransport,
)


class OpenAlgoPreflightStatus(StrEnum):
    """SignalForge-owned startup states for the OpenAlgo boundary."""

    READY = "ready"
    UNREACHABLE = "unreachable"
    API_AUTH_FAILED = "api_auth_failed"
    BROKER_SESSION_UNAVAILABLE = "broker_session_unavailable"
    PROTOCOL_ERROR = "protocol_error"


@dataclass(frozen=True, slots=True)
class OpenAlgoPreflightResult:
    """Secret-free result returned by the OpenAlgo startup preflight."""

    status: OpenAlgoPreflightStatus
    broker: str | None = None
    detail: str | None = None


def preflight(
    config: OpenAlgoConfig,
    *,
    transport: OpenAlgoTransport | None = None,
) -> OpenAlgoPreflightResult:
    """Verify OpenAlgo API authentication and active broker-session availability."""

    selected_transport = transport or StdlibOpenAlgoTransport(config.host)
    try:
        response = selected_transport.post_json(
            path="/api/v1/ping",
            payload={"apikey": config.api_key.get_secret_value()},
            connect_timeout_seconds=config.connect_timeout_seconds,
            request_timeout_seconds=config.request_timeout_seconds,
        )
    except OpenAlgoTransportUnavailable:
        return OpenAlgoPreflightResult(
            status=OpenAlgoPreflightStatus.UNREACHABLE,
            detail="OpenAlgo service could not be reached safely",
        )
    return _classify_ping(response)


def _classify_ping(response: OpenAlgoHttpResponse) -> OpenAlgoPreflightResult:
    if (
        response.content_type is not None
        and "application/json" not in response.content_type.lower()
    ):
        return _protocol_error("OpenAlgo ping returned a non-JSON content type")

    payload = _decode_json_object(response.body)
    if payload is None:
        return _protocol_error("OpenAlgo ping returned malformed or non-object JSON")

    provider_message = _provider_message(payload)
    if response.status_code in {401, 403}:
        if _is_api_key_rejection(provider_message):
            return OpenAlgoPreflightResult(
                status=OpenAlgoPreflightStatus.API_AUTH_FAILED,
                detail="OpenAlgo API key was rejected",
            )
        if response.status_code == 403 and _is_broker_session_unavailable(provider_message):
            return OpenAlgoPreflightResult(
                status=OpenAlgoPreflightStatus.BROKER_SESSION_UNAVAILABLE,
                detail="OpenAlgo broker session is unavailable",
            )
        if response.status_code == 403:
            return _protocol_error("OpenAlgo ping returned an unclassified forbidden response")
        return OpenAlgoPreflightResult(
            status=OpenAlgoPreflightStatus.API_AUTH_FAILED,
            detail="OpenAlgo API authentication failed",
        )

    if response.status_code != 200:
        return _protocol_error("OpenAlgo ping returned an unexpected HTTP status")
    if payload.get("status") != "success":
        return _protocol_error("OpenAlgo ping returned an application-level error")

    data = payload.get("data")
    if not isinstance(data, dict):
        return _protocol_error("OpenAlgo ping success payload omitted data")
    if data.get("message") != "pong":
        return _protocol_error("OpenAlgo ping success payload omitted pong")
    broker = data.get("broker")
    if not isinstance(broker, str) or not broker.strip():
        return _protocol_error("OpenAlgo ping success payload omitted broker identity")

    return OpenAlgoPreflightResult(
        status=OpenAlgoPreflightStatus.READY,
        broker=broker.strip(),
    )


def _decode_json_object(body: bytes) -> dict[str, Any] | None:
    try:
        value = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _provider_message(payload: dict[str, Any]) -> str:
    for key in ("message", "error"):
        value = payload.get(key)
        if isinstance(value, str):
            return value.strip().lower()
    return ""


def _is_api_key_rejection(message: str) -> bool:
    return any(
        marker in message
        for marker in (
            "invalid openalgo apikey",
            "invalid openalgo api key",
            "invalid api key",
            "invalid apikey",
        )
    )


def _is_broker_session_unavailable(message: str) -> bool:
    return any(
        marker in message
        for marker in (
            "broker session",
            "broker not connected",
            "broker is not connected",
            "no active broker",
            "broker login",
            "broker token",
            "session expired",
            "session revoked",
        )
    )


def _protocol_error(detail: str) -> OpenAlgoPreflightResult:
    return OpenAlgoPreflightResult(
        status=OpenAlgoPreflightStatus.PROTOCOL_ERROR,
        detail=detail,
    )
