"""Deterministic single-instrument backtest application over the canonical replay runtime."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from signalforge.config.identity import ConfigIdentity
from signalforge.config.strategy_registry import DEFAULT_STRATEGY_REGISTRY, StrategyRegistry
from signalforge.domain.execution import Fill
from signalforge.domain.exits import Exit, ExitReason
from signalforge.domain.ids import ExitId, FillId, InstrumentId, RunId, SignalId, TradeId, deterministic_id
from signalforge.domain.market import MarketEvent
from signalforge.domain.money import Price, Quantity
from signalforge.domain.provenance import RunIdentity, StrategyIdentity
from signalforge.domain.time import to_utc
from signalforge.domain.trades import Trade, TradeState
from signalforge.research.contracts import ExperimentDefinition
from signalforge.runtime.eligibility import MarketDataFeedState
from signalforge.runtime.indicators import IndicatorContinuity
from signalforge.runtime.position_manager import PositionOpenRejection
from signalforge.runtime.replay import InMemoryReplaySource, ReplaySourceIdentity
from signalforge.runtime.replay_clock import ReplayClockStep, ReplaySessionClock
from signalforge.runtime.replay_runtime import ReplayRuntime
from signalforge.runtime.strategy import StrategyDecision, StrategyRuntimeFacts


@dataclass(frozen=True, slots=True)
class BacktestTradeResult:
    """One deterministic logical trade projected from canonical runtime facts."""

    trade_id: TradeId
    entry_fill_id: FillId
    signal_id: SignalId
    instrument_id: InstrumentId
    entry_price: Price
    stop_price: Price
    raw_target_price: Price
    tradable_target_price: Price
    risk_per_share: Price
    quantity: Quantity
    opened_at: datetime
    state: TradeState
    exit_id: ExitId | None
    exit_reason: ExitReason | None
    exit_price: Price | None
    exited_at: datetime | None
    realised_pnl: Decimal | None
    realised_r: Decimal | None

    @classmethod
    def from_runtime(cls, trade: Trade, exit_fact: Exit | None) -> BacktestTradeResult:
        """Copy immutable research economics from one observed runtime trade state."""

        if exit_fact is None:
            if trade.state is not TradeState.OPEN:
                raise ValueError("Closed backtest trade requires Exit evidence")
            return cls(
                trade_id=trade.trade_id,
                entry_fill_id=trade.entry_fill_id,
                signal_id=trade.signal_id,
                instrument_id=trade.instrument_id,
                entry_price=trade.entry_price,
                stop_price=trade.stop_price,
                raw_target_price=trade.raw_target_price,
                tradable_target_price=trade.tradable_target_price,
                risk_per_share=trade.risk_per_share,
                quantity=trade.quantity,
                opened_at=trade.opened_at,
                state=trade.state,
                exit_id=None,
                exit_reason=None,
                exit_price=None,
                exited_at=None,
                realised_pnl=None,
                realised_r=None,
            )

        if trade.state is not TradeState.CLOSED or trade.exit_id != exit_fact.exit_id:
            raise ValueError("Backtest Exit evidence contradicts Trade terminal state")
        return cls(
            trade_id=trade.trade_id,
            entry_fill_id=trade.entry_fill_id,
            signal_id=trade.signal_id,
            instrument_id=trade.instrument_id,
            entry_price=trade.entry_price,
            stop_price=trade.stop_price,
            raw_target_price=trade.raw_target_price,
            tradable_target_price=trade.tradable_target_price,
            risk_per_share=trade.risk_per_share,
            quantity=trade.quantity,
            opened_at=trade.opened_at,
            state=trade.state,
            exit_id=exit_fact.exit_id,
            exit_reason=exit_fact.reason,
            exit_price=exit_fact.fill_price,
            exited_at=exit_fact.exited_at,
            realised_pnl=exit_fact.realised_pnl,
            realised_r=exit_fact.realised_r,
        )


@dataclass(frozen=True, slots=True)
class BacktestEntryRejection:
    """One explicit filled entry that canonical position mechanics rejected."""

    fill_id: FillId
    instrument_id: InstrumentId
    fill_price: Price
    filled_at: datetime
    reason: PositionOpenRejection


@dataclass(frozen=True, slots=True)
class BacktestRunResult:
    """Deterministic result of one independent instrument backtest."""

    run: RunIdentity
    source: ReplaySourceIdentity
    strategy: StrategyIdentity
    config: ConfigIdentity
    instrument_id: InstrumentId
    events: int
    evaluations: int
    qualified: int
    actionable: int
    signals: int
    trades: int
    exits: int
    open_rejections: tuple[BacktestEntryRejection, ...]
    decision_counts: tuple[tuple[str, int], ...]
    final_lifecycle_state: str
    trade_results: tuple[BacktestTradeResult, ...]


class BacktestRunner:
    """Run one experiment instrument through the existing deterministic replay engine."""

    def __init__(self, *, registry: StrategyRegistry = DEFAULT_STRATEGY_REGISTRY) -> None:
        self._registry = registry

    def run(
        self,
        *,
        experiment: ExperimentDefinition,
        instrument_id: InstrumentId,
        events: Iterable[MarketEvent],
    ) -> BacktestRunResult:
        """Run one instrument after validating experiment/source provenance."""

        if instrument_id not in experiment.universe.instruments:
            raise ValueError("Backtest instrument is not in the experiment universe")

        execution = next(
            (item for item in experiment.execution if item.instrument_id == instrument_id),
            None,
        )
        source_definition = next(
            (item for item in experiment.dataset.sources if item.instrument_id == instrument_id),
            None,
        )
        if execution is None or source_definition is None:
            raise ValueError("Experiment is missing instrument execution or dataset provenance")

        strategy = self._registry.resolve(experiment.strategy_selection)
        if (
            strategy.identity != experiment.strategy_identity
            or strategy.config_identity != experiment.config_identity
        ):
            raise ValueError("Resolved strategy contradicts experiment provenance")

        event_tuple = tuple(events)
        self._validate_events(experiment, instrument_id, event_tuple)
        source = InMemoryReplaySource(instrument_id=instrument_id, events=event_tuple)
        if source.identity.source_id != source_definition.source_id:
            raise ValueError("Historical market events contradict experiment dataset source_id")

        run_id = deterministic_id(
            RunId,
            strategy.config_identity.config_hash,
            source.identity.source_id,
            experiment.engine_calculation_version,
        )
        run = RunIdentity(
            run_id=run_id,
            strategy=strategy.identity,
            config_id=strategy.config_identity.config_id,
            config_hash=strategy.config_identity.config_hash,
            engine_calculation_version=experiment.engine_calculation_version,
        )

        completed_count = 0

        def context_factory(_candle: object) -> StrategyRuntimeFacts:
            nonlocal completed_count
            completed_count += 1
            return StrategyRuntimeFacts(
                completed_regular_session_candles=completed_count,
                continuity=IndicatorContinuity.HEALTHY,
                feed_state=MarketDataFeedState.HEALTHY,
            )

        runtime = ReplayRuntime(
            source=source,
            run=run,
            tick_schedule=execution.tick_schedule,
            quantity=execution.quantity,
            strategy=strategy,
            evaluation_context_factory=context_factory,
        )
        steps = ReplaySessionClock(runtime=runtime).run_all()
        return self._project_result(
            runtime=runtime,
            steps=steps,
            config=strategy.config_identity,
        )

    @staticmethod
    def _validate_events(
        experiment: ExperimentDefinition,
        instrument_id: InstrumentId,
        events: tuple[MarketEvent, ...],
    ) -> None:
        start_at = experiment.dataset.start_at
        end_at = experiment.dataset.end_at
        for event in events:
            if event.instrument_id != instrument_id:
                raise ValueError("Backtest market event instrument does not match request")
            event_at = to_utc(event.exchange_timestamp)
            if event_at < start_at or event_at > end_at:
                raise ValueError("Backtest market event falls outside experiment dataset range")

    @staticmethod
    def _project_result(
        *,
        runtime: ReplayRuntime,
        steps: tuple[ReplayClockStep, ...],
        config: ConfigIdentity,
    ) -> BacktestRunResult:
        evaluations: list[StrategyDecision] = []
        trades: dict[TradeId, BacktestTradeResult] = {}
        rejections: dict[FillId, BacktestEntryRejection] = {}

        for step in steps:
            runtime_step = step.runtime_step
            if runtime_step.evaluation is not None:
                evaluations.append(runtime_step.evaluation)

            lifecycle = runtime_step.lifecycle
            open_result = lifecycle.open_result
            execution = lifecycle.execution
            if open_result is None or execution is None:
                continue

            if open_result.rejection is not None:
                fill = execution.fill
                rejections.setdefault(
                    fill.fill_id,
                    _rejection(fill, open_result.rejection),
                )
                continue

            trade = open_result.trade
            if trade is None:
                raise RuntimeError("Opened lifecycle result is missing Trade")
            trades[trade.trade_id] = BacktestTradeResult.from_runtime(
                trade,
                lifecycle.exit,
            )

        reason_counts: Counter[str] = Counter()
        for evaluation in evaluations:
            reason_counts.update(evaluation.reasons)

        transitions = runtime.lifecycle.audit_transitions
        signal_count = sum(
            transition.entity_type.value == "armed_setup" and transition.from_state == "none"
            for transition in transitions
        )
        trade_count = sum(
            transition.entity_type.value == "trade" and transition.from_state == "none"
            for transition in transitions
        )
        exit_count = sum(
            transition.entity_type.value == "trade" and transition.to_state == "closed"
            for transition in transitions
        )
        return BacktestRunResult(
            run=runtime.run,
            source=runtime.source.identity,
            strategy=runtime.strategy.identity,
            config=config,
            instrument_id=runtime.instrument_id,
            events=runtime.source.identity.event_count,
            evaluations=len(evaluations),
            qualified=sum(evaluation.qualified for evaluation in evaluations),
            actionable=sum(evaluation.actionable for evaluation in evaluations),
            signals=signal_count,
            trades=trade_count,
            exits=exit_count,
            open_rejections=tuple(
                rejections[key] for key in sorted(rejections, key=str)
            ),
            decision_counts=tuple(sorted(reason_counts.items())),
            final_lifecycle_state=runtime.lifecycle.state.value,
            trade_results=tuple(trades[key] for key in sorted(trades, key=str)),
        )


def _rejection(fill: Fill, reason: PositionOpenRejection) -> BacktestEntryRejection:
    return BacktestEntryRejection(
        fill_id=fill.fill_id,
        instrument_id=fill.instrument_id,
        fill_price=fill.fill_price,
        filled_at=fill.filled_at,
        reason=reason,
    )
