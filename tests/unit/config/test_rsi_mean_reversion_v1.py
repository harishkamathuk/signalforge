from decimal import Decimal

import pytest
from pydantic import ValidationError

from signalforge.config.identity import ConfigStatus
from signalforge.config.rsi_mean_reversion_v1 import RsiMeanReversionV1Config
from signalforge.domain.provenance import StrategyIdentity


def test_reference_config_identity_and_status_are_deterministic() -> None:
    first = RsiMeanReversionV1Config()
    second = RsiMeanReversionV1Config()

    assert first.strategy_identity == StrategyIdentity("rsi_mean_reversion_v1", "1.0.0")
    assert first.semantic_mapping() == second.semantic_mapping()
    assert first.identify() == second.identify()
    assert first.identify().status is ConfigStatus.EXPERIMENTAL


def test_reference_config_is_frozen_and_forbids_extra_fields() -> None:
    config = RsiMeanReversionV1Config()

    with pytest.raises(ValidationError):
        config.rsi_threshold = Decimal("29")

    with pytest.raises(ValidationError):
        RsiMeanReversionV1Config.model_validate({"unknown": 1})


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("timeframe_minutes", 10),
        ("rsi_period", 10),
        ("rsi_threshold", "29"),
        ("rsi_strictly_below", False),
        ("target_r_multiple", "2"),
        ("validity_candles", 2),
    ),
)
def test_reference_config_rejects_semantic_drift(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        RsiMeanReversionV1Config.model_validate({field: value})


def test_reference_semantic_mapping_is_exact_fixture() -> None:
    assert RsiMeanReversionV1Config().semantic_mapping() == {
        "strategy_id": "rsi_mean_reversion_v1",
        "strategy_version": "1.0.0",
        "timeframe_minutes": 5,
        "rsi_period": 14,
        "rsi_threshold": Decimal("30"),
        "rsi_strictly_below": True,
        "target_r_multiple": Decimal("1.0"),
        "validity_candles": 1,
    }
