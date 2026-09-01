"""Canonical, representation-independent encoding for deterministic identities."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal


def canonical_timestamp(value: datetime) -> str:
    """Encode an aware instant in UTC without representation-dependent offset data."""

    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("identity timestamps must be timezone-aware")
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def canonical_decimal(value: Decimal) -> str:
    """Encode a finite Decimal without insignificant trailing zeros or rounding."""

    if not value.is_finite():
        raise ValueError("identity Decimals must be finite")
    if value.is_zero():
        return "0"
    encoded = format(value, "f")
    if "." in encoded:
        encoded = encoded.rstrip("0").rstrip(".")
    return encoded