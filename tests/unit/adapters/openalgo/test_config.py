from __future__ import annotations

import pytest
from pydantic import ValidationError

from signalforge.adapters.openalgo.config import OpenAlgoConfig

SECRET = "super-secret-openalgo-key"


def test_valid_config_is_frozen_strict_and_secret_safe() -> None:
    config = OpenAlgoConfig(host="http://127.0.0.1:5000/", api_key=SECRET)

    assert config.host == "http://127.0.0.1:5000"
    assert config.api_key.get_secret_value() == SECRET
    assert SECRET not in repr(config)
    assert SECRET not in config.model_dump_json()

    with pytest.raises(ValidationError):
        OpenAlgoConfig.model_validate(
            {"host": "http://127.0.0.1:5000", "api_key": SECRET, "unsupported": True}
        )


def test_environment_construction_supports_timeouts() -> None:
    config = OpenAlgoConfig.from_environment(
        {
            "OPENALGO_HOST": "https://openalgo.example",
            "OPENALGO_API_KEY": SECRET,
            "OPENALGO_CONNECT_TIMEOUT_SECONDS": "2.5",
            "OPENALGO_REQUEST_TIMEOUT_SECONDS": "8",
        }
    )

    assert config.connect_timeout_seconds == 2.5
    assert config.request_timeout_seconds == 8.0


@pytest.mark.parametrize(
    "host",
    [
        "",
        "localhost:5000",
        "ftp://example.test",
        "http://user:pass@example.test",
        "http://example.test/api",
    ],
)
def test_invalid_hosts_are_rejected(host: str) -> None:
    with pytest.raises(ValidationError) as exc_info:
        OpenAlgoConfig(host=host, api_key=SECRET)

    assert SECRET not in str(exc_info.value)


@pytest.mark.parametrize("api_key", ["", "   "])
def test_blank_api_key_is_rejected(api_key: str) -> None:
    with pytest.raises(ValidationError) as exc_info:
        OpenAlgoConfig(host="http://127.0.0.1:5000", api_key=api_key)

    assert SECRET not in str(exc_info.value)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("connect_timeout_seconds", 0),
        ("connect_timeout_seconds", 61),
        ("request_timeout_seconds", 0),
        ("request_timeout_seconds", 121),
    ],
)
def test_invalid_timeouts_are_rejected(field: str, value: float) -> None:
    payload: dict[str, object] = {
        "host": "http://127.0.0.1:5000",
        "api_key": SECRET,
        field: value,
    }
    with pytest.raises(ValidationError):
        OpenAlgoConfig.model_validate(payload)
