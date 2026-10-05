"""Typed, secret-safe OpenAlgo adapter configuration."""

from __future__ import annotations

from collections.abc import Mapping
from ipaddress import ip_address
from os import environ
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator


class OpenAlgoConfig(BaseModel):
    """Immutable configuration for the OpenAlgo REST adapter boundary."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    host: str
    api_key: SecretStr = Field(repr=False)
    connect_timeout_seconds: float = Field(default=5.0, gt=0, le=60)
    request_timeout_seconds: float = Field(default=10.0, gt=0, le=120)

    @field_validator("host")
    @classmethod
    def validate_host(cls, value: str) -> str:
        """Validate and canonicalize the OpenAlgo service root URL."""

        candidate = value.strip()
        try:
            parsed = urlsplit(candidate)
            port = parsed.port
        except ValueError as exc:
            raise ValueError("OpenAlgo host contains an invalid port") from exc
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("OpenAlgo host must be an absolute HTTP(S) URL")
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("OpenAlgo host must not contain embedded credentials")
        if parsed.query or parsed.fragment:
            raise ValueError("OpenAlgo host must not contain query or fragment components")
        if parsed.path not in {"", "/"}:
            raise ValueError("OpenAlgo host must identify the service root without a path")
        if port is not None and not 1 <= port <= 65535:
            raise ValueError("OpenAlgo host contains an invalid port")
        if parsed.scheme == "http" and not _is_loopback_hostname(parsed.hostname):
            raise ValueError("Remote OpenAlgo hosts must use HTTPS")
        return candidate.rstrip("/")

    @field_validator("api_key", mode="before")
    @classmethod
    def validate_api_key(cls, value: object) -> object:
        """Reject blank OpenAlgo API keys before SecretStr wraps the value."""

        if not isinstance(value, str) or not value.strip():
            raise ValueError("OpenAlgo API key must not be blank")
        return value.strip()

    @classmethod
    def from_environment(
        cls,
        values: Mapping[str, str] | None = None,
    ) -> OpenAlgoConfig:
        """Build configuration from externally supplied environment-style values."""

        source = environ if values is None else values
        payload: dict[str, object] = {
            "host": source.get("OPENALGO_HOST", ""),
            "api_key": source.get("OPENALGO_API_KEY", ""),
        }
        if "OPENALGO_CONNECT_TIMEOUT_SECONDS" in source:
            payload["connect_timeout_seconds"] = source["OPENALGO_CONNECT_TIMEOUT_SECONDS"]
        if "OPENALGO_REQUEST_TIMEOUT_SECONDS" in source:
            payload["request_timeout_seconds"] = source["OPENALGO_REQUEST_TIMEOUT_SECONDS"]
        return cls.model_validate(payload)


def _is_loopback_hostname(hostname: str) -> bool:
    """Return whether a host is safely local for plaintext HTTP development use."""

    normalized = hostname.rstrip(".").lower()
    if normalized == "localhost":
        return True
    try:
        return ip_address(normalized).is_loopback
    except ValueError:
        return False
