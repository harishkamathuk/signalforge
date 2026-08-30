from __future__ import annotations

from dataclasses import FrozenInstanceError
from decimal import Decimal

import pytest

from signalforge.config.identity import (
    ConfigIdentity,
    ConfigStatus,
    canonical_config_json,
    config_hash,
    identify_config,
)
from signalforge.domain.ids import ConfigId


def test_semantically_identical_key_order_hashes_identically() -> None:
    left = {
        "strategy": "intraday_momentum_v1",
        "parameters": {"rsi_max": 65, "rsi_min": 58, "entry_offset": 0.001},
    }
    right = {
        "parameters": {"entry_offset": 0.001, "rsi_min": 58, "rsi_max": 65},
        "strategy": "intraday_momentum_v1",
    }

    assert canonical_config_json(left) == canonical_config_json(right)
    assert config_hash(left) == config_hash(right)


def test_equivalent_decimal_formatting_hashes_identically() -> None:
    left = {"entry_offset": Decimal("0.0010")}
    right = {"entry_offset": Decimal("0.001")}

    assert config_hash(left) == config_hash(right)


def test_float_and_equivalent_decimal_normalize_identically() -> None:
    left = {"reward_risk": 1.5}
    right = {"reward_risk": Decimal("1.50")}

    assert config_hash(left) == config_hash(right)


def test_material_parameter_change_changes_hash() -> None:
    baseline = {"adx_min": 22, "reward_risk": 1.5}
    changed = {"adx_min": 23, "reward_risk": 1.5}

    assert config_hash(baseline) != config_hash(changed)


def test_sequence_order_is_semantic() -> None:
    first = {"periods": [9, 20, 50]}
    second = {"periods": [50, 20, 9]}

    assert config_hash(first) != config_hash(second)


def test_identify_config_uses_hash_as_config_id() -> None:
    config = {"strategy": "intraday_momentum_v1", "version": "1.0.0"}

    identity = identify_config(config, status=ConfigStatus.ACCEPTED)

    assert identity.config_id.value == identity.config_hash
    assert identity.config_hash == config_hash(config)
    assert identity.status is ConfigStatus.ACCEPTED


def test_identify_config_defaults_to_experimental() -> None:
    identity = identify_config({"strategy": "candidate"})

    assert identity.status is ConfigStatus.EXPERIMENTAL


def test_config_identity_rejects_mismatched_id_and_hash() -> None:
    digest = "a" * 64

    with pytest.raises(ValueError, match="Config ID must equal"):
        ConfigIdentity(
            config_id=ConfigId("b" * 64),
            config_hash=digest,
            status=ConfigStatus.EXPERIMENTAL,
        )


def test_config_identity_is_immutable() -> None:
    identity = identify_config({"strategy": "candidate"})

    with pytest.raises(FrozenInstanceError):
        identity.status = ConfigStatus.ACCEPTED  # type: ignore[misc]


def test_non_string_mapping_key_is_rejected() -> None:
    with pytest.raises(TypeError, match="mapping keys must be strings"):
        config_hash({"parameters": {1: "invalid"}})  # type: ignore[dict-item]


def test_non_finite_numeric_values_are_rejected() -> None:
    with pytest.raises(ValueError, match="must be finite"):
        config_hash({"threshold": float("nan")})

    with pytest.raises(ValueError, match="must be finite"):
        config_hash({"threshold": Decimal("Infinity")})


def test_unsupported_values_are_rejected() -> None:
    with pytest.raises(TypeError, match="Unsupported configuration value type"):
        config_hash({"symbols": {"RELIANCE", "TCS"}})
