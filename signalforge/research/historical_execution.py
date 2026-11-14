"""Deterministic historical bar execution under accepted ADR-011 semantics."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Protocol

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
from signalforge.domain.provenance import MarketSessionPolicyIdentity, RunIdentity
from signalforge.domain.signals import Signal
from signalforge.domain.time import CandleInterval, to_ist
from signalforge.research.audited_source_slice_v1 import AuditedSourceSliceV1
from signalforge.research.btc_raw_diagnostic_input import RawDiagnosticSource
from signalforge.research.historical_bars import (
    HistoricalBar,
    HistoricalBarDataset,
    HistoricalContinuityError,
    HistoricalPriceBasis,
    aggregate_one_minute_to_five_minute,
)
from signalforge.runtime.indicators import IndicatorContinuity, IndicatorEngine
from signalforge.runtime.market_session import NSE_INTRADAY_MARKET_SESSION_POLICY
from signalforge.runtime.strategy import (
    ArmedPolicyIntent,
    ArmedSetupView,
    CompletedCandleStrategyContext,
    Strategy,
    StrategyDecision,
    StrategyEntryFillView,
    validate_armed_policy,
)

_BPS = Decimal("10000")
HISTORICAL_EXECUTION_CALCULATION_VERSION = "historical-bar-execution-v1"


class HistoricalPriceMode(StrEnum):
    """Explicit historical price authority; raw levels are never execution-valid."""

    EXECUTION_VALID = "execution_valid"
    RAW_DIAGNOSTIC = "raw_diagnostic"


class HistoricalContinuationPolicy(StrEnum):
    """Optional versioned diagnostic continuation, never the default runner."""

    FAIL_CLOSED_V1 = "fail_closed_v1"
    BOUNDED_FLAT_V1 = "bounded_flat_v1"


# Bounded-flat inference changes modelled research outcomes; keep a distinct
# calculation identity and never rewrite historical-bar-execution-v1 results.
BOUNDED_FLAT_SIMULATOR_VERSION = "historical-bar-execution-v2-bounded-flat"


class HistoricalSessionPolicy(Protocol):
    """Historical projection of the shared SF-089 market/session policy boundary."""

    @property
    def identity(self) -> MarketSessionPolicyIdentity: ...

    def compulsory_exit_at(self, at: datetime) -> datetime | None: ...


class ContinuousHistoricalSessionPolicy:
    """24x7 UTC historical chronology; no implicit UTC-midnight position exit."""

    @property
    def identity(self) -> MarketSessionPolicyIdentity:
        return MarketSessionPolicyIdentity("continuous_utc", "1.0.0")

    def accepts_event(self, at: datetime) -> bool:
        if at.tzinfo is None:
            raise ValueError("Historical timestamp must be aware")
        return True

    def trading_date(self, at: datetime) -> date:
        if at.tzinfo is None:
            raise ValueError("Historical timestamp must be aware")
        return at.astimezone(UTC).date()

    def compulsory_exit_at(self, at: datetime) -> None:
        if at.tzinfo is None:
            raise ValueError("Historical timestamp must be aware")
        return None


CONTINUOUS_HISTORICAL_SESSION_POLICY = ContinuousHistoricalSessionPolicy()


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
    MULTIPLE_COMPETING_ACTIONS = "multiple_competing_actions"
    MISSING_EXECUTION_EVIDENCE = "missing_execution_evidence"
    UNSUPPORTED_STRATEGY_POLICY = "unsupported_strategy_policy"
    DATASET_END_OPEN = "dataset_end_open"
    DATASET_END_ARMED = "dataset_end_armed"


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
    price_mode: HistoricalPriceMode = HistoricalPriceMode.EXECUTION_VALID

    def __post_init__(self) -> None:
        if not self.profile_id.strip() or not self.version.strip():
            raise ValueError("Execution assumption identity must not be empty")
        if not self.tick_rule_version.strip():
            raise ValueError("tick_rule_version must not be empty")
        if self.price_mode is HistoricalPriceMode.RAW_DIAGNOSTIC:
            if self.tick_rule_version != "unresolved":
                raise ValueError("Raw diagnostic requires explicitly unresolved tick rule")
            permitted = {
                "REFERENCE_RAW": (Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0")),
                "ADVERSE_RAW": (Decimal("10"), Decimal("10"), Decimal("10"), Decimal("0")),
            }
            expected = permitted.get(self.profile_id)
            actual = (
                self.entry_slippage_bps,
                self.stop_slippage_bps,
                self.target_slippage_bps,
                self.forced_exit_slippage_bps,
            )
            if self.version != "1.0.0" or expected != actual:
                raise ValueError("Unknown or contradictory frozen RAW_DIAGNOSTIC profile")
        elif self.tick_rule_version == "unresolved":
            raise ValueError("Execution-valid profile cannot use unresolved tick rule")
        for name in (
            "entry_slippage_bps",
            "stop_slippage_bps",
            "target_slippage_bps",
            "forced_exit_slippage_bps",
        ):
            value = getattr(self, name)
            if not isinstance(value, Decimal):
                raise TypeError(f"{name} must be a Decimal")
            if not value.is_finite() or value < 0 or value >= _BPS:
                raise ValueError(
                    f"{name} must be finite, non-negative, and below 10000 bps"
                )

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

    @classmethod
    def reference_raw(cls) -> HistoricalExecutionAssumptionProfile:
        zero = Decimal("0")
        return cls("REFERENCE_RAW", "1.0.0", zero, zero, zero, zero,
                   "unresolved", HistoricalPriceMode.RAW_DIAGNOSTIC)

    @classmethod
    def adverse_raw(cls) -> HistoricalExecutionAssumptionProfile:
        return cls("ADVERSE_RAW", "1.0.0", Decimal("10"), Decimal("10"),
                   Decimal("10"), Decimal("0"), "unresolved",
                   HistoricalPriceMode.RAW_DIAGNOSTIC)

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
            **(
                {"price_mode": self.price_mode.value}
                if self.price_mode is HistoricalPriceMode.RAW_DIAGNOSTIC else {}
            ),
        }


@dataclass(frozen=True, slots=True)
class HistoricalBarReachabilityEvidence:
    """Observed bar and the lifecycle actions it proves reachable."""

    bucket: CandleInterval
    open: Price
    high: Price
    low: Price
    close: Price
    reachable_actions: tuple[str, ...]

    def semantic_mapping(self) -> dict[str, object]:
        return {
            "bucket_start": self.bucket.start.isoformat(),
            "bucket_end": self.bucket.end.isoformat(),
            "open": self.open.value,
            "high": self.high.value,
            "low": self.low.value,
            "close": self.close.value,
            "reachable_actions": list(self.reachable_actions),
        }


@dataclass(frozen=True, slots=True)
class HistoricalModeledFill:
    base_price: Price
    fill_price: Price
    bucket: CandleInterval
    timing: HistoricalFillTiming
    slippage_bps: Decimal

    def semantic_mapping(self) -> dict[str, object]:
        return {
            "base_price": self.base_price.value,
            "fill_price": self.fill_price.value,
            "bucket_start": self.bucket.start.isoformat(),
            "bucket_end": self.bucket.end.isoformat(),
            "timing": self.timing.value,
            "slippage_bps": self.slippage_bps,
        }


@dataclass(frozen=True, slots=True)
class HistoricalPossibleOutcome:
    terminal_state: HistoricalTerminalState
    exit_reason: HistoricalExitReason | None
    realised_r: Decimal | None

    def semantic_mapping(self) -> dict[str, object]:
        return {
            "terminal_state": self.terminal_state.value,
            "exit_reason": None if self.exit_reason is None else self.exit_reason.value,
            "realised_r": self.realised_r,
        }


@dataclass(frozen=True, slots=True)
class HistoricalExecutionOutcome:
    opportunity_id: str
    signal_interval: CandleInterval
    certainty: HistoricalOutcomeCertainty
    terminal_state: HistoricalTerminalState
    decision_reasons: tuple[str, ...]
    raw_trigger: Price | None = None
    tradable_trigger: Price | None = None
    stop_price: Price | None = None
    raw_target_price: Price | None = None
    tradable_target_price: Price | None = None
    entry_fill: HistoricalModeledFill | None = None
    exit_fill: HistoricalModeledFill | None = None
    exit_reason: HistoricalExitReason | None = None
    realised_r: Decimal | None = None
    ambiguity_reasons: tuple[HistoricalAmbiguityReason, ...] = ()
    possible_outcomes: tuple[HistoricalPossibleOutcome, ...] = ()
    reachability_evidence: tuple[HistoricalBarReachabilityEvidence, ...] = ()
    affected_quality_buckets: tuple[CandleInterval, ...] = ()
    detail: str | None = None

    def semantic_mapping(self) -> dict[str, object]:
        return {
            "opportunity_id": self.opportunity_id,
            "signal_interval_start": self.signal_interval.start.isoformat(),
            "signal_interval_end": self.signal_interval.end.isoformat(),
            "certainty": self.certainty.value,
            "terminal_state": self.terminal_state.value,
            "decision_reasons": list(self.decision_reasons),
            "raw_trigger": None if self.raw_trigger is None else self.raw_trigger.value,
            "tradable_trigger": (
                None if self.tradable_trigger is None else self.tradable_trigger.value
            ),
            "stop_price": None if self.stop_price is None else self.stop_price.value,
            "raw_target_price": (
                None if self.raw_target_price is None else self.raw_target_price.value
            ),
            "tradable_target_price": (
                None
                if self.tradable_target_price is None
                else self.tradable_target_price.value
            ),
            "entry_fill": (
                None if self.entry_fill is None else self.entry_fill.semantic_mapping()
            ),
            "exit_fill": None if self.exit_fill is None else self.exit_fill.semantic_mapping(),
            "exit_reason": None if self.exit_reason is None else self.exit_reason.value,
            "realised_r": self.realised_r,
            "ambiguity_reasons": [item.value for item in self.ambiguity_reasons],
            "possible_outcomes": [
                item.semantic_mapping() for item in self.possible_outcomes
            ],
            "reachability_evidence": [
                item.semantic_mapping() for item in self.reachability_evidence
            ],
            "affected_quality_buckets": [
                {
                    "start": item.start.isoformat(),
                    "end": item.end.isoformat(),
                }
                for item in self.affected_quality_buckets
            ],
            "detail": self.detail,
        }


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
    blocked_non_actionable_signals: int | None = None

    def semantic_mapping(self) -> dict[str, object]:
        return {
            "total_actionable_opportunities": self.total_actionable_opportunities,
            "determinate_opportunities": self.determinate_opportunities,
            "bounded_ambiguous_opportunities": self.bounded_ambiguous_opportunities,
            "unresolved_opportunities": self.unresolved_opportunities,
            "determinate_coverage_rate": self.determinate_coverage_rate,
            "determinate_closed_trades": self.determinate_closed_trades,
            "determinate_subset_win_rate": self.determinate_subset_win_rate,
            "determinate_subset_expectancy_r": self.determinate_subset_expectancy_r,
            "determinate_subset_profit_factor_r": self.determinate_subset_profit_factor_r,
            "determinate_subset_max_drawdown_r": self.determinate_subset_max_drawdown_r,
            **({"blocked_non_actionable_signals": self.blocked_non_actionable_signals}
               if self.blocked_non_actionable_signals is not None else {}),
        }


@dataclass(frozen=True, slots=True)
class HistoricalRawDecisionEvidence:
    """Measured completed-candle rejection/indicator trace, RAW_DIAGNOSTIC only."""

    interval: CandleInterval
    qualified: bool
    actionable: bool
    blocked_by_active_lifecycle: bool
    indicator_ready: bool
    reasons: tuple[str, ...]
    macd_line: Decimal | None
    macd_signal: Decimal | None
    macd_histogram: Decimal | None

    def semantic_mapping(self) -> dict[str, object]:
        return {
            "interval_start": self.interval.start.isoformat(),
            "interval_end": self.interval.end.isoformat(),
            "qualified": self.qualified,
            "actionable": self.actionable,
            "blocked_by_active_lifecycle": self.blocked_by_active_lifecycle,
            "indicator_ready": self.indicator_ready,
            "reasons": list(self.reasons),
            "macd_line": self.macd_line,
            "macd_signal": self.macd_signal,
            "macd_histogram": self.macd_histogram,
        }


@dataclass(frozen=True, slots=True)
class HistoricalExecutionRunResult:
    dataset_id: str
    strategy_id: str
    strategy_version: str
    config_hash: str
    engine_calculation_version: str
    simulator_calculation_version: str
    execution_profile_id: str
    execution_profile_version: str
    execution_profile_semantic_id: str
    tick_rule_version: str
    tick_schedule_semantic_id: str
    outcomes: tuple[HistoricalExecutionOutcome, ...]
    summary: HistoricalExecutionSummary
    terminated_early: bool
    execution_valid: bool = True
    market_session_policy_identity: MarketSessionPolicyIdentity = (
        MarketSessionPolicyIdentity("nse_intraday", "1.0.0")
    )
    source_diagnostic_id: str | None = None
    price_mode: HistoricalPriceMode = HistoricalPriceMode.EXECUTION_VALID
    measurement_start: datetime | None = None
    raw_decision_evidence: tuple[HistoricalRawDecisionEvidence, ...] = ()

    def __post_init__(self) -> None:
        if self.price_mode is HistoricalPriceMode.RAW_DIAGNOSTIC:
            if (
                self.execution_valid
                or self.tick_rule_version != "unresolved"
                or self.tick_schedule_semantic_id != "UNRESOLVED_NOT_EXECUTION_VALID"
                or not self.source_diagnostic_id
                or self.measurement_start is None
                or self.market_session_policy_identity != (
                    CONTINUOUS_HISTORICAL_SESSION_POLICY.identity
                )
            ):
                raise ValueError("Raw diagnostic result must be explicitly non-execution-valid")
        elif (
            not self.execution_valid
            or self.source_diagnostic_id is not None
            or self.measurement_start is not None
            or self.raw_decision_evidence
        ):
            raise ValueError("Execution-valid results cannot contain raw diagnostic provenance")

    @property
    def result_id(self) -> str:
        return config_hash(self.semantic_mapping())

    def semantic_mapping(self) -> dict[str, object]:
        return {
            "dataset_id": self.dataset_id,
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "config_hash": self.config_hash,
            "engine_calculation_version": self.engine_calculation_version,
            "simulator_calculation_version": self.simulator_calculation_version,
            "execution_profile_id": self.execution_profile_id,
            "execution_profile_version": self.execution_profile_version,
            "execution_profile_semantic_id": self.execution_profile_semantic_id,
            "tick_rule_version": self.tick_rule_version,
            "tick_schedule_semantic_id": self.tick_schedule_semantic_id,
            "outcomes": [item.semantic_mapping() for item in self.outcomes],
            "summary": self.summary.semantic_mapping(),
            "terminated_early": self.terminated_early,
            **(
                {
                    "execution_valid": False,
                    "price_mode": self.price_mode.value,
                    "market_session_policy": {
                        "policy_id": self.market_session_policy_identity.policy_id,
                        "policy_version": self.market_session_policy_identity.policy_version,
                    },
                    "source_diagnostic_id": self.source_diagnostic_id,
                    "raw_decision_evidence": [
                        item.semantic_mapping() for item in self.raw_decision_evidence
                    ],
                    "measurement_start": (
                        None if self.measurement_start is None
                        else self.measurement_start.isoformat()
                    ),
                }
                if self.price_mode is HistoricalPriceMode.RAW_DIAGNOSTIC else {}
            ),
        }


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
    reachability: list[HistoricalBarReachabilityEvidence] = field(default_factory=list)

    @property
    def is_open(self) -> bool:
        return self.entry_fill is not None


@dataclass(frozen=True, slots=True)
class HistoricalStrictMinuteAudit:
    """A single ADR-011 state-before-bucket strict assessment observation.

    This optional audit channel is not an execution result or observed
    intraminute chronology. Existing historical result identities exclude it.
    """

    bucket_start: datetime
    eligible: bool
    assessed: bool
    ambiguous: bool
    reason: str


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
        tick_schedule: TickSizeSchedule | None,
        execution_profile: HistoricalExecutionAssumptionProfile,
        market_session_policy: HistoricalSessionPolicy = NSE_INTRADAY_MARKET_SESSION_POLICY,
        raw_source: RawDiagnosticSource | AuditedSourceSliceV1 | None = None,
        measurement_start: datetime | None = None,
        continuation_policy: HistoricalContinuationPolicy = (
            HistoricalContinuationPolicy.FAIL_CLOSED_V1
        ),
        strict_minute_observer: Callable[[HistoricalStrictMinuteAudit], None] | None = None,
    ) -> HistoricalExecutionRunResult:
        if not isinstance(continuation_policy, HistoricalContinuationPolicy):
            raise TypeError("Historical continuation policy must be explicitly versioned")
        raw = execution_profile.price_mode is HistoricalPriceMode.RAW_DIAGNOSTIC
        if strict_minute_observer is not None and (
            not raw or continuation_policy is not HistoricalContinuationPolicy.FAIL_CLOSED_V1
        ):
            raise ValueError("Strict minute audit requires FAIL_CLOSED_V1 RAW_DIAGNOSTIC")
        # Evidence and bars travel as one audited bundle, never as caller-paired IDs.
        source_diagnostic_id = None if raw_source is None else raw_source.source_diagnostic_id
        if not raw and continuation_policy is not HistoricalContinuationPolicy.FAIL_CLOSED_V1:
            raise ValueError("Bounded-flat continuation is RAW_DIAGNOSTIC research only")
        if raw:
            if tick_schedule is not None:
                raise ValueError("RAW_DIAGNOSTIC must not accept a historical tick schedule")
            if market_session_policy is not CONTINUOUS_HISTORICAL_SESSION_POLICY:
                raise ValueError("RAW_DIAGNOSTIC requires continuous historical session policy")
            if raw_source is None:
                raise ValueError("RAW_DIAGNOSTIC requires a provenance-bound raw source")
            if raw_source.dataset is not dataset:
                raise ValueError("RAW_DIAGNOSTIC dataset must be the raw source dataset")
            if dataset.manifest.grid is None:
                raise ValueError("RAW_DIAGNOSTIC requires explicit continuous grid")
            if dataset.manifest.price_basis is not HistoricalPriceBasis.TRADED:
                raise ValueError("RAW_DIAGNOSTIC requires proven traded-price basis")
            if measurement_start is None or measurement_start.tzinfo is None:
                raise ValueError("RAW_DIAGNOSTIC requires aware measurement_start")
            measurement_start = measurement_start.astimezone(UTC)
            coverage = dataset.manifest.grid.coverage
            if (
                measurement_start.second
                or measurement_start.microsecond
                or (measurement_start - coverage[0].start) % timedelta(minutes=5)
            ):
                raise ValueError("measurement_start must align to a five-minute bucket")
            if (
                not coverage[0].start < measurement_start < coverage[-1].end
                or measurement_start - coverage[0].start < timedelta(minutes=250 * 5)
            ):
                raise ValueError("RAW_DIAGNOSTIC requires sufficient pre-roll coverage")
            if any(a.end != b.start for a, b in zip(coverage, coverage[1:], strict=False)):
                raise ValueError("RAW_DIAGNOSTIC continuous grid must have no gaps")
        else:
            if tick_schedule is None:
                raise ValueError("Execution-valid historical run requires tick schedule")
            if tick_schedule.instrument_id != dataset.manifest.instrument_id:
                raise ValueError("TickSizeSchedule instrument must match historical dataset")
            if market_session_policy is not NSE_INTRADAY_MARKET_SESSION_POLICY:
                raise ValueError("Execution-valid historical mode requires NSE session policy")
            if raw_source is not None or measurement_start is not None:
                raise ValueError("Raw research identity requires RAW_DIAGNOSTIC")
        strategy = self._registry.resolve(strategy_selection)
        if raw and (
            strategy.identity.strategy_id != "btc_momentum_baseline_v0"
            or strategy.identity.strategy_version != "0.1.0-experimental"
            or str(dataset.manifest.instrument_id) != "DELTA:BTCUSD"
        ):
            raise ValueError("RAW_DIAGNOSTIC is restricted to approved DELTA:BTCUSD baseline")
        run = RunIdentity(
            run_id=deterministic_id(
                RunId,
                str(dataset.dataset_id),
                strategy.config_identity.config_hash,
                engine_calculation_version,
                *(
                    (execution_profile.semantic_id, source_diagnostic_id,
                     measurement_start.isoformat())
                    if raw and measurement_start is not None else ()
                ),
                # Preserve every legacy v1 run/signal/opportunity identity.
                # Only the opt-in v2 computation introduces a new namespace.
                *(
                    (BOUNDED_FLAT_SIMULATOR_VERSION,)
                    if continuation_policy is HistoricalContinuationPolicy.BOUNDED_FLAT_V1
                    else ()
                ),
            ),
            strategy=strategy.identity,
            config_id=strategy.config_identity.config_id,
            config_hash=strategy.config_identity.config_hash,
            engine_calculation_version=engine_calculation_version,
            market_session_policy=market_session_policy.identity,
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
        raw_decisions: list[HistoricalRawDecisionEvidence] = []
        active: _Active | None = None
        completed = 0

        for start in _expected_minute_starts(dataset):
            bar = bar_by_start.get(start)
            if bar is None:
                if active is not None:
                    if strict_minute_observer is not None:
                        strict_minute_observer(HistoricalStrictMinuteAudit(
                            start, True, False, False, "MISSING_EXECUTION_EVIDENCE",
                        ))
                    outcomes.append(_missing(active, start))
                    return _result(
                        dataset,
                        strategy,
                        engine_calculation_version,
                        execution_profile,
                        tick_schedule,
                        outcomes,
                        True,
                        market_session_policy,
                        source_diagnostic_id,
                        measurement_start,
                        raw_decisions,
                        continuation_policy,
                    )
                candle = next(c for c in candles if c.interval.contains(start))
                engine.break_continuity()
                raise HistoricalContinuityError(candle)

            if active is not None:
                # Audit causal eligibility before processing this minute.
                # Arming at a completed 5m boundary cannot retroactively
                # make the just-finished bar an eligible strict minute.
                terminal = _process_bar(
                    active,
                    bar,
                    strategy,
                    tick_schedule,
                    execution_profile,
                    market_session_policy,
                    continuation_policy,
                )
                if strict_minute_observer is not None:
                    bounded_here = (
                        terminal is not None
                        and terminal.certainty is HistoricalOutcomeCertainty.BOUNDED_AMBIGUOUS
                        and bool(terminal.ambiguity_reasons)
                        and bool(terminal.reachability_evidence)
                        and terminal.reachability_evidence[-1].bucket.start == start
                    )
                    unassessed = (
                        terminal is not None
                        and terminal.certainty is HistoricalOutcomeCertainty.UNRESOLVED
                    )
                    strict_minute_observer(HistoricalStrictMinuteAudit(
                        start, True, not unassessed, bounded_here,
                        ("BOUNDED_AMBIGUOUS" if bounded_here else
                         "UNRESOLVED" if unassessed else "ASSESSED"),
                    ))
                if terminal is not None:
                    outcomes.append(terminal)
                    if _requires_run_termination(terminal):
                        return _result(
                            dataset,
                            strategy,
                            engine_calculation_version,
                            execution_profile,
                            tick_schedule,
                            outcomes,
                            True,
                            market_session_policy,
                            source_diagnostic_id,
                            measurement_start,
                            raw_decisions,
                            continuation_policy,
                        )
                    active = None
            elif strict_minute_observer is not None:
                strict_minute_observer(HistoricalStrictMinuteAudit(
                    start, False, False, False, "KNOWN_INELIGIBLE",
                ))

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
            # Retain *all* measured candle decisions (including rejected and
            # blocked) with unrounded MACD evidence. This is an audit trace,
            # never a signal filter or NSE execution-valid output change.
            if raw and measurement_start is not None and (
                completed_candle.interval.end > measurement_start
            ):
                raw_decisions.append(HistoricalRawDecisionEvidence(
                    interval=completed_candle.interval,
                    qualified=decision.qualified,
                    actionable=decision.actionable,
                    blocked_by_active_lifecycle=active is not None and decision.actionable,
                    indicator_ready=snapshot.ready,
                    reasons=decision.reasons,
                    macd_line=snapshot.macd_line,
                    macd_signal=snapshot.macd_signal,
                    macd_histogram=snapshot.macd_histogram,
                ))
            if not decision.actionable:
                continue
            # Diagnostic pre-roll updates indicators but cannot produce trades.
            if (
                measurement_start is not None
                and completed_candle.interval.end <= measurement_start
            ):
                continue
            if active is not None:
                outcomes.append(_blocked(run, decision))
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
                    (
                        (
                            HistoricalAmbiguityReason.DATASET_END_OPEN
                            if active.is_open else HistoricalAmbiguityReason.DATASET_END_ARMED,
                        )
                        if raw else (HistoricalAmbiguityReason.UNSUPPORTED_STRATEGY_POLICY,)
                    ),
                    (
                        "active lifecycle remains unresolved at dataset end"
                        if raw else "active lifecycle survived regular-session evidence"
                    ),
                )
            )

        return _result(
            dataset,
            strategy,
            engine_calculation_version,
            execution_profile,
            tick_schedule,
            outcomes,
            False,
            market_session_policy,
            source_diagnostic_id,
            measurement_start,
            raw_decisions,
            continuation_policy,
        )


def _arm(
    dataset: HistoricalBarDataset,
    strategy: Strategy,
    run: RunIdentity,
    candle: CompletedCandle,
    decision: StrategyDecision,
    tick_schedule: TickSizeSchedule | None,
) -> _Active:
    if candle.close is None or candle.low is None:
        raise ValueError("Actionable candle requires close and low")
    intent = strategy.arm_intent(candle, decision)
    tradable_trigger = (
        intent.raw_trigger if tick_schedule is None else
        ceil_to_tick(
            intent.raw_trigger,
            tick_schedule.tick_size_on(to_ist(candle.interval.end).date()),
        )
    )
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
    validate_armed_policy(policy, view)
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
    ticks: TickSizeSchedule | None,
    profile: HistoricalExecutionAssumptionProfile,
    session: HistoricalSessionPolicy,
    continuation_policy: HistoricalContinuationPolicy,
) -> HistoricalExecutionOutcome | None:
    active.reachability.append(_reachability(active, bar, session))
    return (
        _process_open_bar(active, bar, ticks, profile, session)
        if active.is_open
        else _process_armed_bar(
            active, bar, strategy, ticks, profile, session, continuation_policy
        )
    )


def _process_armed_bar(
    active: _Active,
    bar: HistoricalBar,
    strategy: Strategy,
    ticks: TickSizeSchedule | None,
    profile: HistoricalExecutionAssumptionProfile,
    session: HistoricalSessionPolicy,
    continuation_policy: HistoricalContinuationPolicy,
) -> HistoricalExecutionOutcome | None:
    start, end = bar.interval.start, bar.interval.end
    forced = session.compulsory_exit_at(start)
    cutoff = active.policy.strategy_entry_cutoff_at

    if forced is not None and start >= forced:
        return _expired(active, "forced_session_entry_expiry")
    if cutoff is not None and start >= cutoff:
        return _expired(active, "entry_cutoff_reached")
    if start >= active.view.valid_until:
        return _expired(active, "validity_window_end")

    trigger = bar.high.value >= active.view.tradable_trigger.value
    invalidation = active.policy.pre_entry_invalidation
    invalidated = invalidation is not None and bar.low.value <= invalidation.price.value
    gap = bar.open.value >= active.view.tradable_trigger.value

    # Observed bar OPEN precedes every intrabar trigger. Do not preserve a
    # fictitious entry branch if the accepted invalidation has already fired
    # at that first observed price. Keep v1 behaviour unchanged.
    if (
        continuation_policy is HistoricalContinuationPolicy.BOUNDED_FLAT_V1
        and invalidation is not None
        and not gap
        and bar.open.value <= invalidation.price.value
    ):
        return _expired(active, "pre_entry_invalidation_at_bar_open")

    competing: list[HistoricalAmbiguityReason] = []
    if trigger and not gap:
        for boundary, reason in (
            (cutoff, HistoricalAmbiguityReason.ENTRY_VS_STRATEGY_CUTOFF),
            (active.view.valid_until, HistoricalAmbiguityReason.ENTRY_VS_EXPIRY),
            (forced, HistoricalAmbiguityReason.ENTRY_VS_SESSION_CUTOFF),
        ):
            if boundary is not None and start < boundary < end:
                competing.append(reason)
        if invalidated:
            competing.append(HistoricalAmbiguityReason.ENTRY_VS_INVALIDATION)
        if len(competing) > 1:
            competing.append(HistoricalAmbiguityReason.MULTIPLE_COMPETING_ACTIONS)
        if competing:
            # Only this narrow condition proves that *all* possible lifecycles
            # end FLAT. If invalidation precedes entry the setup expires. If
            # entry precedes invalidation, invalidation <= stop proves the
            # stop was crossed after entry (or a reachable target closed first).
            # A higher pre-entry invalidation or any competing time cutoff
            # cannot safely use this inference.
            if (
                continuation_policy is HistoricalContinuationPolicy.BOUNDED_FLAT_V1
                and profile.price_mode is HistoricalPriceMode.RAW_DIAGNOSTIC
                and invalidation is not None
                and invalidation.price.value <= active.view.stop_price.value
                and competing == [HistoricalAmbiguityReason.ENTRY_VS_INVALIDATION]
            ):
                return _bounded_flat_entry_invalidation(
                    active, bar, strategy, profile
                )
            return _bounded(
                active,
                tuple(competing),
                (
                    HistoricalPossibleOutcome(HistoricalTerminalState.EXPIRED, None, None),
                    HistoricalPossibleOutcome(HistoricalTerminalState.OPEN_POSSIBLE, None, None),
                ),
                "entry ordering against competing intrabar actions is unknown",
            )
    if not gap and invalidated:
        return _expired(active, "pre_entry_invalidation")
    if not trigger:
        return None

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
    active.raw_target = economics.raw_target_price
    active.tradable_target = (
        economics.raw_target_price if ticks is None else
        ceil_to_tick(
            economics.raw_target_price,
            ticks.tick_size_on(to_ist(bar.interval.start).date()),
        )
    )

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
            # For raw diagnostics, possible close branches use the *selected*
            # adverse sell-fill assumptions. Preserve NSE/ADR-011 legacy bounds.
            stop_exit = (
                _sell_fill(
                    active.view.stop_price, bar, HistoricalFillTiming.INTRABAR_UNKNOWN,
                    profile.stop_slippage_bps, ticks,
                ).fill_price
                if ticks is None else active.view.stop_price
            )
            branches.append(
                HistoricalPossibleOutcome(
                    HistoricalTerminalState.CLOSED,
                    HistoricalExitReason.STOP,
                    _r(active, stop_exit),
                )
            )
        if target:
            target_exit = (
                _sell_fill(
                    active.tradable_target, bar, HistoricalFillTiming.INTRABAR_UNKNOWN,
                    profile.target_slippage_bps, ticks,
                ).fill_price
                if ticks is None else active.tradable_target
            )
            branches.append(
                HistoricalPossibleOutcome(
                    HistoricalTerminalState.CLOSED,
                    HistoricalExitReason.TARGET,
                    _r(active, target_exit),
                )
            )
        return _bounded(active, reasons, tuple(branches), "entry/exit order unknown")
    if gap:
        return _resolve_open_reaches(active, bar, ticks, profile)
    return None


def _bounded_flat_entry_invalidation(
    active: _Active,
    bar: HistoricalBar,
    strategy: Strategy,
    profile: HistoricalExecutionAssumptionProfile,
) -> HistoricalExecutionOutcome:
    """Return bounded histories only if their shared future is provably FLAT.

    An intrabar entry still has modeled, not observed, execution prices. The
    conditional STOP (and, where reachable, TARGET) paths are not selected as
    historical truth. Only the common final lifecycle state is established.
    """
    entry = _buy_fill(
        active.view.tradable_trigger,
        bar,
        HistoricalFillTiming.INTRABAR_UNKNOWN,
        profile.entry_slippage_bps,
        None,
    )
    economics = strategy.post_fill_economics(
        StrategyEntryFillView(entry.fill_price), active.view
    )
    if (
        entry.fill_price.value <= active.view.stop_price.value
        or economics.stop_price != active.view.stop_price
        or economics.raw_target_price is None
    ):
        return _unresolved(
            active,
            (HistoricalAmbiguityReason.UNSUPPORTED_STRATEGY_POLICY,),
            "bounded-flat continuation cannot establish supported positive-risk economics",
        )
    active.entry_fill = entry
    active.raw_target = economics.raw_target_price
    active.tradable_target = economics.raw_target_price
    stop_fill = _sell_fill(
        active.view.stop_price, bar, HistoricalFillTiming.INTRABAR_UNKNOWN,
        profile.stop_slippage_bps, None,
    )
    branches = [
        HistoricalPossibleOutcome(HistoricalTerminalState.EXPIRED, None, None),
        HistoricalPossibleOutcome(
            HistoricalTerminalState.CLOSED,
            HistoricalExitReason.STOP,
            _r(active, stop_fill.fill_price),
        ),
    ]
    if bar.high.value >= economics.raw_target_price.value:
        target_fill = _sell_fill(
            economics.raw_target_price, bar, HistoricalFillTiming.INTRABAR_UNKNOWN,
            profile.target_slippage_bps, None,
        )
        branches.append(
            HistoricalPossibleOutcome(
                HistoricalTerminalState.CLOSED,
                HistoricalExitReason.TARGET,
                _r(active, target_fill.fill_price),
            )
        )
    return _bounded(
        active,
        (HistoricalAmbiguityReason.ENTRY_VS_INVALIDATION,),
        tuple(branches),
        "all supported branches end flat; possible entry/exit R remains bounded",
    )


def _process_open_bar(
    active: _Active,
    bar: HistoricalBar,
    ticks: TickSizeSchedule | None,
    profile: HistoricalExecutionAssumptionProfile,
    session: HistoricalSessionPolicy,
) -> HistoricalExecutionOutcome | None:
    assert active.entry_fill is not None
    assert active.tradable_target is not None
    forced = session.compulsory_exit_at(bar.interval.start)
    if forced is not None and bar.interval.start >= forced:
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
    ticks: TickSizeSchedule | None,
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


def _reachability(
    active: _Active,
    bar: HistoricalBar,
    session: HistoricalSessionPolicy,
) -> HistoricalBarReachabilityEvidence:
    actions: list[str] = []
    if active.is_open:
        if bar.low.value <= active.view.stop_price.value:
            actions.append("stop")
        if (
            active.tradable_target is not None
            and bar.high.value >= active.tradable_target.value
        ):
            actions.append("target")
        forced = session.compulsory_exit_at(bar.interval.start)
        if forced is not None and bar.interval.start >= forced:
            actions.append("forced_session_exit")
    else:
        if bar.high.value >= active.view.tradable_trigger.value:
            actions.append("entry_trigger")
        invalidation = active.policy.pre_entry_invalidation
        if invalidation is not None and bar.low.value <= invalidation.price.value:
            actions.append("pre_entry_invalidation")
        cutoff = active.policy.strategy_entry_cutoff_at
        for boundary, name in (
            (cutoff, "strategy_entry_cutoff"),
            (active.view.valid_until, "validity_expiry"),
            (session.compulsory_exit_at(bar.interval.start), "session_cutoff"),
        ):
            if boundary is not None and bar.interval.start <= boundary < bar.interval.end:
                actions.append(name)
    return HistoricalBarReachabilityEvidence(
        bar.interval,
        bar.open,
        bar.high,
        bar.low,
        bar.close,
        tuple(actions),
    )


def _buy_fill(
    base: Price,
    bar: HistoricalBar,
    timing: HistoricalFillTiming,
    bps: Decimal,
    ticks: TickSizeSchedule | None,
) -> HistoricalModeledFill:
    raw = Price(base.value * (Decimal("1") + bps / _BPS))
    fill = raw if ticks is None else ceil_to_tick(
        raw, ticks.tick_size_on(to_ist(bar.interval.start).date())
    )
    return HistoricalModeledFill(base, fill, bar.interval, timing, bps)


def _sell_fill(
    base: Price,
    bar: HistoricalBar,
    timing: HistoricalFillTiming,
    bps: Decimal,
    ticks: TickSizeSchedule | None,
) -> HistoricalModeledFill:
    raw = Price(base.value * (Decimal("1") - bps / _BPS))
    fill = raw if ticks is None else floor_to_tick(
        raw, ticks.tick_size_on(to_ist(bar.interval.start).date())
    )
    return HistoricalModeledFill(base, fill, bar.interval, timing, bps)


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
        raw_trigger=active.view.raw_trigger,
        tradable_trigger=active.view.tradable_trigger,
        stop_price=active.view.stop_price,
        raw_target_price=active.raw_target,
        tradable_target_price=active.tradable_target,
        entry_fill=active.entry_fill,
        exit_fill=fill,
        exit_reason=reason,
        realised_r=_r(active, fill.fill_price),
        reachability_evidence=tuple(active.reachability),
    )


def _expired(active: _Active, detail: str) -> HistoricalExecutionOutcome:
    return HistoricalExecutionOutcome(
        active.opportunity_id,
        active.signal.interval,
        HistoricalOutcomeCertainty.DETERMINATE,
        HistoricalTerminalState.EXPIRED,
        active.reasons,
        raw_trigger=active.view.raw_trigger,
        tradable_trigger=active.view.tradable_trigger,
        stop_price=active.view.stop_price,
        raw_target_price=active.raw_target,
        tradable_target_price=active.tradable_target,
        reachability_evidence=tuple(active.reachability),
        detail=detail,
    )


def _rejected(active: _Active, detail: str) -> HistoricalExecutionOutcome:
    return HistoricalExecutionOutcome(
        active.opportunity_id,
        active.signal.interval,
        HistoricalOutcomeCertainty.DETERMINATE,
        HistoricalTerminalState.REJECTED,
        active.reasons,
        raw_trigger=active.view.raw_trigger,
        tradable_trigger=active.view.tradable_trigger,
        stop_price=active.view.stop_price,
        raw_target_price=active.raw_target,
        tradable_target_price=active.tradable_target,
        entry_fill=active.entry_fill,
        reachability_evidence=tuple(active.reachability),
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
        raw_trigger=active.view.raw_trigger,
        tradable_trigger=active.view.tradable_trigger,
        stop_price=active.view.stop_price,
        raw_target_price=active.raw_target,
        tradable_target_price=active.tradable_target,
        entry_fill=active.entry_fill,
        ambiguity_reasons=reasons,
        possible_outcomes=possible,
        reachability_evidence=tuple(active.reachability),
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
        raw_trigger=active.view.raw_trigger,
        tradable_trigger=active.view.tradable_trigger,
        stop_price=active.view.stop_price,
        raw_target_price=active.raw_target,
        tradable_target_price=active.tradable_target,
        entry_fill=active.entry_fill,
        ambiguity_reasons=reasons,
        reachability_evidence=tuple(active.reachability),
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
    run: RunIdentity,
    decision: StrategyDecision,
) -> HistoricalExecutionOutcome:
    opportunity_id = config_hash(
        {
            "strategy_run_id": str(run.run_id),
            "interval_start": decision.interval.start.isoformat(),
            "interval_end": decision.interval.end.isoformat(),
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
    """Use canonical coverage rather than reconstructing an NSE session."""
    yield from dataset.manifest.effective_grid.minute_starts()

def _requires_run_termination(outcome: HistoricalExecutionOutcome) -> bool:
    if outcome.certainty is HistoricalOutcomeCertainty.UNRESOLVED:
        return True
    if outcome.certainty is not HistoricalOutcomeCertainty.BOUNDED_AMBIGUOUS:
        return False
    return any(
        branch.terminal_state is HistoricalTerminalState.OPEN_POSSIBLE
        for branch in outcome.possible_outcomes
    )


def _result(
    dataset: HistoricalBarDataset,
    strategy: Strategy,
    engine_version: str,
    profile: HistoricalExecutionAssumptionProfile,
    tick_schedule: TickSizeSchedule | None,
    outcomes: list[HistoricalExecutionOutcome],
    terminated: bool,
    session: HistoricalSessionPolicy,
    source_diagnostic_id: str | None,
    measurement_start: datetime | None,
    raw_decisions: list[HistoricalRawDecisionEvidence],
    continuation_policy: HistoricalContinuationPolicy,
) -> HistoricalExecutionRunResult:
    raw = profile.price_mode is HistoricalPriceMode.RAW_DIAGNOSTIC
    # Raw barriers must not be misreported as historically tradable tick prices.
    output = (
        [replace(o, tradable_trigger=None, tradable_target_price=None) for o in outcomes]
        if raw else outcomes
    )
    return HistoricalExecutionRunResult(
        dataset_id=str(dataset.dataset_id),
        strategy_id=strategy.identity.strategy_id,
        strategy_version=strategy.identity.strategy_version,
        config_hash=strategy.config_identity.config_hash,
        engine_calculation_version=engine_version,
        simulator_calculation_version=(
            BOUNDED_FLAT_SIMULATOR_VERSION
            if continuation_policy is HistoricalContinuationPolicy.BOUNDED_FLAT_V1
            else HISTORICAL_EXECUTION_CALCULATION_VERSION
        ),
        execution_profile_id=profile.profile_id,
        execution_profile_version=profile.version,
        execution_profile_semantic_id=profile.semantic_id,
        tick_rule_version=profile.tick_rule_version,
        tick_schedule_semantic_id=(
            "UNRESOLVED_NOT_EXECUTION_VALID" if tick_schedule is None
            else _tick_schedule_semantic_id(tick_schedule)
        ),
        outcomes=tuple(output),
        summary=_summary(outcomes, raw=raw),
        terminated_early=terminated,
        execution_valid=not raw,
        market_session_policy_identity=session.identity,
        source_diagnostic_id=source_diagnostic_id,
        price_mode=profile.price_mode,
        measurement_start=measurement_start,
        raw_decision_evidence=tuple(raw_decisions) if raw else (),
    )


def _tick_schedule_semantic_id(schedule: TickSizeSchedule) -> str:
    return config_hash(
        {
            "instrument_id": str(schedule.instrument_id),
            "rules": [
                {
                    "tick_size": rule.tick_size.value,
                    "effective_from": rule.effective_from.isoformat(),
                    "effective_to": (
                        None
                        if rule.effective_to is None
                        else rule.effective_to.isoformat()
                    ),
                }
                for rule in schedule.rules
            ],
        }
    )


def _summary(
    outcomes: list[HistoricalExecutionOutcome], *, raw: bool = False
) -> HistoricalExecutionSummary:
    # A qualifying signal during an OPEN/ARMED lifecycle is audit evidence,
    # not another actionable opportunity. Preserve legacy NSE summary identity.
    actionable = (
        [o for o in outcomes if o.terminal_state is not HistoricalTerminalState.BLOCKED]
        if raw else outcomes
    )
    total = len(actionable)
    determinate = [
        o for o in actionable if o.certainty is HistoricalOutcomeCertainty.DETERMINATE
    ]
    bounded = [
        o for o in actionable
        if o.certainty is HistoricalOutcomeCertainty.BOUNDED_AMBIGUOUS
    ]
    unresolved = [
        o for o in actionable if o.certainty is HistoricalOutcomeCertainty.UNRESOLVED
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
        len(outcomes) - len(actionable) if raw else None,
    )
