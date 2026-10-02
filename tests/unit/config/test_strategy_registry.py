from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

import pytest
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from signalforge.config.identity import ConfigIdentity, identify_config
from signalforge.config.strategy_registry import (
    DEFAULT_STRATEGY_REGISTRY,
    StrategyParameterValidationError,
    StrategyRegistration,
    StrategyRegistry,
    StrategyResolutionError,
    StrategySelection,
    UnknownStrategyError,
    UnsupportedStrategyVersionError,
    normalize_strategy_selection,
)
from signalforge.domain.execution import Fill
from signalforge.domain.ids import InstrumentId, RunId, deterministic_id
from signalforge.domain.indicators import IndicatorRequirements, RsiRequirement
from signalforge.domain.market import CompletedCandle, MarketEvent
from signalforge.domain.provenance import StrategyIdentity
from signalforge.domain.signals import Signal
from signalforge.domain.time import CandleInterval
from signalforge.runtime.strategy import (
    ArmedEventAction,
    ArmedEventDecision,
    ArmedSetupView,
    ArmIntent,
    CompletedCandleStrategyContext,
    PositionEconomics,
    StrategyDecision,
)


@dataclass(frozen=True, slots=True)
class _Decision:
    instrument_id: InstrumentId
    interval: CandleInterval
    qualified: bool = False
    actionable: bool = False
    reasons: tuple[str, ...] = ("test_only",)


class _TestConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    threshold: Decimal = Field(default=Decimal("50"))

    def identify(self) -> ConfigIdentity:
        return identify_config(
            {
                "strategy_id": "test_only_strategy",
                "strategy_version": "1.0.0",
                "threshold": self.threshold,
            }
        )


class _TestStrategy:
    def __init__(self, config: _TestConfig, *, identity: StrategyIdentity | None = None) -> None:
        self.config = config
        self._identity = identity or StrategyIdentity("test_only_strategy", "1.0.0")

    @property
    def identity(self) -> StrategyIdentity:
        return self._identity

    @property
    def config_identity(self) -> ConfigIdentity:
        return self.config.identify()

    @property
    def indicator_requirements(self) -> IndicatorRequirements:
        return IndicatorRequirements.of(RsiRequirement(14))

    def evaluate_completed_candle(
        self,
        context: CompletedCandleStrategyContext,
    ) -> _Decision:
        return _Decision(context.candle.instrument_id, context.candle.interval)

    def arm_intent(
        self,
        candle: CompletedCandle,
        decision: StrategyDecision,
    ) -> ArmIntent:
        raise AssertionError("test-only strategy never arms")

    def evaluate_armed_market_event(
        self,
        signal: Signal,
        setup: ArmedSetupView,
        event: MarketEvent,
    ) -> ArmedEventDecision:
        return ArmedEventDecision(ArmedEventAction.NO_ACTION)

    def evaluate_armed_completed_candle(
        self,
        signal: Signal,
        setup: ArmedSetupView,
        candle: CompletedCandle,
    ) -> ArmedEventDecision:
        return ArmedEventDecision(ArmedEventAction.NO_ACTION)

    def evaluate_armed_time(
        self,
        signal: Signal,
        setup: ArmedSetupView,
        at: datetime,
    ) -> ArmedEventDecision:
        return ArmedEventDecision(ArmedEventAction.NO_ACTION)

    def post_fill_economics(
        self,
        fill: Fill,
        setup: ArmedSetupView,
    ) -> PositionEconomics:
        raise AssertionError("test-only strategy never opens a position")


def _test_factory(parameters: Mapping[str, object]) -> _TestStrategy:
    return _TestStrategy(_TestConfig.model_validate(dict(parameters)))


def test_default_registry_contains_both_real_strategies() -> None:
    assert DEFAULT_STRATEGY_REGISTRY.registrations == (
        ("intraday_momentum_v1", "1.0.0"),
        ("rsi_mean_reversion_v1", "1.0.0"),
    )


def test_known_strategy_resolves_and_preserves_v1_identity() -> None:
    strategy = DEFAULT_STRATEGY_REGISTRY.resolve(
        StrategySelection("intraday_momentum_v1", "1.0.0", {})
    )

    assert strategy.identity == StrategyIdentity("intraday_momentum_v1", "1.0.0")
    assert strategy.config_identity.config_hash == (
        "fd6ec6027dcd2d661d60c3ccfa4e7de3873b2400c8ad2e0ca1323f358b967956"
    )


def test_unknown_strategy_and_unsupported_version_are_distinct() -> None:
    with pytest.raises(UnknownStrategyError, match="Unknown strategy: missing"):
        DEFAULT_STRATEGY_REGISTRY.resolve(StrategySelection("missing", "1.0.0", {}))

    with pytest.raises(
        UnsupportedStrategyVersionError,
        match="Unsupported version 2.0.0",
    ):
        DEFAULT_STRATEGY_REGISTRY.resolve(
            StrategySelection("intraday_momentum_v1", "2.0.0", {})
        )


def test_invalid_and_extra_v1_parameters_fail_typed_validation() -> None:
    with pytest.raises(StrategyParameterValidationError) as invalid:
        DEFAULT_STRATEGY_REGISTRY.resolve(
            StrategySelection(
                "intraday_momentum_v1",
                "1.0.0",
                {"rsi_min": "not-a-decimal"},
            )
        )
    assert isinstance(invalid.value.__cause__, ValidationError)

    with pytest.raises(StrategyParameterValidationError) as extra:
        DEFAULT_STRATEGY_REGISTRY.resolve(
            StrategySelection(
                "intraday_momentum_v1",
                "1.0.0",
                {"unknown_parameter": 123},
            )
        )
    assert isinstance(extra.value.__cause__, ValidationError)


def test_duplicate_registration_fails_instead_of_overwriting() -> None:
    registration = StrategyRegistration(
        "test_only_strategy",
        "1.0.0",
        _test_factory,
    )

    with pytest.raises(ValueError, match="Duplicate strategy registration"):
        StrategyRegistry((registration, registration))


def test_constructed_strategy_identity_must_match_registration() -> None:
    def mismatched_factory(parameters: Mapping[str, object]) -> _TestStrategy:
        config = _TestConfig.model_validate(dict(parameters))
        return _TestStrategy(
            config,
            identity=StrategyIdentity("other_strategy", "9.9.9"),
        )

    registry = StrategyRegistry(
        (
            StrategyRegistration(
                "test_only_strategy",
                "1.0.0",
                mismatched_factory,
            ),
        )
    )

    with pytest.raises(StrategyResolutionError, match="contradicts constructed strategy"):
        registry.resolve(StrategySelection("test_only_strategy", "1.0.0", {}))


def test_explicit_envelope_and_legacy_v1_defaults_are_equivalent() -> None:
    legacy = normalize_strategy_selection({})
    explicit = normalize_strategy_selection(
        {
            "id": "intraday_momentum_v1",
            "version": "1.0.0",
            "parameters": {},
        }
    )

    legacy_strategy = DEFAULT_STRATEGY_REGISTRY.resolve(legacy)
    explicit_strategy = DEFAULT_STRATEGY_REGISTRY.resolve(explicit)

    assert legacy_strategy.identity == explicit_strategy.identity
    assert legacy_strategy.config_identity == explicit_strategy.config_identity
    assert legacy_strategy.indicator_requirements == explicit_strategy.indicator_requirements


def test_explicit_parameter_key_order_preserves_config_and_run_identity() -> None:
    left = normalize_strategy_selection(
        {
            "id": "intraday_momentum_v1",
            "version": "1.0.0",
            "parameters": {"rsi_max": "64", "rsi_min": "59"},
        }
    )
    right = normalize_strategy_selection(
        {
            "version": "1.0.0",
            "parameters": {"rsi_min": "59", "rsi_max": "64"},
            "id": "intraday_momentum_v1",
        }
    )
    left_strategy = DEFAULT_STRATEGY_REGISTRY.resolve(left)
    right_strategy = DEFAULT_STRATEGY_REGISTRY.resolve(right)

    assert left_strategy.identity == right_strategy.identity
    assert left_strategy.config_identity == right_strategy.config_identity

    left_run = deterministic_id(
        RunId,
        left_strategy.config_identity.config_hash,
        "source-fixture-v1",
        "engine-v1",
    )
    right_run = deterministic_id(
        RunId,
        right_strategy.config_identity.config_hash,
        "source-fixture-v1",
        "engine-v1",
    )
    assert left_run == right_run


def test_any_envelope_key_activates_strict_envelope_validation() -> None:
    with pytest.raises(ValidationError):
        normalize_strategy_selection(
            {
                "id": "intraday_momentum_v1",
                "version": "1.0.0",
                "parameters": {},
                "rsi_min": 58,
            }
        )

    with pytest.raises(ValidationError):
        normalize_strategy_selection({"id": "intraday_momentum_v1"})


@pytest.mark.parametrize("invalid", (None, "v1", [], 1))
def test_non_mapping_strategy_input_is_rejected_by_replay_model(invalid: object) -> None:
    from signalforge.cli import ReplayCommandConfig

    with pytest.raises(ValidationError):
        ReplayCommandConfig.model_validate(
            {
                "instrument_id": "NSE:RELIANCE",
                "quantity": 1,
                "engine_calculation_version": "engine-v1",
                "tick_rules": [
                    {"tick_size": "0.05", "effective_from": "2026-01-01"}
                ],
                "strategy": invalid,
            }
        )


def test_reference_strategy_resolves_through_production_registry() -> None:
    strategy = DEFAULT_STRATEGY_REGISTRY.resolve(
        StrategySelection("rsi_mean_reversion_v1", "1.0.0", {})
    )

    assert strategy.identity == StrategyIdentity("rsi_mean_reversion_v1", "1.0.0")
    assert strategy.indicator_requirements == IndicatorRequirements.of(RsiRequirement(14))


def test_reference_strategy_wrong_version_and_parameters_fail() -> None:
    with pytest.raises(
        UnsupportedStrategyVersionError,
        match="Unsupported version 2.0.0",
    ):
        DEFAULT_STRATEGY_REGISTRY.resolve(
            StrategySelection("rsi_mean_reversion_v1", "2.0.0", {})
        )

    with pytest.raises(StrategyParameterValidationError):
        DEFAULT_STRATEGY_REGISTRY.resolve(
            StrategySelection(
                "rsi_mean_reversion_v1",
                "1.0.0",
                {"rsi_threshold": "29"},
            )
        )
