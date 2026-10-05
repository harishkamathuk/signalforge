"""Operational configuration for the OpenAlgo live market-data adapter."""

from __future__ import annotations

from collections.abc import Mapping
from ipaddress import ip_address
from os import environ
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator


class OpenAlgoMarketDataConfig(BaseModel):
    """Immutable live WebSocket/feed configuration."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    ws_url: str
    stale_after_seconds: float = Field(default=15.0, gt=0, le=300)
    reconnect_attempts: int = Field(default=3, ge=0, le=20)
    reconnect_delay_seconds: float = Field(default=1.0, ge=0, le=60)
    connect_timeout_seconds: float = Field(default=5.0, gt=0, le=60)
    receive_timeout_seconds: float = Field(default=5.0, gt=0, le=60)

    @field_validator("ws_url")
    @classmethod
    def validate_ws_url(cls, value: str) -> str:
        candidate = value.strip()
        try:
            parsed = urlsplit(candidate)
            port = parsed.port
        except ValueError as exc:
            raise ValueError("OpenAlgo WebSocket URL contains an invalid port") from exc
        if parsed.scheme not in {"ws", "wss"} or not parsed.hostname:
            raise ValueError("OpenAlgo WebSocket URL must be absolute ws:// or wss://")
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("OpenAlgo WebSocket URL must not contain embedded credentials")
        if parsed.query or parsed.fragment:
            raise ValueError("OpenAlgo WebSocket URL must not contain query or fragment")
        if port is not None and not 1 <= port <= 65535:
            raise ValueError("OpenAlgo WebSocket URL contains an invalid port")
        if parsed.scheme == "ws" and not _is_loopback(parsed.hostname):
            raise ValueError("Remote OpenAlgo WebSocket endpoints must use WSS")
        return candidate

    @classmethod
    def from_environment(
        cls,
        values: Mapping[str, str] | None = None,
    ) -> OpenAlgoMarketDataConfig:
        source = environ if values is None else values
        payload: dict[str, object] = {"ws_url": source.get("OPENALGO_WS_URL", "")}
        mapping = {
            "OPENALGO_STALE_AFTER_SECONDS": "stale_after_seconds",
            "OPENALGO_RECONNECT_ATTEMPTS": "reconnect_attempts",
            "OPENALGO_RECONNECT_DELAY_SECONDS": "reconnect_delay_seconds",
            "OPENALGO_WS_CONNECT_TIMEOUT_SECONDS": "connect_timeout_seconds",
            "OPENALGO_WS_RECEIVE_TIMEOUT_SECONDS": "receive_timeout_seconds",
        }
        for env_name, field_name in mapping.items():
            if env_name in source:
                payload[field_name] = source[env_name]
        return cls.model_validate(payload)


def _is_loopback(hostname: str) -> bool:
    normalized = hostname.rstrip(".").lower()
    if normalized == "localhost":
        return True
    try:
        return ip_address(normalized).is_loopback
    except ValueError:
        return False
