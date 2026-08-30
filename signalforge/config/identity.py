"""Canonical SignalForge configuration identity and hashing."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from hashlib import sha256

from signalforge.domain.ids import ConfigId


class ConfigStatus(StrEnum):
    """Lifecycle states currently supported by SignalForge configuration governance."""

    EXPERIMENTAL = "experimental"
    ACCEPTED = "accepted"


@dataclass(frozen=True, slots=True)
class ConfigIdentity:
    """Immutable identity and governance status for one normalized configuration."""

    config_id: ConfigId
    config_hash: str
    status: ConfigStatus

    def __post_init__(self) -> None:
        if self.config_id.value != self.config_hash:
            raise ValueError("Config ID must equal the canonical config hash")
        if len(self.config_hash) != 64:
            raise ValueError("Config hash must be a SHA-256 hex digest")
        try:
            int(self.config_hash, 16)
        except ValueError as exc:
            raise ValueError("Config hash must be a SHA-256 hex digest") from exc


def canonical_config_json(config: Mapping[str, object]) -> str:
    """Serialize normalized configuration data into deterministic canonical JSON."""

    normalized = _normalize_value(config)
    return json.dumps(
        normalized,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def config_hash(config: Mapping[str, object]) -> str:
    """Return the SHA-256 digest of the canonical configuration representation."""

    canonical = canonical_config_json(config).encode("utf-8")
    return sha256(canonical).hexdigest()


def identify_config(
    config: Mapping[str, object],
    *,
    status: ConfigStatus = ConfigStatus.EXPERIMENTAL,
) -> ConfigIdentity:
    """Build immutable config identity from normalized semantic content."""

    digest = config_hash(config)
    return ConfigIdentity(config_id=ConfigId(digest), config_hash=digest, status=status)


def _normalize_value(value: object) -> object:
    """Convert supported values to an unambiguous type-tagged canonical structure."""

    if value is None:
        return ["null"]
    if isinstance(value, bool):
        return ["bool", value]
    if isinstance(value, int):
        return ["int", str(value)]
    if isinstance(value, str):
        return ["str", value]

    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("Configuration Decimal values must be finite")
        return ["decimal", _canonical_decimal(value)]

    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("Configuration float values must be finite")
        return ["decimal", _canonical_decimal(Decimal(str(value)))]

    if isinstance(value, Mapping):
        items: list[tuple[str, object]] = []
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("Configuration mapping keys must be strings")
            items.append((key, _normalize_value(item)))
        items.sort(key=lambda item: item[0])
        return ["map", [[key, item] for key, item in items]]

    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return ["list", [_normalize_value(item) for item in value]]

    raise TypeError(f"Unsupported configuration value type: {type(value).__name__}")


def _canonical_decimal(value: Decimal) -> str:
    normalized = value.normalize()
    if normalized == 0:
        return "0"
    return format(normalized, "f")
