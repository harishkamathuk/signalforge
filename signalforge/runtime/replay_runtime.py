"""Deterministic single-security in-memory replay runtime composition."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from signalforge.domain.ids import InstrumentId
from signalforge.domain.indicators import IndicatorSnapshot
from signalforge.domain.instruments import TickSizeSchedule
from signalforge.domain.market import CompletedCandle
from signalforge.domain.money import Quantity
from signalforge.domain.provenance import RunIdentity
from signalforge.runtime.candles import CandleEngine
from signalforge.runtime.indicators import IndicatorEngine
from signalforge.runtime.lifecycle import LifecycleCoordinator, LifecycleSnapshot
from signalforge.runtime.replay import ReplayInput, ReplaySource
from signalforge.runtime.strategy import (
    CompletedCandleStrategyContext,
    Strategy,
    StrategyDecision,
    StrategyRuntimeFacts,
)

EvaluationContextFactory = Callable[[CompletedCandle], StrategyRuntimeFacts]


@dataclass(frozen=True, slots=True)
class ReplayRuntimeStep:
    """Observable output from processing one replay input."""

    replay_input: ReplayInput
    completed_candle: CompletedCandle | None
    indicator_snapshot: IndicatorSnapshot | None
    evaluation: StrategyDecision | None
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
        strategy: Strategy,
        evaluation_context_factory: EvaluationContextFactory,
        candle_engine: CandleEngine | None = None,
        indicator_engine: IndicatorEngine | None = None,
        lifecycle: LifecycleCoordinator | None = None,
    ) -> None:
        instrument_id = source.identity.instrument_id
        if tick_schedule.instrument_id != instrument_id:
            raise ValueError("Replay source and tick schedule instruments must match")

        self.source = source
        self.run = run
        self.candle_engine = candle_engine or CandleEngine(instrument_id=instrument_id)
        if self.candle_engine.instrument_id != instrument_id:
            raise ValueError("Recovered CandleEngine instrument must match replay source")
        if run.strategy != strategy.identity:
            raise ValueError("Run strategy identity must match configured strategy")
        if (
            run.config_id != strategy.config_identity.config_id
            or run.config_hash != strategy.config_identity.config_hash
        ):
            raise ValueError("Run config identity must match configured strategy")

        self.indicator_engine = indicator_engine or IndicatorEngine(
            instrument_id,
            run.engine_calculation_version,
            requirements=strategy.indicator_requirements,
        )
        indicator_state = self.indicator_engine.state
        if (
            indicator_state.instrument_id != instrument_id
            or indicator_state.calculation_version != run.engine_calculation_version
            or indicator_state.requirements != strategy.indicator_requirements
        ):
            raise ValueError("Recovered IndicatorEngine contradicts replay runtime")
        self.strategy = strategy
        self.lifecycle = lifecycle or LifecycleCoordinator(
            run=run,
            tick_schedule=tick_schedule,
            quantity=quantity,
            strategy=strategy,
        )
        if self.lifecycle.run != run or self.lifecycle.strategy.identity != strategy.identity:
            raise ValueError("Recovered lifecycle contradicts replay runtime")
        self._evaluation_context_factory = evaluation_context_factory

    @property
    def instrument_id(self) -> InstrumentId:
        return self.source.identity.instrument_id

    def process_time(self, at: datetime) -> LifecycleSnapshot:
        """Route one explicit replay-time boundary into the lifecycle."""

        return self.lifecycle.process_time(at)

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
        facts = self._evaluation_context_factory(completed)
        evaluation = self.strategy.evaluate_completed_candle(
            CompletedCandleStrategyContext(
                candle=completed,
                indicators=snapshot,
                completed_regular_session_candles=facts.completed_regular_session_candles,
                continuity=facts.continuity,
                feed_state=facts.feed_state,
            )
        )
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
