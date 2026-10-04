"""File-backed research experiment execution and deterministic JSON projection."""

from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from signalforge.config.strategy_registry import (
    DEFAULT_STRATEGY_REGISTRY,
    StrategyRegistry,
    normalize_strategy_selection,
)
from signalforge.domain.ids import InstrumentId
from signalforge.domain.instruments import TickSizeRule, TickSizeSchedule
from signalforge.domain.market import MarketEvent
from signalforge.domain.money import Price, Quantity
from signalforge.research.analytics import ResearchAnalytics
from signalforge.research.backtest import (
    BacktestEntryRejection,
    BacktestRunResult,
    BacktestTradeResult,
)
from signalforge.research.contracts import (
    DatasetDefinition,
    DatasetSourceDefinition,
    ExperimentDefinition,
    InstrumentExecutionDefinition,
    UniverseDefinition,
)
from signalforge.research.orchestration import (
    ExperimentResult,
    ResearchOrchestrator,
)
from signalforge.runtime.replay import InMemoryReplaySource, ReplaySource


class ResearchTickRuleConfig(BaseModel):
    """One effective-dated tick rule declared by a research experiment file."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tick_size: Decimal = Field(gt=0)
    effective_from: date
    effective_to: date | None = None


class ResearchInstrumentConfig(BaseModel):
    """One explicitly configured research instrument and its historical source."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    instrument_id: str = Field(min_length=1)
    input_file: Path
    quantity: int = Field(gt=0)
    tick_rules: tuple[ResearchTickRuleConfig, ...] = Field(min_length=1)


class ResearchExperimentFileConfig(BaseModel):
    """Strict external configuration for one reproducible research experiment."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    strategy: dict[str, object]
    engine_calculation_version: str = Field(min_length=1)
    start_at: datetime
    end_at: datetime
    instruments: tuple[ResearchInstrumentConfig, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_unique_instruments(self) -> ResearchExperimentFileConfig:
        """Reject duplicate instrument declarations before any source is read."""

        instrument_ids = tuple(item.instrument_id for item in self.instruments)
        if len(set(instrument_ids)) != len(instrument_ids):
            raise ValueError("Research experiment instruments must be unique")
        return self


class ResearchEventInput(BaseModel):
    """Strict external event representation used by JSON historical sources."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    exchange_timestamp: datetime
    received_timestamp: datetime
    price: Decimal = Field(gt=0)
    quantity: int = Field(gt=0)
    source: str = Field(min_length=1)
    source_event_id: str | None = None


def research_run_command(
    experiment_path: Path,
    *,
    registry: StrategyRegistry = DEFAULT_STRATEGY_REGISTRY,
) -> dict[str, object]:
    """Load, validate, run and serialize one explicit historical research experiment."""

    config = ResearchExperimentFileConfig.model_validate(_read_json(experiment_path))

    selection = normalize_strategy_selection(config.strategy)
    # Resolve typed strategy configuration before any historical source is read.
    registry.resolve(selection)

    universe = UniverseDefinition(
        tuple(InstrumentId(item.instrument_id) for item in config.instruments)
    )
    execution = tuple(_execution_definition(item) for item in config.instruments)

    sources: dict[InstrumentId, ReplaySource] = {}
    source_definitions: list[DatasetSourceDefinition] = []
    for item in config.instruments:
        instrument_id = InstrumentId(item.instrument_id)
        source = _load_source(
            instrument_id=instrument_id,
            path=_resolve_input_path(experiment_path, item.input_file),
        )
        sources[instrument_id] = source
        source_definitions.append(
            DatasetSourceDefinition(
                instrument_id=instrument_id,
                source_id=source.identity.source_id,
            )
        )

    dataset = DatasetDefinition(
        sources=tuple(source_definitions),
        start_at=config.start_at,
        end_at=config.end_at,
    )
    experiment = ExperimentDefinition.create(
        strategy_selection=selection,
        universe=universe,
        dataset=dataset,
        engine_calculation_version=config.engine_calculation_version,
        execution=execution,
        registry=registry,
    )
    result = ResearchOrchestrator(registry=registry).run(
        experiment=experiment,
        sources=sources,
    )
    return _serialize_result(experiment=experiment, result=result)


def _read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _resolve_input_path(experiment_path: Path, input_file: Path) -> Path:
    if input_file.is_absolute():
        return input_file
    return experiment_path.parent / input_file


def _execution_definition(
    item: ResearchInstrumentConfig,
) -> InstrumentExecutionDefinition:
    instrument_id = InstrumentId(item.instrument_id)
    return InstrumentExecutionDefinition(
        instrument_id=instrument_id,
        quantity=Quantity(item.quantity),
        tick_schedule=TickSizeSchedule(
            instrument_id=instrument_id,
            rules=tuple(
                TickSizeRule(
                    tick_size=Price(rule.tick_size),
                    effective_from=rule.effective_from,
                    effective_to=rule.effective_to,
                )
                for rule in item.tick_rules
            ),
        ),
    )


def _load_source(
    *,
    instrument_id: InstrumentId,
    path: Path,
) -> InMemoryReplaySource:
    raw_events = _read_json(path)
    if not isinstance(raw_events, list):
        raise ValueError(f"Research input {path} must be a JSON array")
    parsed = tuple(ResearchEventInput.model_validate(item) for item in raw_events)
    events = tuple(
        MarketEvent(
            instrument_id=instrument_id,
            exchange_timestamp=item.exchange_timestamp,
            received_timestamp=item.received_timestamp,
            price=Price(item.price),
            quantity=item.quantity,
            source=item.source,
            source_event_id=item.source_event_id,
        )
        for item in parsed
    )
    return InMemoryReplaySource(instrument_id=instrument_id, events=events)


def _serialize_result(
    *,
    experiment: ExperimentDefinition,
    result: ExperimentResult,
) -> dict[str, object]:
    return {
        "schema_version": "research-result-v1",
        "experiment": {
            "experiment_id": str(experiment.experiment_id),
            "universe_id": str(experiment.universe.universe_id),
            "dataset_id": str(experiment.dataset.dataset_id),
            "strategy_id": experiment.strategy_identity.strategy_id,
            "strategy_version": experiment.strategy_identity.strategy_version,
            "config_hash": experiment.config_identity.config_hash,
            "engine_calculation_version": experiment.engine_calculation_version,
            "start_at": experiment.dataset.start_at.isoformat(),
            "end_at": experiment.dataset.end_at.isoformat(),
        },
        "instrument_results": [
            _serialize_instrument_result(item) for item in result.instrument_results
        ],
        "trade_dataset": [_serialize_trade(item) for item in result.trade_dataset],
        "analytics": _serialize_analytics(result.analytics),
        "per_instrument": [
            {
                "instrument_id": str(item.instrument_id),
                "analytics": _serialize_analytics(item.analytics),
            }
            for item in result.per_instrument
        ],
    }


def _serialize_instrument_result(result: BacktestRunResult) -> dict[str, object]:
    return {
        "instrument_id": str(result.instrument_id),
        "backtest_run_id": str(result.backtest_run_id),
        "runtime_run_id": str(result.run.run_id),
        "source_id": result.source.source_id,
        "events": result.events,
        "evaluations": result.evaluations,
        "qualified": result.qualified,
        "actionable": result.actionable,
        "signals": result.signals,
        "trades": result.trades,
        "exits": result.exits,
        "open_rejections": [
            _serialize_rejection(item) for item in result.open_rejections
        ],
        "decision_counts": dict(result.decision_counts),
        "final_lifecycle_state": result.final_lifecycle_state,
    }


def _serialize_trade(trade: BacktestTradeResult) -> dict[str, object]:
    return {
        "experiment_id": str(trade.experiment_id),
        "backtest_run_id": str(trade.backtest_run_id),
        "backtest_trade_id": str(trade.backtest_trade_id),
        "trade_id": str(trade.trade_id),
        "entry_fill_id": str(trade.entry_fill_id),
        "signal_id": str(trade.signal_id),
        "instrument_id": str(trade.instrument_id),
        "entry_price": _decimal_string(trade.entry_price.value),
        "stop_price": _decimal_string(trade.stop_price.value),
        "raw_target_price": _decimal_string(trade.raw_target_price.value),
        "tradable_target_price": _decimal_string(trade.tradable_target_price.value),
        "risk_per_share": _decimal_string(trade.risk_per_share.value),
        "quantity": trade.quantity.value,
        "opened_at": trade.opened_at.isoformat(),
        "state": trade.state.value,
        "exit_id": None if trade.exit_id is None else str(trade.exit_id),
        "exit_reason": None if trade.exit_reason is None else trade.exit_reason.value,
        "exit_price": (
            None
            if trade.exit_price is None
            else _decimal_string(trade.exit_price.value)
        ),
        "exited_at": None if trade.exited_at is None else trade.exited_at.isoformat(),
        "realised_pnl": _decimal_or_none(trade.realised_pnl),
        "realised_r": _decimal_or_none(trade.realised_r),
    }


def _serialize_rejection(rejection: BacktestEntryRejection) -> dict[str, object]:
    return {
        "experiment_id": str(rejection.experiment_id),
        "backtest_run_id": str(rejection.backtest_run_id),
        "fill_id": str(rejection.fill_id),
        "instrument_id": str(rejection.instrument_id),
        "fill_price": _decimal_string(rejection.fill_price.value),
        "filled_at": rejection.filled_at.isoformat(),
        "reason": rejection.reason.value,
    }


def _serialize_analytics(analytics: ResearchAnalytics) -> dict[str, object]:
    return {
        "economics_basis": analytics.economics_basis,
        "trade_count": analytics.trade_count,
        "realised_trade_count": analytics.realised_trade_count,
        "open_trade_count": analytics.open_trade_count,
        "wins": analytics.wins,
        "losses": analytics.losses,
        "breakeven": analytics.breakeven,
        "win_rate": _decimal_or_none(analytics.win_rate),
        "expectancy_r": _decimal_or_none(analytics.expectancy_r),
        "profit_factor": _decimal_or_none(analytics.profit_factor),
        "gross_profit": _decimal_string(analytics.gross_profit),
        "gross_loss": _decimal_string(analytics.gross_loss),
        "gross_pnl": _decimal_string(analytics.gross_pnl),
        "max_drawdown_r": _decimal_string(analytics.max_drawdown_r),
        "exit_reason_counts": dict(analytics.exit_reason_counts),
    }


def _decimal_or_none(value: Decimal | None) -> str | None:
    return None if value is None else _decimal_string(value)


def _decimal_string(value: Decimal) -> str:
    """Serialize a finite Decimal by numeric value rather than incidental scale."""

    if not value.is_finite():
        raise ValueError("Research output Decimal values must be finite")
    normalized = value.normalize()
    if normalized == 0:
        return "0"
    return format(normalized, "f")
