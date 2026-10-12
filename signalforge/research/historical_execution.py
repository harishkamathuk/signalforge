"""Deterministic historical bar execution under accepted ADR-011 semantics."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, replace
from datetime import datetime, time, timedelta
from decimal import Decimal
from enum import StrEnum

from signalforge.config.identity import config_hash
from signalforge.config.strategy_registry import (
    DEFAULT_STRATEGY_REGISTRY,
    StrategyRegistry,
    StrategySelection,
)
from signalforge.domain.armed import ArmedSetupState
from signalforge.domain.ids import RunId, deterministic_id
from signalforge.domain.instruments import TickSizeSchedule
from signalforge.domain.market import CandleQuality, CompletedCandle
from signalforge.domain.money import Price, ceil_to_tick, floor_to_tick
from signalforge.domain.provenance import RunIdentity
from signalforge.domain.signals import Signal
from signalforge.domain.time import IST, CandleInterval, to_ist, to_utc
from signalforge.research.historical_bars import (
    HistoricalBar,
    HistoricalBarDataset,
    HistoricalContinuityError,
    aggregate_one_minute_to_five_minute,
)
from signalforge.runtime.indicators import IndicatorContinuity, IndicatorEngine
from signalforge.runtime.strategy import (
    ArmedPolicyIntent,
    ArmedSetupView,
    CompletedCandleStrategyContext,
    PriceBarrierDirection,
    Strategy,
    StrategyDecision,
    StrategyEntryFillView,
)

_BPS = Decimal("10000")
_SESSION_OPEN = time(9, 15)
_SESSION_END = time(15, 30)
_FORCED_EXIT = time(15, 15)


class HistoricalOutcomeCertainty(StrEnum):
    DETERMINATE = "determinate"
    BOUNDED_AMBIGUOUS = "bounded_ambiguous"
    UNRESOLVED = "unresolved"


class HistoricalAmbiguityReason(StrEnum):
    ENTRY_VS_INVALIDATION = "entry_vs_invalidation"
    ENTRY_VS_EXPIRY = "entry_vs_expiry"
    ENTRY_VS_STRATEGY_CUTOFF = "entry_vs_strategy_cutoff"
    ENTRY_VS_SESSION_CUTOFF = "entry_vs_session_cutoff"
    ENTRY_VS_POST_FILL_STOP = "entry_vs_post_fill_stop"
    ENTRY_VS_POST_FILL_TARGET = "entry_vs_post_fill_target"
    STOP_VS_TARGET = "stop_vs_target"
    MISSING_EXECUTION_EVIDENCE = "missing_execution_evidence"
    UNSUPPORTED_STRATEGY_POLICY = "unsupported_strategy_policy"


class HistoricalFillTiming(StrEnum):
    BAR_OPEN_EXACT = "bar_open_exact"
    EXACT_BOUNDARY = "exact_boundary"
    INTRABAR_UNKNOWN = "intrabar_unknown"


class HistoricalTerminalState(StrEnum):
    EXPIRED = "expired"
    REJECTED = "rejected"
    CLOSED = "closed"
    OPEN_POSSIBLE = "open_possible"
    BLOCKED = "blocked"
    UNRESOLVED = "unresolved"


class HistoricalExitReason(StrEnum):
    STOP = "stop"
    TARGET = "target"
    FORCED_SESSION_EXIT = "forced_session_exit"


@dataclass(frozen=True, slots=True)
class HistoricalExecutionAssumptionProfile:
    """Known versioned slippage assumptions; never executable configuration."""

    profile_id: str
    version: str
    entry_slippage_bps: Decimal
    stop_slippage_bps: Decimal
    target_slippage_bps: Decimal
    forced_exit_slippage_bps: Decimal
    tick_rule_version: str

    def __post_init__(self) -> None:
        if not self.profile_id.strip() or not self.version.strip():
            raise ValueError("Execution assumption identity must not be empty")
        if not self.tick_rule_version.strip():
            raise ValueError("tick_rule_version must not be empty")
        for name in (
            "entry_slippage_bps",
            "stop_slippage_bps",
            "target_slippage_bps",
            "forced_exit_slippage_bps",
        ):
            value = getattr(self, name)
            if not isinstance(value, Decimal):
                raise TypeError(f"{name} must be a Decimal")
            if not value.is_finite() or value < 0:
                raise ValueError(f"{name} must be finite and non-negative")

    @classmethod
    def zero(cls) -> HistoricalExecutionAssumptionProfile:
        zero = Decimal("0")
        return cls(
            "historical-zero-slippage",
            "1",
            zero,
            zero,
            zero,
            zero,
            "nse-tick-v1",
        )

    @property
    def semantic_id(self) -> str:
        return config_hash(self.semantic_mapping())

    def semantic_mapping(self) -> dict[str, object]:
        return {
            "profile_id": self.profile_id,
            "version": self.version,
            "entry_slippage_bps": self.entry_slippage_bps,
            "stop_slippage_bps": self.stop_slippage_bps,
            "target_slippage_bps": self.target_slippage_bps,
            "forced_exit_slippage_bps": self.forced_exit_slippage_bps,
            "tick_rule_version": self.tick_rule_version,
        }


@dataclass(frozen=True, slots=True)
class HistoricalModeledFill:
    base_price: Price
    fill_price: Price
    bucket: CandleInterval
    timing: HistoricalFillTiming
    slippage_bps: Decimal


@dataclass(frozen=True, slots=True)
class HistoricalPossibleOutcome:
    terminal_state: HistoricalTerminalState
    exit_reason: HistoricalExitReason | None
    realised_r: Decimal | None


@dataclass(frozen=True, slots=True)
class HistoricalExecutionOutcome:
    opportunity_id: str
    signal_interval: CandleInterval
    certainty: HistoricalOutcomeCertainty
    terminal_state: HistoricalTerminalState
    decision_reasons: tuple[str, ...]
    entry_fill: HistoricalModeledFill | None = None
    exit_fill: HistoricalModeledFill | None = None
    exit_reason: HistoricalExitReason | None = None
    realised_r: Decimal | None = None
    ambiguity_reasons: tuple[HistoricalAmbiguityReason, ...] = ()
    possible_outcomes: tuple[HistoricalPossibleOutcome, ...] = ()
    affected_quality_buckets: tuple[CandleInterval, ...] = ()
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class HistoricalExecutionSummary:
    total_actionable_opportunities: int
    determinate_opportunities: int
    bounded_ambiguous_opportunities: int
    unresolved_opportunities: int
    determinate_coverage_rate: Decimal | None
    determinate_closed_trades: int
    determinate_subset_win_rate: Decimal | None
    determinate_subset_expectancy_r: Decimal | None
    determinate_subset_profit_factor_r: Decimal | None
    determinate_subset_max_drawdown_r: Decimal


@dataclass(frozen=True, slots=True)
class HistoricalExecutionRunResult:
    dataset_id: str
    strategy_id: str
    strategy_version: str
    config_hash: str
    engine_calculation_version: str
    execution_profile_semantic_id: str
    outcomes: tuple[HistoricalExecutionOutcome, ...]
    summary: HistoricalExecutionSummary
    terminated_early: bool


@dataclass(slots=True)
class _Active:
    opportunity_id: str
    signal: Signal
    view: ArmedSetupView
    policy: ArmedPolicyIntent
    reasons: tuple[str, ...]
    entry_fill: HistoricalModeledFill | None = None
    raw_target: Price | None = None
    tradable_target: Price | None = None

    @property
    def is_open(self) -> bool:
        return self.entry_fill is not None


class HistoricalBarExecutionRunner:
    """Single-security historical lifecycle using only canonical one-minute evidence."""

    def __init__(self, *, registry: StrategyRegistry = DEFAULT_STRATEGY_REGISTRY) -> None:
        self._registry = registry

    def run(
        self,
        dataset: HistoricalBarDataset,
        *,
        strategy_selection: StrategySelection,
        engine_calculation_version: str,
        tick_schedule: TickSizeSchedule,
        execution_profile: HistoricalExecutionAssumptionProfile,
    ) -> HistoricalExecutionRunResult:
        if tick_schedule.instrument_id != dataset.manifest.instrument_id:
            raise ValueError("TickSizeSchedule instrument must match historical dataset")
        strategy = self._registry.resolve(strategy_selection)
        run = RunIdentity(
            run_id=deterministic_id(
                RunId,
                str(dataset.dataset_id),
                strategy.config_identity.config_hash,
                engine_calculation_version,
                execution_profile.semantic_id,
            ),
            strategy=strategy.identity,
            config_id=strategy.config_identity.config_id,
            config_hash=strategy.config_identity.config_hash,
            engine_calculation_version=engine_calculation_version,
        )
        engine = IndicatorEngine(
            dataset.manifest.instrument_id,
            engine_calculation_version,
            requirements=strategy.indicator_requirements,
        )
        candles = aggregate_one_minute_to_five_minute(dataset)
        candle_by_end = {c.interval.end: c for c in candles}
        bar_by_start = {b.interval.start: b for b in dataset.bars}
        outcomes: list[HistoricalExecutionOutcome] = []
        active: _Active | None = None
        completed = 0

        for start in _expected_minute_starts(dataset):
            bar = bar_by_start.get(start)
            if bar is None:
                if active is not None:
                    outcomes.append(_missing(active, start))
                    return _result(
                        dataset,
                        strategy,
                        engine_calculation_version,
                        execution_profile,
                        outcomes,
                        True,
                    )
                candle = next(c for c in candles if c.interval.contains(start))
                engine.break_continuity()
                raise HistoricalContinuityError(candle)

            if active is not None:
                terminal = _process_bar(
                    active,
                    bar,
                    strategy,
                    tick_schedule,
                    execution_profile,
                )
                if terminal is not None:
                    outcomes.append(terminal)
                    active = None

            completed_candle = candle_by_end.get(bar.interval.end)
            if completed_candle is None:
                continue
            if completed_candle.quality is not CandleQuality.VALID:
                engine.break_continuity()
                raise HistoricalContinuityError(completed_candle)
            snapshot = engine.update(completed_candle)
            completed += 1
            decision: StrategyDecision = strategy.evaluate_completed_candle(
                CompletedCandleStrategyContext(
                    candle=completed_candle,
                    indicators=snapshot,
                    completed_regular_session_candles=completed,
                    continuity=IndicatorContinuity.HEALTHY,
                    feed_state=None,
                )
            )
            if not decision.actionable:
                continue
            if active is not None:
                outcomes.append(_blocked(dataset, strategy, decision))
                continue
            active = _arm(
                dataset,
                strategy,
                run,
                completed_candle,
                decision,
                tick_schedule,
            )

        if active is not None:
            outcomes.append(
                _unresolved(
                    active,
                    (HistoricalAmbiguityReason.UNSUPPORTED_STRATEGY_POLICY,),
                    "active lifecycle survived regular-session evidence",
                )
            )

        return _result(
            dataset,
            strategy,
            engine_calculation_version,
            execution_profile,
            outcomes,
            False,
        )


def _arm(
    dataset: HistoricalBarDataset,
    strategy: Strategy,
    run: RunIdentity,
    candle: CompletedCandle,
    decision: StrategyDecision,
    tick_schedule: TickSizeSchedule,
) -> _Active:
    if candle.close is None or candle.low is None:
        raise ValueError("Actionable candle requires close and low")
    intent = strategy.arm_intent(candle, decision)
    tick = tick_schedule.tick_size_on(to_ist(candle.interval.end).date())
    tradable_trigger = ceil_to_tick(intent.raw_trigger, tick)
    signal = Signal.create(
        instrument_id=candle.instrument_id,
        interval=candle.interval,
        signal_close=candle.close,
        signal_low=candle.low,
        run=run,
        created_at=candle.interval.end,
    )
    view = ArmedSetupView(
        signal.signal_id,
        intent.raw_trigger,
        tradable_trigger,
        intent.stop_price,
        candle.interval.end,
        intent.valid_until,
        ArmedSetupState.ARMED,
    )
    policy = strategy.armed_policy(signal, view)
    invalidation = policy.pre_entry_invalidation
    if invalidation is not None and (
        invalidation.direction is not PriceBarrierDirection.AT_OR_BELOW
        or invalidation.price.value >= tradable_trigger.value
    ):
        raise ValueError("Unsupported/conflicting pre-entry invalidation policy")
    return _Active(
        config_hash(
            {
                "dataset_id": str(dataset.dataset_id),
                "signal_id": str(signal.signal_id),
            }
        ),
        signal,
        view,
        policy,
        decision.reasons,
    )


def _process_bar(
    active: _Active,
    bar: HistoricalBar,
    strategy: Strategy,
    ticks: TickSizeSchedule,
    profile: HistoricalExecutionAssumptionProfile,
) -> HistoricalExecutionOutcome | None:
    return (
        _process_open_bar(active, bar, ticks, profile)
        if active.is_open
        else _process_armed_bar(active, bar, strategy, ticks, profile)
    )


def _process_armed_bar(
    active: _Active,
    bar: HistoricalBar,
    strategy: Strategy,
    ticks: TickSizeSchedule,
    profile: HistoricalExecutionAssumptionProfile,
) -> HistoricalExecutionOutcome | None:
    start, end = bar.interval.start, bar.interval.end
    forced = _forced_exit_at(start)
    cutoff = active.policy.strategy_entry_cutoff_at

    if start >= forced:
        return _expired(active, "forced_session_entry_expiry")
    if cutoff is not None and start >= cutoff:
        return _expired(active, "entry_cutoff_reached")
    if start >= active.view.valid_until:
        return _expired(active, "validity_window_end")

    trigger = bar.high.value >= active.view.tradable_trigger.value
    invalidation = active.policy.pre_entry_invalidation
    invalidated = invalidation is not None and bar.low.value <= invalidation.price.value

    for boundary, reason in (
        (cutoff, HistoricalAmbiguityReason.ENTRY_VS_STRATEGY_CUTOFF),
        (active.view.valid_until, HistoricalAmbiguityReason.ENTRY_VS_EXPIRY),
        (forced, HistoricalAmbiguityReason.ENTRY_VS_SESSION_CUTOFF),
    ):
        if boundary is not None and start < boundary < end and trigger:
            return _bounded(
                active,
                (reason,),
                (
                    HistoricalPossibleOutcome(HistoricalTerminalState.EXPIRED, None, None),
                    HistoricalPossibleOutcome(HistoricalTerminalState.OPEN_POSSIBLE, None, None),
                ),
                "price reach and time-boundary order unknown",
            )

    if trigger and invalidated:
        return _bounded(
            active,
            (HistoricalAmbiguityReason.ENTRY_VS_INVALIDATION,),
            (
                HistoricalPossibleOutcome(HistoricalTerminalState.EXPIRED, None, None),
                HistoricalPossibleOutcome(HistoricalTerminalState.OPEN_POSSIBLE, None, None),
            ),
            "trigger and invalidation both reachable in one minute",
        )
    if invalidated:
        return _expired(active, "pre_entry_invalidation")
    if not trigger:
        return None

    gap = bar.open.value >= active.view.tradable_trigger.value
    base = bar.open if gap else active.view.tradable_trigger
    entry = _buy_fill(
        base,
        bar,
        HistoricalFillTiming.BAR_OPEN_EXACT if gap else HistoricalFillTiming.INTRABAR_UNKNOWN,
        profile.entry_slippage_bps,
        ticks,
    )
    active.entry_fill = entry
    economics = strategy.post_fill_economics(
        StrategyEntryFillView(entry.fill_price),
        active.view,
    )
    if entry.fill_price.value <= economics.stop_price.value:
        return _rejected(active, "non_positive_risk")
    if economics.stop_price != active.view.stop_price or economics.raw_target_price is None:
        return _unresolved(
            active,
            (HistoricalAmbiguityReason.UNSUPPORTED_STRATEGY_POLICY,),
            "unsupported post-fill economics",
        )
    tick = ticks.tick_size_on(to_ist(bar.interval.start).date())
    active.raw_target = economics.raw_target_price
    active.tradable_target = ceil_to_tick(economics.raw_target_price, tick)

    stop = bar.low.value <= active.view.stop_price.value
    target = bar.high.value >= active.tradable_target.value
    if not gap and (stop or target):
        reasons = tuple(
            reason
            for reached, reason in (
                (stop, HistoricalAmbiguityReason.ENTRY_VS_POST_FILL_STOP),
                (target, HistoricalAmbiguityReason.ENTRY_VS_POST_FILL_TARGET),
            )
            if reached
        )
        branches = [HistoricalPossibleOutcome(HistoricalTerminalState.OPEN_POSSIBLE, None, None)]
        if stop:
            branches.append(
                HistoricalPossibleOutcome(
                    HistoricalTerminalState.CLOSED,
                    HistoricalExitReason.STOP,
                    _r(active, active.view.stop_price),
                )
            )
        if target:
            branches.append(
                HistoricalPossibleOutcome(
                    HistoricalTerminalState.CLOSED,
                    HistoricalExitReason.TARGET,
                    _r(active, active.tradable_target),
                )
            )
        return _bounded(active, reasons, tuple(branches), "entry/exit order unknown")
    if gap:
        return _resolve_open_reaches(active, bar, ticks, profile)
    return None


def _process_open_bar(
    active: _Active,
    bar: HistoricalBar,
    ticks: TickSizeSchedule,
    profile: HistoricalExecutionAssumptionProfile,
) -> HistoricalExecutionOutcome | None:
    assert active.entry_fill is not None
    assert active.tradable_target is not None
    if bar.interval.start >= _forced_exit_at(bar.interval.start):
        return _closed(
            active,
            _sell_fill(
                bar.open,
                bar,
                HistoricalFillTiming.EXACT_BOUNDARY,
                profile.forced_exit_slippage_bps,
                ticks,
            ),
            HistoricalExitReason.FORCED_SESSION_EXIT,
        )
    return _resolve_open_reaches(active, bar, ticks, profile)


def _resolve_open_reaches(
    active: _Active,
    bar: HistoricalBar,
    ticks: TickSizeSchedule,
    profile: HistoricalExecutionAssumptionProfile,
) -> HistoricalExecutionOutcome | None:
    assert active.tradable_target is not None
    stop = active.view.stop_price
    target = active.tradable_target
    if bar.open.value <= stop.value:
        return _closed(
            active,
            _sell_fill(
                bar.open,
                bar,
                HistoricalFillTiming.BAR_OPEN_EXACT,
                profile.stop_slippage_bps,
                ticks,
            ),
            HistoricalExitReason.STOP,
        )
    if bar.open.value >= target.value:
        return _closed(
            active,
            _sell_fill(
                bar.open,
                bar,
                HistoricalFillTiming.BAR_OPEN_EXACT,
                profile.target_slippage_bps,
                ticks,
            ),
            HistoricalExitReason.TARGET,
        )
    stop_hit = bar.low.value <= stop.value
    target_hit = bar.high.value >= target.value
    if stop_hit and target_hit:
        stop_fill = _sell_fill(
            stop,
            bar,
            HistoricalFillTiming.INTRABAR_UNKNOWN,
            profile.stop_slippage_bps,
            ticks,
        )
        target_fill = _sell_fill(
            target,
            bar,
            HistoricalFillTiming.INTRABAR_UNKNOWN,
            profile.target_slippage_bps,
            ticks,
        )
        return _bounded(
            active,
            (HistoricalAmbiguityReason.STOP_VS_TARGET,),
            (
                HistoricalPossibleOutcome(
                    HistoricalTerminalState.CLOSED,
                    HistoricalExitReason.STOP,
                    _r(active, stop_fill.fill_price),
                ),
                HistoricalPossibleOutcome(
                    HistoricalTerminalState.CLOSED,
                    HistoricalExitReason.TARGET,
                    _r(active, target_fill.fill_price),
                ),
            ),
            "stop and target both reachable in one minute",
        )
    if stop_hit:
        return _closed(
            active,
            _sell_fill(
                stop,
                bar,
                HistoricalFillTiming.INTRABAR_UNKNOWN,
                profile.stop_slippage_bps,
                ticks,
            ),
            HistoricalExitReason.STOP,
        )
    if target_hit:
        return _closed(
            active,
            _sell_fill(
                target,
                bar,
                HistoricalFillTiming.INTRABAR_UNKNOWN,
                profile.target_slippage_bps,
                ticks,
            ),
            HistoricalExitReason.TARGET,
        )
    return None


def _buy_fill(
    base: Price,
    bar: HistoricalBar,
    timing: HistoricalFillTiming,
    bps: Decimal,
    ticks: TickSizeSchedule,
) -> HistoricalModeledFill:
    raw = Price(base.value * (Decimal("1") + bps / _BPS))
    tick = ticks.tick_size_on(to_ist(bar.interval.start).date())
    return HistoricalModeledFill(base, ceil_to_tick(raw, tick), bar.interval, timing, bps)


def _sell_fill(
    base: Price,
    bar: HistoricalBar,
    timing: HistoricalFillTiming,
    bps: Decimal,
    ticks: TickSizeSchedule,
) -> HistoricalModeledFill:
    raw = Price(base.value * (Decimal("1") - bps / _BPS))
    tick = ticks.tick_size_on(to_ist(bar.interval.start).date())
    return HistoricalModeledFill(base, floor_to_tick(raw, tick), bar.interval, timing, bps)


def _r(active: _Active, exit_price: Price) -> Decimal:
    assert active.entry_fill is not None
    risk = active.entry_fill.fill_price.value - active.view.stop_price.value
    return (exit_price.value - active.entry_fill.fill_price.value) / risk


def _closed(
    active: _Active,
    fill: HistoricalModeledFill,
    reason: HistoricalExitReason,
) -> HistoricalExecutionOutcome:
    return HistoricalExecutionOutcome(
        active.opportunity_id,
        active.signal.interval,
        HistoricalOutcomeCertainty.DETERMINATE,
        HistoricalTerminalState.CLOSED,
        active.reasons,
        entry_fill=active.entry_fill,
        exit_fill=fill,
        exit_reason=reason,
        realised_r=_r(active, fill.fill_price),
    )


def _expired(active: _Active, detail: str) -> HistoricalExecutionOutcome:
    return HistoricalExecutionOutcome(
        active.opportunity_id,
        active.signal.interval,
        HistoricalOutcomeCertainty.DETERMINATE,
        HistoricalTerminalState.EXPIRED,
        active.reasons,
        detail=detail,
    )


def _rejected(active: _Active, detail: str) -> HistoricalExecutionOutcome:
    return HistoricalExecutionOutcome(
        active.opportunity_id,
        active.signal.interval,
        HistoricalOutcomeCertainty.DETERMINATE,
        HistoricalTerminalState.REJECTED,
        active.reasons,
        entry_fill=active.entry_fill,
        detail=detail,
    )


def _bounded(
    active: _Active,
    reasons: tuple[HistoricalAmbiguityReason, ...],
    possible: tuple[HistoricalPossibleOutcome, ...],
    detail: str,
) -> HistoricalExecutionOutcome:
    return HistoricalExecutionOutcome(
        active.opportunity_id,
        active.signal.interval,
        HistoricalOutcomeCertainty.BOUNDED_AMBIGUOUS,
        HistoricalTerminalState.UNRESOLVED,
        active.reasons,
        entry_fill=active.entry_fill,
        ambiguity_reasons=reasons,
        possible_outcomes=possible,
        detail=detail,
    )


def _unresolved(
    active: _Active,
    reasons: tuple[HistoricalAmbiguityReason, ...],
    detail: str,
) -> HistoricalExecutionOutcome:
    return HistoricalExecutionOutcome(
        active.opportunity_id,
        active.signal.interval,
        HistoricalOutcomeCertainty.UNRESOLVED,
        HistoricalTerminalState.UNRESOLVED,
        active.reasons,
        entry_fill=active.entry_fill,
        ambiguity_reasons=reasons,
        detail=detail,
    )


def _missing(active: _Active, start: datetime) -> HistoricalExecutionOutcome:
    bucket = CandleInterval(start, start + timedelta(minutes=1))
    outcome = _unresolved(
        active,
        (HistoricalAmbiguityReason.MISSING_EXECUTION_EVIDENCE,),
        "required canonical one-minute execution evidence is missing",
    )
    return replace(outcome, affected_quality_buckets=(bucket,))


def _blocked(
    dataset: HistoricalBarDataset,
    strategy: Strategy,
    decision: StrategyDecision,
) -> HistoricalExecutionOutcome:
    opportunity_id = config_hash(
        {
            "dataset_id": str(dataset.dataset_id),
            "strategy_id": strategy.identity.strategy_id,
            "interval": decision.interval.start.isoformat(),
            "blocked_by_active_lifecycle": True,
        }
    )
    return HistoricalExecutionOutcome(
        opportunity_id,
        decision.interval,
        HistoricalOutcomeCertainty.DETERMINATE,
        HistoricalTerminalState.BLOCKED,
        decision.reasons,
        detail="single-security lifecycle already active",
    )


def _expected_minute_starts(dataset: HistoricalBarDataset) -> Iterator[datetime]:
    for session_date in dataset.manifest.expected_session_dates:
        current = to_utc(datetime.combine(session_date, _SESSION_OPEN, tzinfo=IST))
        end = to_utc(datetime.combine(session_date, _SESSION_END, tzinfo=IST))
        while current < end:
            yield current
            current += timedelta(minutes=1)


def _forced_exit_at(at: datetime) -> datetime:
    local = to_ist(at)
    return datetime.combine(local.date(), _FORCED_EXIT, tzinfo=IST)


def _result(
    dataset: HistoricalBarDataset,
    strategy: Strategy,
    engine_version: str,
    profile: HistoricalExecutionAssumptionProfile,
    outcomes: list[HistoricalExecutionOutcome],
    terminated: bool,
) -> HistoricalExecutionRunResult:
    return HistoricalExecutionRunResult(
        str(dataset.dataset_id),
        strategy.identity.strategy_id,
        strategy.identity.strategy_version,
        strategy.config_identity.config_hash,
        engine_version,
        profile.semantic_id,
        tuple(outcomes),
        _summary(outcomes),
        terminated,
    )


def _summary(outcomes: list[HistoricalExecutionOutcome]) -> HistoricalExecutionSummary:
    total = len(outcomes)
    determinate = [
        o for o in outcomes if o.certainty is HistoricalOutcomeCertainty.DETERMINATE
    ]
    bounded = [
        o
        for o in outcomes
        if o.certainty is HistoricalOutcomeCertainty.BOUNDED_AMBIGUOUS
    ]
    unresolved = [
        o for o in outcomes if o.certainty is HistoricalOutcomeCertainty.UNRESOLVED
    ]
    closed = [
        o
        for o in determinate
        if o.terminal_state is HistoricalTerminalState.CLOSED
        and o.realised_r is not None
    ]
    rs = [o.realised_r for o in closed if o.realised_r is not None]
    coverage = None if total == 0 else Decimal(len(determinate)) / Decimal(total)
    win_rate = None if not rs else Decimal(sum(r > 0 for r in rs)) / Decimal(len(rs))
    expectancy = None if not rs else sum(rs, Decimal("0")) / Decimal(len(rs))
    gains = sum((r for r in rs if r > 0), Decimal("0"))
    losses = -sum((r for r in rs if r < 0), Decimal("0"))
    profit_factor = None if losses == 0 else gains / losses
    cumulative = Decimal("0")
    peak = Decimal("0")
    max_dd = Decimal("0")
    for value in rs:
        cumulative += value
        peak = max(peak, cumulative)
        max_dd = max(max_dd, peak - cumulative)
    return HistoricalExecutionSummary(
        total,
        len(determinate),
        len(bounded),
        len(unresolved),
        coverage,
        len(closed),
        win_rate,
        expectancy,
        profit_factor,
        max_dd,
    )
