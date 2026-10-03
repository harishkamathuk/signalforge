from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from signalforge.cli import replay_command
from signalforge.config.identity import ConfigIdentity, identify_config
from signalforge.config.strategy_registry import (
    StrategyRegistration,
    StrategyRegistry,
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
    StrategyDecision,
)


@dataclass(frozen=True, slots=True)
class _NoopDecision:
    instrument_id: InstrumentId
    interval: CandleInterval
    qualified: bool = False
    actionable: bool = False
    reasons: tuple[str, ...] = ("test_noop",)


class _NoopConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    marker: Decimal = Decimal("1")

    def identify(self) -> ConfigIdentity:
        return identify_config(
            {
                "strategy_id": "test_noop_strategy",
                "strategy_version": "1.0.0",
                "marker": self.marker,
            }
        )


class _NoopStrategy:
    @property
    def identity(self) -> StrategyIdentity:
        return StrategyIdentity("test_noop_strategy", "1.0.0")

    def __init__(self, config: _NoopConfig) -> None:
        self.config = config

    @property
    def config_identity(self) -> ConfigIdentity:
        return self.config.identify()

    @property
    def indicator_requirements(self) -> IndicatorRequirements:
        return IndicatorRequirements.of(RsiRequirement(14))

    def evaluate_completed_candle(
        self,
        context: CompletedCandleStrategyContext,
    ) -> _NoopDecision:
        return _NoopDecision(context.candle.instrument_id, context.candle.interval)

    def arm_intent(
        self,
        candle: CompletedCandle,
        decision: StrategyDecision,
    ) -> ArmIntent:
        raise AssertionError("test no-op strategy never arms")

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
        raise AssertionError("test no-op strategy never opens")


def _factory(parameters: Mapping[str, object]) -> _NoopStrategy:
    return _NoopStrategy(_NoopConfig.model_validate(dict(parameters)))


def _write(path: Path, payload: object) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_third_strategy_extends_through_registration_without_engine_changes(
    tmp_path: Path,
) -> None:
    registry = StrategyRegistry(
        (StrategyRegistration("test_noop_strategy", "1.0.0", _factory),)
    )
    config = _write(
        tmp_path / "config.json",
        {
            "instrument_id": "NSE:TEST",
            "quantity": 1,
            "engine_calculation_version": "engine-v1",
            "tick_rules": [
                {"tick_size": "0.05", "effective_from": "2026-01-01"}
            ],
            "strategy": {
                "id": "test_noop_strategy",
                "version": "1.0.0",
                "parameters": {},
            },
        },
    )
    events = _write(
        tmp_path / "events.json",
        [
            {
                "exchange_timestamp": "2026-10-03T10:00:00+05:30",
                "received_timestamp": "2026-10-03T10:00:00.001+05:30",
                "price": "100",
                "quantity": 1,
                "source": "sf066",
                "source_event_id": "e1",
            },
            {
                "exchange_timestamp": "2026-10-03T10:05:00+05:30",
                "received_timestamp": "2026-10-03T10:05:00.001+05:30",
                "price": "101",
                "quantity": 1,
                "source": "sf066",
                "source_event_id": "e2",
            },
        ],
    )

    summary = replay_command(config, events, registry=registry)

    assert summary["evaluations"] == 1
    assert summary["signals"] == 0
    assert summary["decision_counts"] == {"test_noop": 1}
