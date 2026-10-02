from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import BaseModel, ConfigDict, ValidationError

from signalforge.cli import main, replay_command
from signalforge.config.identity import ConfigIdentity, identify_config
from signalforge.config.strategy_registry import (
    StrategyParameterValidationError,
    StrategyRegistration,
    StrategyRegistry,
    UnknownStrategyError,
    UnsupportedStrategyVersionError,
)
from signalforge.domain.execution import Fill
from signalforge.domain.ids import InstrumentId
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
)


def _write(path: Path, payload: object) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _config_payload(strategy: object) -> dict[str, object]:
    return {
        "instrument_id": "NSE:RELIANCE",
        "quantity": 10,
        "engine_calculation_version": "engine-v1",
        "tick_rules": [
            {
                "tick_size": "0.10",
                "effective_from": "2026-01-01",
            }
        ],
        "strategy": strategy,
    }


def _config(tmp_path: Path, *, strategy: object | None = None) -> Path:
    return _write(
        tmp_path / "config.json",
        _config_payload({} if strategy is None else strategy),
    )


def _input(tmp_path: Path) -> Path:
    return _write(
        tmp_path / "events.json",
        [
            {
                "exchange_timestamp": "2026-08-31T10:00:00+05:30",
                "received_timestamp": "2026-08-31T10:00:00.001+05:30",
                "price": "100.00",
                "quantity": 1,
                "source": "fixture",
                "source_event_id": "e1",
            },
            {
                "exchange_timestamp": "2026-08-31T10:05:00+05:30",
                "received_timestamp": "2026-08-31T10:05:00.001+05:30",
                "price": "101.00",
                "quantity": 1,
                "source": "fixture",
                "source_event_id": "e2",
            },
        ],
    )


def test_replay_command_returns_deterministic_summary(tmp_path: Path) -> None:
    config = _config(tmp_path)
    input_path = _input(tmp_path)

    first = replay_command(config, input_path)
    second = replay_command(config, input_path)

    assert first == second
    assert first["instrument_id"] == "NSE:RELIANCE"
    assert first["events"] == 2
    assert first["evaluations"] == 1
    assert first["signals"] == 0
    assert first["trades"] == 0
    assert first["exits"] == 0
    assert first["final_lifecycle_state"] == "idle"


def test_explicit_v1_default_matches_legacy_replay(tmp_path: Path) -> None:
    input_path = _input(tmp_path)
    legacy = _write(tmp_path / "legacy.json", _config_payload({}))
    explicit = _write(
        tmp_path / "explicit.json",
        _config_payload(
            {
                "id": "intraday_momentum_v1",
                "version": "1.0.0",
                "parameters": {},
            }
        ),
    )

    assert replay_command(legacy, input_path) == replay_command(explicit, input_path)


def test_explicit_v1_custom_parameters_match_legacy_replay(tmp_path: Path) -> None:
    input_path = _input(tmp_path)
    parameters = {"rsi_min": "59", "rsi_max": "64"}
    legacy = _write(tmp_path / "legacy-custom.json", _config_payload(parameters))
    explicit = _write(
        tmp_path / "explicit-custom.json",
        _config_payload(
            {
                "id": "intraday_momentum_v1",
                "version": "1.0.0",
                "parameters": parameters,
            }
        ),
    )

    assert replay_command(legacy, input_path) == replay_command(explicit, input_path)


def test_main_prints_json_summary_and_returns_zero(tmp_path: Path, capsys) -> None:
    exit_code = main(
        [
            "replay",
            "--config",
            str(_config(tmp_path)),
            "--input",
            str(_input(tmp_path)),
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 0
    assert captured.err == ""
    assert payload["events"] == 2


def test_main_returns_nonzero_for_invalid_input(tmp_path: Path, capsys) -> None:
    invalid_input = _write(tmp_path / "events.json", {"not": "an array"})

    exit_code = main(
        [
            "replay",
            "--config",
            str(_config(tmp_path)),
            "--input",
            str(invalid_input),
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.out == ""
    assert "Replay input must be a JSON array" in captured.err


@pytest.mark.parametrize(
    ("strategy", "error_type"),
    (
        (
            {"id": "missing", "version": "1.0.0", "parameters": {}},
            UnknownStrategyError,
        ),
        (
            {
                "id": "intraday_momentum_v1",
                "version": "2.0.0",
                "parameters": {},
            },
            UnsupportedStrategyVersionError,
        ),
        (
            {
                "id": "intraday_momentum_v1",
                "version": "1.0.0",
                "parameters": {"rsi_min": "invalid"},
            },
            StrategyParameterValidationError,
        ),
        (
            {
                "id": "intraday_momentum_v1",
                "version": "1.0.0",
                "parameters": {"unknown_parameter": 1},
            },
            StrategyParameterValidationError,
        ),
    ),
)
def test_strategy_configuration_fails_before_market_input_is_read(
    tmp_path: Path,
    strategy: object,
    error_type: type[Exception],
) -> None:
    config = _write(tmp_path / "invalid-strategy.json", _config_payload(strategy))
    missing_input = tmp_path / "does-not-exist.json"

    with pytest.raises(error_type):
        replay_command(config, missing_input)


def test_ambiguous_explicit_strategy_shape_does_not_fall_back_to_v1(
    tmp_path: Path,
) -> None:
    config = _write(
        tmp_path / "ambiguous.json",
        _config_payload(
            {
                "id": "intraday_momentum_v1",
                "version": "1.0.0",
                "parameters": {},
                "rsi_min": 58,
            }
        ),
    )

    with pytest.raises(ValidationError):
        replay_command(config, tmp_path / "does-not-exist.json")


@dataclass(frozen=True, slots=True)
class _ReferenceDecision:
    instrument_id: InstrumentId
    interval: CandleInterval
    qualified: bool = False
    actionable: bool = False
    reasons: tuple[str, ...] = ("reference_test",)


class _ReferenceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    threshold: Decimal = Decimal("50")

    def identify(self) -> ConfigIdentity:
        return identify_config(
            {
                "strategy_id": "test_reference_strategy",
                "strategy_version": "1.0.0",
                "threshold": self.threshold,
            }
        )


class _ReferenceStrategy:
    def __init__(self, config: _ReferenceConfig) -> None:
        self.config = config

    @property
    def identity(self) -> StrategyIdentity:
        return StrategyIdentity("test_reference_strategy", "1.0.0")

    @property
    def config_identity(self) -> ConfigIdentity:
        return self.config.identify()

    @property
    def indicator_requirements(self) -> IndicatorRequirements:
        return IndicatorRequirements.of(RsiRequirement(14))

    def evaluate_completed_candle(
        self,
        context: CompletedCandleStrategyContext,
    ) -> _ReferenceDecision:
        return _ReferenceDecision(context.candle.instrument_id, context.candle.interval)

    def arm_intent(
        self,
        candle: CompletedCandle,
        decision: _ReferenceDecision,
    ) -> ArmIntent:
        raise AssertionError("reference strategy never arms")

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
        raise AssertionError("reference strategy never opens")


def _reference_factory(parameters: Mapping[str, object]) -> _ReferenceStrategy:
    return _ReferenceStrategy(_ReferenceConfig.model_validate(dict(parameters)))


def test_test_only_second_strategy_runs_without_replay_runtime_changes(
    tmp_path: Path,
) -> None:
    registry = StrategyRegistry(
        (
            StrategyRegistration(
                "test_reference_strategy",
                "1.0.0",
                _reference_factory,
            ),
        )
    )
    config = _write(
        tmp_path / "reference.json",
        _config_payload(
            {
                "id": "test_reference_strategy",
                "version": "1.0.0",
                "parameters": {"threshold": "55"},
            }
        ),
    )

    summary = replay_command(config, _input(tmp_path), registry=registry)

    assert summary["events"] == 2
    assert summary["evaluations"] == 1
    assert summary["signals"] == 0
    assert summary["trades"] == 0
    assert summary["decision_counts"] == {"reference_test": 1}
