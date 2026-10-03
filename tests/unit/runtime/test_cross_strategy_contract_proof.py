from __future__ import annotations

import inspect

from signalforge.config.identity import ConfigStatus
from signalforge.config.strategy_registry import (
    DEFAULT_STRATEGY_REGISTRY,
    StrategySelection,
)
from signalforge.domain.ids import RunId, deterministic_id
from signalforge.runtime import (
    execution,
    lifecycle,
    position_manager,
    replay_runtime,
    signal_lifecycle,
)
from signalforge.runtime.indicators import V1_INDICATOR_REQUIREMENTS


def _resolve(strategy_id: str):
    return DEFAULT_STRATEGY_REGISTRY.resolve(
        StrategySelection(strategy_id, "1.0.0", {})
    )


def test_real_strategies_share_registry_and_keep_frozen_identity() -> None:
    v1 = _resolve("intraday_momentum_v1")
    reference = _resolve("rsi_mean_reversion_v1")

    assert DEFAULT_STRATEGY_REGISTRY.registrations == (
        ("intraday_momentum_v1", "1.0.0"),
        ("rsi_mean_reversion_v1", "1.0.0"),
    )
    assert v1.config_identity.config_hash == (
        "fd6ec6027dcd2d661d60c3ccfa4e7de3873b2400c8ad2e0ca1323f358b967956"
    )
    assert reference.config_identity.config_hash == (
        "c5e0abf5b3fa55744278038b4f5f34d2b9164052821181f48345d05d226fd02f"
    )
    assert v1.config_identity.status is ConfigStatus.ACCEPTED
    assert reference.config_identity.status is ConfigStatus.EXPERIMENTAL
    assert v1.indicator_requirements == V1_INDICATOR_REQUIREMENTS
    assert reference.indicator_requirements.keys == ("rsi:14",)


def test_repeated_resolution_and_run_identity_are_deterministic() -> None:
    for strategy_id in ("intraday_momentum_v1", "rsi_mean_reversion_v1"):
        first = _resolve(strategy_id)
        second = _resolve(strategy_id)
        assert first.identity == second.identity
        assert first.config_identity == second.config_identity
        first_run = deterministic_id(
            RunId,
            first.config_identity.config_hash,
            "sf066-source",
            "engine-v1",
        )
        second_run = deterministic_id(
            RunId,
            second.config_identity.config_hash,
            "sf066-source",
            "engine-v1",
        )
        assert first_run == second_run


def test_shared_runtime_contains_no_real_strategy_dispatch() -> None:
    forbidden = (
        "intraday_momentum_v1",
        "rsi_mean_reversion_v1",
        "IntradayMomentumV1Strategy",
        "RsiMeanReversionV1Strategy",
    )
    for module in (
        replay_runtime,
        lifecycle,
        signal_lifecycle,
        position_manager,
        execution,
    ):
        source = inspect.getsource(module)
        for token in forbidden:
            assert token not in source
