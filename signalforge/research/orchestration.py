"""Deterministic multi-instrument research orchestration."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from signalforge.config.strategy_registry import DEFAULT_STRATEGY_REGISTRY, StrategyRegistry
from signalforge.domain.ids import ExperimentId, InstrumentId
from signalforge.research.analytics import ResearchAnalytics, calculate_analytics
from signalforge.research.backtest import (
    BacktestRunner,
    BacktestRunResult,
    BacktestTradeResult,
)
from signalforge.research.contracts import ExperimentDefinition
from signalforge.runtime.replay import ReplaySource


class ResearchExperimentError(RuntimeError):
    """Raised when an experiment cannot produce a complete deterministic result."""


@dataclass(frozen=True, slots=True)
class InstrumentAnalytics:
    """Core descriptive metrics for one independently backtested instrument."""

    instrument_id: InstrumentId
    analytics: ResearchAnalytics


@dataclass(frozen=True, slots=True)
class ExperimentResult:
    """Complete deterministic result for one explicit-universe research experiment."""

    experiment_id: ExperimentId
    instrument_results: tuple[BacktestRunResult, ...]
    trade_dataset: tuple[BacktestTradeResult, ...]
    analytics: ResearchAnalytics
    per_instrument: tuple[InstrumentAnalytics, ...]


class ResearchOrchestrator:
    """Run each explicit-universe instrument independently and aggregate evidence."""

    def __init__(self, *, registry: StrategyRegistry = DEFAULT_STRATEGY_REGISTRY) -> None:
        self._runner = BacktestRunner(registry=registry)

    def run(
        self,
        *,
        experiment: ExperimentDefinition,
        sources: Mapping[InstrumentId, ReplaySource],
    ) -> ExperimentResult:
        """Validate all sources, execute independent backtests, and aggregate results."""

        self._validate_sources(experiment=experiment, sources=sources)

        instrument_results: list[BacktestRunResult] = []
        for instrument_id in experiment.universe.instruments:
            try:
                result = self._runner.run(
                    experiment=experiment,
                    instrument_id=instrument_id,
                    source=sources[instrument_id],
                )
            except Exception as exc:
                raise ResearchExperimentError(
                    f"Research experiment failed for instrument {instrument_id}"
                ) from exc
            instrument_results.append(result)

        ordered_results = tuple(instrument_results)
        trades = tuple(
            sorted(
                (
                    trade
                    for result in ordered_results
                    for trade in result.trade_results
                ),
                key=_dataset_order_key,
            )
        )
        per_instrument = tuple(
            InstrumentAnalytics(
                instrument_id=result.instrument_id,
                analytics=calculate_analytics(result.trade_results),
            )
            for result in ordered_results
        )
        return ExperimentResult(
            experiment_id=experiment.experiment_id,
            instrument_results=ordered_results,
            trade_dataset=trades,
            analytics=calculate_analytics(trades),
            per_instrument=per_instrument,
        )

    @staticmethod
    def _validate_sources(
        *,
        experiment: ExperimentDefinition,
        sources: Mapping[InstrumentId, ReplaySource],
    ) -> None:
        expected = set(experiment.universe.instruments)
        actual = set(sources)
        if actual != expected:
            missing = sorted(str(item) for item in expected - actual)
            extra = sorted(str(item) for item in actual - expected)
            raise ResearchExperimentError(
                "Research sources must exactly match experiment universe "
                f"(missing={missing}, extra={extra})"
            )

        definitions = {
            definition.instrument_id: definition
            for definition in experiment.dataset.sources
        }
        for instrument_id in experiment.universe.instruments:
            source = sources[instrument_id]
            if source.identity.instrument_id != instrument_id:
                raise ResearchExperimentError(
                    f"Replay source instrument mismatch for {instrument_id}"
                )
            expected_source_id = definitions[instrument_id].source_id
            if source.identity.source_id != expected_source_id:
                raise ResearchExperimentError(
                    f"Replay source identity mismatch for {instrument_id}"
                )


def _dataset_order_key(trade: BacktestTradeResult) -> tuple[object, str, str]:
    """Order research rows independently of source mapping/invocation order."""

    return (
        trade.opened_at,
        str(trade.instrument_id),
        str(trade.backtest_trade_id),
    )
