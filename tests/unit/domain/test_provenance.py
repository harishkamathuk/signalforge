"""Tests for immutable SignalForge provenance models."""

from dataclasses import FrozenInstanceError

import pytest

from signalforge.domain.ids import ConfigId, RunId
from signalforge.domain.provenance import RunIdentity, StrategyIdentity


def test_strategy_identity_rejects_blank_fields() -> None:
    with pytest.raises(ValueError):
        StrategyIdentity(strategy_id="", strategy_version="1.0.0")

    with pytest.raises(ValueError):
        StrategyIdentity(strategy_id="intraday_momentum_v1", strategy_version=" ")


def test_run_identity_is_immutable() -> None:
    identity = RunIdentity(
        run_id=RunId("run-001"),
        strategy=StrategyIdentity("intraday_momentum_v1", "1.0.0"),
        config_id=ConfigId("baseline"),
        config_hash="a" * 64,
        engine_calculation_version="calc-v1",
    )

    with pytest.raises(FrozenInstanceError):
        identity.config_hash = "b" * 64  # type: ignore[misc]


def test_run_identity_rejects_blank_provenance_fields() -> None:
    strategy = StrategyIdentity("intraday_momentum_v1", "1.0.0")

    with pytest.raises(ValueError):
        RunIdentity(
            run_id=RunId("run-001"),
            strategy=strategy,
            config_id=ConfigId("baseline"),
            config_hash=" ",
            engine_calculation_version="calc-v1",
        )

    with pytest.raises(ValueError):
        RunIdentity(
            run_id=RunId("run-001"),
            strategy=strategy,
            config_id=ConfigId("baseline"),
            config_hash="a" * 64,
            engine_calculation_version=" ",
        )


def test_run_identity_preserves_exact_provenance() -> None:
    identity = RunIdentity(
        run_id=RunId("run-20260830-001"),
        strategy=StrategyIdentity("intraday_momentum_v1", "1.0.0"),
        config_id=ConfigId("config-baseline"),
        config_hash="0123456789abcdef" * 4,
        engine_calculation_version="indicator-spec-v1",
    )

    assert identity.strategy.strategy_id == "intraday_momentum_v1"
    assert identity.strategy.strategy_version == "1.0.0"
    assert identity.config_id == ConfigId("config-baseline")
    assert identity.config_hash == "0123456789abcdef" * 4
    assert identity.engine_calculation_version == "indicator-spec-v1"
