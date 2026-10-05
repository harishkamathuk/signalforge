"""Typed, secret-safe OpenAlgo adapter configuration."""

from __future__ import annotations

from collections.abc import Mapping
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
        parsed = urlsplit(candidate)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("OpenAlgo host must be an absolute HTTP(S) URL")
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("OpenAlgo host must not contain embedded credentials")
        if parsed.query or parsed.fragment:
            raise ValueError("OpenAlgo host must not contain query or fragment components")
        if parsed.path not in {"", "/"}:
            raise ValueError("OpenAlgo host must identify the service root without a path")
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
