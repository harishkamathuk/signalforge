from datetime import time
from decimal import Decimal

import pytest
from pydantic import ValidationError

from signalforge.config.identity import ConfigStatus, identify_config
from signalforge.config.strategy_v1 import StrategyV1EvaluationConfig
from signalforge.domain.provenance import StrategyIdentity


def test_defaults_match_accepted_strategy_v1() -> None:
    config = StrategyV1EvaluationConfig()

    assert config.strategy_identity == StrategyIdentity("intraday_momentum_v1", "1.0.0")
    assert config.timeframe_minutes == 5
    assert config.setup_ema_period == 9
    assert (config.trend_fast_ema_period, config.trend_slow_ema_period) == (20, 50)
    assert config.rsi_period == 14
    assert (config.rsi_min, config.rsi_max) == (Decimal("58"), Decimal("65"))
    assert config.adx_period == 14
    assert config.adx_threshold == Decimal("22")
    assert (config.macd_fast_period, config.macd_slow_period, config.macd_signal_period) == (
        12,
        26,
        9,
    )
    assert config.minimum_warmup_candles == 250
    assert config.first_signal_time_ist == time(9, 20)
    assert config.last_signal_time_ist == time(15, 0)


def test_frozen_semantics_are_explicit_and_cannot_be_changed() -> None:
    config = StrategyV1EvaluationConfig()

    assert config.rsi_lower_inclusive is True
    assert config.rsi_upper_inclusive is True
    assert config.adx_strictly_greater is True
    assert config.trend_strictly_greater is True
    assert config.setup_strictly_greater is True
    assert config.macd_diagnostic_only is True

    for field in (
        "rsi_lower_inclusive",
        "rsi_upper_inclusive",
        "adx_strictly_greater",
        "trend_strictly_greater",
        "setup_strictly_greater",
        "macd_diagnostic_only",
    ):
        with pytest.raises(ValidationError):
            StrategyV1EvaluationConfig(**{field: False})


def test_unknown_fields_are_rejected_so_macd_cannot_become_gate() -> None:
    with pytest.raises(ValidationError):
        StrategyV1EvaluationConfig(macd_qualification_gate=True)  # type: ignore[call-arg]


def test_configuration_is_immutable() -> None:
    config = StrategyV1EvaluationConfig()

    with pytest.raises(ValidationError):
        config.adx_threshold = Decimal("23")


def test_relationship_validation() -> None:
    with pytest.raises(ValidationError, match="RSI minimum"):
        StrategyV1EvaluationConfig(rsi_min=Decimal("66"), rsi_max=Decimal("65"))
    with pytest.raises(ValidationError, match="first signal time"):
        StrategyV1EvaluationConfig(
            first_signal_time_ist=time(15, 5),
            last_signal_time_ist=time(15, 0),
        )
    with pytest.raises(ValidationError, match="trend fast EMA"):
        StrategyV1EvaluationConfig(trend_fast_ema_period=50, trend_slow_ema_period=20)
    with pytest.raises(ValidationError, match="MACD fast period"):
        StrategyV1EvaluationConfig(macd_fast_period=26, macd_slow_period=12)


def test_semantic_mapping_is_supported_by_canonical_hashing() -> None:
    config = StrategyV1EvaluationConfig()
    identity = config.identify()

    assert identity.status is ConfigStatus.ACCEPTED
    assert identity == identify_config(config.semantic_mapping(), status=ConfigStatus.ACCEPTED)
    assert identity.config_id.value == identity.config_hash
    assert len(identity.config_hash) == 64


def test_same_semantics_produce_stable_identity() -> None:
    left = StrategyV1EvaluationConfig()
    right = StrategyV1EvaluationConfig.model_validate(left.model_dump())

    assert left.semantic_mapping() == right.semantic_mapping()
    assert left.identify() == right.identify()


def test_parameter_change_changes_config_identity_without_changing_strategy_identity() -> None:
    accepted = StrategyV1EvaluationConfig()
    experimental = StrategyV1EvaluationConfig(adx_threshold=Decimal("23"))

    assert accepted.strategy_identity == experimental.strategy_identity
    assert accepted.identify().config_hash != experimental.identify().config_hash
    assert experimental.identify(status=ConfigStatus.EXPERIMENTAL).status is ConfigStatus.EXPERIMENTAL


def test_time_values_are_canonicalized_as_minute_strings() -> None:
    mapping = StrategyV1EvaluationConfig().semantic_mapping()

    assert mapping["first_signal_time_ist"] == "09:20"
    assert mapping["last_signal_time_ist"] == "15:00"
