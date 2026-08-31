"""Deterministic single-security in-memory replay runtime composition."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from signalforge.config.strategy_v1 import StrategyV1EvaluationConfig
from signalforge.domain.indicators import IndicatorSnapshot
from signalforge.domain.instruments import TickSizeSchedule
from signalforge.domain.market import CompletedCandle
from signalforge.domain.money import Quantity
from signalforge.domain.provenance import RunIdentity
from signalforge.runtime.candles import CandleEngine
from signalforge.runtime.indicators import IndicatorEngine
from signalforge.runtime.lifecycle import LifecycleCoordinator, LifecycleSnapshot
from signalforge.runtime.replay import ReplayInput, ReplaySource
from signalforge.runtime.strategy_evaluator import (
    StrategyEvaluationContext,
    StrategyEvaluator,
    StrategyEvaluatorResult,
)

EvaluationContextFactory = Callable[[CompletedCandle], StrategyEvaluationContext]


@dataclass(frozen=True, slots=True)
class ReplayRuntimeStep:
    """Observable output from processing one replay input."""

    replay_input: ReplayInput
    completed_candle: CompletedCandle | None
    indicator_snapshot: IndicatorSnapshot | None
    evaluation: StrategyEvaluatorResult | None
    lifecycle: LifecycleSnapshot


class ReplayRuntime:
    """Compose the existing single-security runtime for deterministic replay."""

    def __init__(
        self,
        *,
        source: ReplaySource,
        run: RunIdentity,
        tick_schedule: TickSizeSchedule,
        quantity: Quantity,
        strategy_config: StrategyV1EvaluationConfig,
        evaluation_context_factory: EvaluationContextFactory,
    ) -> None:
        instrument_id = source.identity.instrument_id
        if tick_schedule.instrument_id != instrument_id:
            raise ValueError("Replay source and tick schedule instruments must match")

        self.source = source
        self.run = run
        self.candle_engine = CandleEngine(instrument_id=instrument_id)
        self.indicator_engine = IndicatorEngine(
            instrument_id,
            run.engine_calculation_version,
        )
        self.strategy_evaluator = StrategyEvaluator(strategy_config)
        self.lifecycle = LifecycleCoordinator(
            run=run,
            tick_schedule=tick_schedule,
            quantity=quantity,
        )
        self._evaluation_context_factory = evaluation_context_factory

    @property
    def instrument_id(self):
        return self.source.identity.instrument_id

    def process_input(self, replay_input: ReplayInput) -> ReplayRuntimeStep:
        """Process one replay input without reading any future source input."""

        if replay_input.source_id != self.source.identity.source_id:
            raise ValueError("ReplayInput source identity does not match runtime source")
        event = replay_input.event
        if event.instrument_id != self.instrument_id:
            raise ValueError("ReplayInput instrument does not match runtime instrument")

        self.lifecycle.process_market_event(event)
        completed = self.candle_engine.process(event)
        if completed is None:
            return ReplayRuntimeStep(
                replay_input=replay_input,
                completed_candle=None,
                indicator_snapshot=None,
                evaluation=None,
                lifecycle=self.lifecycle.snapshot(),
            )

        self.lifecycle.process_completed_candle(completed)
        snapshot = self.indicator_engine.update(completed)
        context = self._evaluation_context_factory(completed)
        evaluation = self.strategy_evaluator.evaluate(completed, snapshot, context)
        lifecycle = self.lifecycle.process_evaluation(completed, evaluation)
        return ReplayRuntimeStep(
            replay_input=replay_input,
            completed_candle=completed,
            indicator_snapshot=snapshot,
            evaluation=evaluation,
            lifecycle=lifecycle,
        )

    def run_all(self) -> tuple[ReplayRuntimeStep, ...]:
        """Consume the configured replay source serially to exhaustion."""

        return tuple(self.process_input(replay_input) for replay_input in self.source)
