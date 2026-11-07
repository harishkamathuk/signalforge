"""Isolated, research-only OHLC-path scenario simulation (SF-258).

This module never asserts observed intraminute order, creates broker fills or
alters the strict historical runner. The only registered path is a hypothetical
Open -> High -> Low -> Close first-crossing order.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType

from signalforge.config.identity import canonical_config_json, config_hash
from signalforge.config.strategy_registry import (
    DEFAULT_STRATEGY_REGISTRY,
    StrategyRegistry,
    StrategySelection,
)
from signalforge.domain.armed import ArmedSetupState
from signalforge.domain.ids import RunId
from signalforge.domain.market import CandleQuality, CompletedCandle
from signalforge.domain.money import Price
from signalforge.domain.provenance import RunIdentity
from signalforge.domain.signals import Signal
from signalforge.research.btc_raw_diagnostic_input import RawDiagnosticSource
from signalforge.research.historical_bars import (
    HistoricalBar,
    HistoricalPriceBasis,
    aggregate_one_minute_to_five_minute,
)
from signalforge.research.historical_execution import (
    CONTINUOUS_HISTORICAL_SESSION_POLICY,
    HistoricalExecutionAssumptionProfile,
    HistoricalPriceMode,
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
    validate_armed_policy,
)


class ScenarioMode(StrEnum):
    """Dispatch discriminator incompatible with strict research or execution."""

    SCENARIO_RESEARCH = "SCENARIO_RESEARCH"


class ScenarioMethodStatus(StrEnum):
    """Methodological sufficiency, never strategy profitability or execution validity."""

    VALID = "SCENARIO_METHOD_VALID"
    INVALID = "SCENARIO_METHOD_INVALID"
    INCONCLUSIVE = "SCENARIO_METHOD_INCONCLUSIVE"


@dataclass(frozen=True, slots=True)
class VersionedRule:
    """Exact registered rule identity; suffixes are not inferred versions."""

    id: str
    version: str

    def __post_init__(self) -> None:
        if not self.id.strip() or not self.version.strip():
            raise ValueError("Scenario rule ID and version are required")

    def mapping(self) -> dict[str, str]:
        """Return stable rule identity."""
        return {"id": self.id, "version": self.version}


_REGISTERED_RULES = (
    VersionedRule("OPEN_HIGH_LOW_CLOSE", "1.0.0-proposal"),
    VersionedRule("REJECT_SAME_LEVEL_TIE_V1", "1.0.0-proposal"),
    VersionedRule("OBSERVED_OPEN_FIRST_V1", "1.0.0-proposal"),
    VersionedRule("FIVE_MINUTE_EXPIRY_AFTER_FINAL_CLOSE_V1", "1.0.0-proposal"),
    VersionedRule("RAW_PROFILE_AFTER_BASE_V1", "1.0.0-proposal"),
)


@dataclass(frozen=True, slots=True)
class ScenarioAssumptionSet:
    """One immutable, fully versioned, allowlisted hypothetical execution model."""

    scenario_id: str
    scenario_version: str
    price_path_rule: VersionedRule
    event_tie_policy: VersionedRule
    gap_policy: VersionedRule
    time_boundary_policy: VersionedRule
    fill_application_policy: VersionedRule

    def __post_init__(self) -> None:
        if (self.scenario_id, self.scenario_version) != (
            "BTC_OHLC_PATH_V1", "0.1.0-proposal"
        ):
            raise ValueError("Only approved BTC_OHLC_PATH_V1 version is registered")
        actual = (
            self.price_path_rule, self.event_tie_policy, self.gap_policy,
            self.time_boundary_policy, self.fill_application_policy,
        )
        if actual != _REGISTERED_RULES:
            raise ValueError("Unknown or contradictory scenario subpolicy identity")

    @classmethod
    def btc_ohlc_path_v1(cls) -> ScenarioAssumptionSet:
        """Construct the sole explicitly registered scenario; never a request default."""
        return cls("BTC_OHLC_PATH_V1", "0.1.0-proposal", *_REGISTERED_RULES)

    def mapping(self) -> dict[str, object]:
        """Return all five independent rule versions without implicit defaults."""
        return {
            "scenario_id": self.scenario_id,
            "scenario_version": self.scenario_version,
            "price_path_rule": self.price_path_rule.mapping(),
            "event_tie_policy": self.event_tie_policy.mapping(),
            "gap_policy": self.gap_policy.mapping(),
            "time_boundary_policy": self.time_boundary_policy.mapping(),
            "fill_application_policy": self.fill_application_policy.mapping(),
        }

    @property
    def semantic_hash(self) -> str:
        """Bind the complete registered rule vocabulary."""
        return config_hash(self.mapping())


@dataclass(frozen=True, slots=True)
class ScenarioResourcePolicy:
    """All finite computational budgets participate in the pre-run identity."""

    policy_id: str
    version: str
    max_bars: int
    max_events: int
    max_outcomes: int
    max_trace_records: int
    max_states: int

    def __post_init__(self) -> None:
        if (self.policy_id, self.version) != ("FINITE_FAIL_CLOSED", "1.0.0"):
            raise ValueError("Unknown scenario resource/exhaustion policy")
        for field in ("max_bars", "max_events", "max_outcomes", "max_trace_records", "max_states"):
            value = getattr(self, field)
            if type(value) is not int or value <= 0:
                raise ValueError(f"{field} must be a finite positive integer")

    def mapping(self) -> dict[str, object]:
        """Return version, exhaustion behaviour and every configured bound."""
        return {
            "policy_id": self.policy_id, "version": self.version,
            "max_bars": self.max_bars, "max_events": self.max_events,
            "max_outcomes": self.max_outcomes, "max_trace_records": self.max_trace_records,
            "max_states": self.max_states,
            "exhaustion": "FAIL_CLOSED_UNRESOLVED",
        }


@dataclass(frozen=True, slots=True)
class ScenarioResearchRequest:
    """Explicit synthetic or audited source plus frozen BTC research parameters."""

    mode: ScenarioMode
    source: RawDiagnosticSource
    strategy_selection: StrategySelection
    engine_calculation_version: str
    assumptions: ScenarioAssumptionSet
    profile: HistoricalExecutionAssumptionProfile
    resources: ScenarioResourcePolicy
    is_start: datetime
    oos_start: datetime
    measured_end: datetime
    repository_revision: str

    def __post_init__(self) -> None:
        if self.mode is not ScenarioMode.SCENARIO_RESEARCH:
            raise ValueError("ScenarioResearchRequest must use SCENARIO_RESEARCH")
        if not isinstance(self.assumptions, ScenarioAssumptionSet):
            raise TypeError("Registered explicit scenario assumptions required")
        if not isinstance(self.resources, ScenarioResourcePolicy):
            raise TypeError("Explicit finite scenario resource policy required")
        if not isinstance(self.source, RawDiagnosticSource) or self.source.execution_valid:
            raise ValueError("Scenario requires provenance-bound non-execution-valid source")
        if (
            self.profile.price_mode is not HistoricalPriceMode.RAW_DIAGNOSTIC
            or self.profile.profile_id not in ("REFERENCE_RAW", "ADVERSE_RAW")
        ):
            raise ValueError("Only frozen BTC RAW profiles are accepted")
        if not self.engine_calculation_version.strip() or not self.repository_revision.strip():
            raise ValueError("Calculation and actual revision identities required")
        if not (
            self.strategy_selection.strategy_id == "btc_momentum_baseline_v0"
            and self.strategy_selection.strategy_version == "0.1.0-experimental"
        ):
            raise ValueError("Scenario research is limited to frozen BTC baseline")
        dataset = self.source.dataset
        if (
            str(dataset.manifest.instrument_id) != "DELTA:BTCUSD"
            or dataset.manifest.grid is None
            or dataset.manifest.price_basis is not HistoricalPriceBasis.TRADED
        ):
            raise ValueError("Scenario requires traded-price continuous BTC source")
        coverage = dataset.manifest.effective_grid.coverage
        if len(coverage) != 1:
            raise ValueError("BTC scenario requires one continuous source coverage interval")
        for field in ("is_start", "oos_start", "measured_end"):
            value = getattr(self, field)
            if value.tzinfo is None or value.utcoffset() != timedelta(0):
                raise ValueError(f"{field} must be UTC aware")
            if value.second or value.microsecond:
                raise ValueError(f"{field} must align to minute boundaries")
        if not (
            coverage[0].start < self.is_start < self.oos_start <= self.measured_end
            <= coverage[0].end
        ):
            raise ValueError("Scenario measured windows must be ordered within source")
        for value in (self.is_start, self.oos_start, self.measured_end):
            if (value - coverage[0].start) % timedelta(minutes=5):
                raise ValueError("Scenario boundaries must align to completed five-minute candles")
        if self.is_start - coverage[0].start < timedelta(minutes=250 * 5):
            raise ValueError("Scenario requires 250 completed warm-up candles")
        if not self.source.source_diagnostic_id.startswith("synthetic-"):
            # The protected-source bridge is the only authority for its source ID.
            if (
                coverage[0].start != datetime(2025, 10, 30, tzinfo=UTC)
                or coverage[0].end != datetime(2026, 10, 30, tzinfo=UTC)
                or self.is_start != datetime(2025, 10, 31, tzinfo=UTC)
                or self.oos_start != datetime(2026, 7, 1, tzinfo=UTC)
                or self.measured_end != datetime(2026, 10, 30, tzinfo=UTC)
            ):
                raise ValueError("Protected scenario must preserve frozen SF-094 windows")
            if len(self.repository_revision) != 40 or any(
                c not in "0123456789abcdef" for c in self.repository_revision.lower()
            ):
                raise ValueError("Protected scenario requests require an actual commit SHA")


def _seal(value: object) -> object:
    """Detach nested input dictionaries from their caller and make them immutable."""
    if isinstance(value, Mapping):
        return MappingProxyType({str(k): _seal(v) for k, v in value.items()})
    if isinstance(value, (tuple, list)):
        return tuple(_seal(v) for v in value)
    return value


def _unseal(value: object) -> object:
    """Expose a copy, never the frozen canonical input mapping."""
    if isinstance(value, Mapping):
        return {str(k): _unseal(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [_unseal(v) for v in value]
    return value


@dataclass(frozen=True, slots=True)
class ScenarioExecutionManifest:
    """Frozen *input-only* identity; outputs must not enter the run-ID preimage."""

    input_mapping: Mapping[str, object]

    def __post_init__(self) -> None:
        object.__setattr__(self, "input_mapping", _seal(self.input_mapping))

    @property
    def run_id(self) -> str:
        """Domain-separate the planned run from strict execution identifiers."""
        return config_hash({"domain": "scenario-run-v1", "inputs": self.input_mapping})

    def mapping(self) -> dict[str, object]:
        """Return the complete pre-run manifest without produced evidence."""
        copied = _unseal(self.input_mapping)
        assert isinstance(copied, dict)
        return copied


@dataclass(frozen=True, slots=True)
class ScenarioTrace:
    """Observed bar reference and explicitly ASSUMED in-minute action ordering."""

    bucket_start: datetime
    from_level: Decimal
    to_level: Decimal
    action: str
    assumed: bool
    modeled_base: Decimal | None = None

    def mapping(self) -> dict[str, object]:
        """Return a lossless canonical trace with no invented event timestamp."""
        return {
            "bucket_start": self.bucket_start.isoformat(),
            "from_level": self.from_level, "to_level": self.to_level,
            "action": self.action, "ordering": "ASSUMED" if self.assumed else "OBSERVED_OPEN",
            "modeled_base": self.modeled_base,
        }


@dataclass(frozen=True, slots=True)
class ScenarioOutcome:
    """Hypothetical scenario-conditioned lifecycle, not an actual executed trade."""

    opportunity_id: str
    state: str
    reason: str
    entry_bucket: datetime | None
    exit_bucket: datetime | None
    entry_price: Decimal | None
    exit_price: Decimal | None
    r: Decimal | None
    holding_span_1m_buckets: int | None

    def mapping(self) -> dict[str, object]:
        """Return explicitly scenario-conditioned and UTC-referenced economics."""
        return {
            "opportunity_id": self.opportunity_id,
            "certainty": "SCENARIO_CONDITIONED", "state": self.state,
            "reason": self.reason,
            "entry_bucket": None if self.entry_bucket is None else self.entry_bucket.isoformat(),
            "exit_bucket": None if self.exit_bucket is None else self.exit_bucket.isoformat(),
            "entry_price": self.entry_price, "exit_price": self.exit_price,
            "r": self.r, "holding_span_1m_buckets": self.holding_span_1m_buckets,
        }


@dataclass(frozen=True, slots=True)
class ScenarioResearchResult:
    """Separate, non-execution-valid output with method-level completeness gates."""

    manifest: ScenarioExecutionManifest
    outcomes: tuple[ScenarioOutcome, ...]
    trace: tuple[ScenarioTrace, ...]
    is_observed: int
    oos_observed: int
    unsupported: int
    failure: str | None
    failure_bucket: datetime | None
    event_count: int
    method_status: ScenarioMethodStatus
    execution_valid: bool = False
    replay_verified: bool = False

    def __post_init__(self) -> None:
        if self.execution_valid:
            raise ValueError("Scenario results may never be execution-valid")
        if self.method_status is ScenarioMethodStatus.VALID and not self.replay_verified:
            raise ValueError("Valid scenario methodology requires verified independent replay")

    @property
    def result_id(self) -> str:
        """Domain-separate result identity from planned run and strict reports."""
        return config_hash({"domain": "scenario-result-v1", "result": self.mapping()})

    @property
    def point_metrics_allowed(self) -> bool:
        """Guard any future conditional point statistics behind frozen completeness."""
        return self.method_status is ScenarioMethodStatus.VALID

    def mapping(self) -> dict[str, object]:
        """Serialize only scenario-conditioned outputs and explicit failure evidence."""
        return {
            "mode": "SCENARIO_RESEARCH", "schema_version": "scenario-result-v1",
            "scenario_run_id": self.manifest.run_id,
            "execution_valid": False, "certainty": "SCENARIO_CONDITIONED",
            "replay_verified": self.replay_verified,
            "is_observed": self.is_observed, "oos_observed": self.oos_observed,
            "unsupported": self.unsupported, "failure": self.failure,
            "failure_bucket": None if self.failure_bucket is None
            else self.failure_bucket.isoformat(),
            "event_count": self.event_count,
            "method_status": self.method_status.value,
            "outcomes": [item.mapping() for item in self.outcomes],
            "trace": [item.mapping() for item in self.trace],
        }

    def write_new(self, destination: Path) -> None:
        """Write canonical result exclusively; never overwrite protected or prior output."""
        if destination.suffix != ".json" or not destination.parent.is_dir():
            raise ValueError("Scenario destination must be a JSON path in an existing directory")
        parent = destination.parent.resolve(strict=True)
        if any(part in ("sf088", "sf096") for part in parent.parts):
            raise ValueError("Scenario output may not be written into protected evidence trees")
        # The exclusive create is the collision barrier; never replace evidence.
        with destination.open("x", encoding="utf-8") as stream:
            stream.write(canonical_config_json({
                "manifest": self.manifest.mapping(),
                "result": self.mapping(),
                "scenario_result_id": self.result_id,
            }))
            stream.write("\n")


@dataclass(slots=True)
class _Active:
    opportunity_id: str
    signal: Signal
    view: ArmedSetupView
    policy: ArmedPolicyIntent
    entry_bucket: datetime | None = None
    entry_price: Price | None = None
    target: Price | None = None


@dataclass(slots=True)
class _Work:
    active: _Active | None
    outcomes: list[ScenarioOutcome]
    trace: list[ScenarioTrace]
    events: int = 0
    unsupported: int = 0
    failure: str | None = None
    failure_bucket: datetime | None = None


def _outcome(active: _Active, state: str, reason: str, bar: HistoricalBar | None = None,
             exit_price: Price | None = None) -> ScenarioOutcome:
    if exit_price is not None and active.entry_price is None:
        raise ValueError("Exit without modeled entry")
    exit_bucket = None if bar is None else bar.interval.start
    span = None
    r = None
    if exit_price is not None:
        assert active.entry_bucket is not None and active.entry_price is not None
        assert bar is not None
        span = 1 + int((bar.interval.start - active.entry_bucket) / timedelta(minutes=1))
        risk = active.entry_price.value - active.view.stop_price.value
        r = (exit_price.value - active.entry_price.value) / risk
    return ScenarioOutcome(
        active.opportunity_id, state, reason, active.entry_bucket, exit_bucket,
        None if active.entry_price is None else active.entry_price.value,
        None if exit_price is None else exit_price.value, r, span,
    )


def _crosses(a: Decimal, b: Decimal, barrier: Decimal) -> bool:
    return (a <= barrier <= b) if a < b else (b <= barrier <= a)


def _sell(base: Decimal, bps: Decimal) -> Price:
    return Price(base * (Decimal("1") - bps / Decimal("10000")))


def _step(
    work: _Work,
    strategy: Strategy,
    profile: HistoricalExecutionAssumptionProfile,
    bar: HistoricalBar,
    start: Decimal,
    end: Decimal,
    *,
    opening: bool,
) -> None:
    """Walk one declared monotone segment; only its first crossing may act.

    Neither segment endpoint order nor a crossing has a provider event timestamp.
    A later segment can react to a target computed only after entry fill.
    """
    cursor = start
    while work.active is not None:
        active = work.active
        if active.entry_price is None:
            invalidation = active.policy.pre_entry_invalidation
            if invalidation is not None and (
                invalidation.direction is not PriceBarrierDirection.AT_OR_BELOW
            ):
                work.failure = "SCENARIO_UNSUPPORTED: invalidation direction"
                work.failure_bucket = bar.interval.start
                return
            trigger = active.view.tradable_trigger.value
            barrier = None if invalidation is None else invalidation.price.value
            candidates: list[tuple[Decimal, str]] = []
            if (opening and cursor >= trigger) or (
                not opening and end >= cursor and _crosses(cursor, end, trigger)
            ):
                candidates.append((cursor if opening else trigger, "ENTRY"))
            if barrier is not None and (
                (opening and cursor <= barrier) or
                (not opening and end <= cursor and _crosses(cursor, end, barrier))
            ):
                candidates.append((cursor if opening else barrier, "INVALIDATION"))
        else:
            assert active.target is not None
            stop = active.view.stop_price.value
            target = active.target.value
            candidates = []
            if (opening and cursor <= stop) or (
                not opening and end <= cursor and _crosses(cursor, end, stop)
            ):
                candidates.append((cursor if opening else stop, "STOP"))
            if (opening and cursor >= target) or (
                not opening and end >= cursor and _crosses(cursor, end, target)
            ):
                candidates.append((cursor if opening else target, "TARGET"))
        if not candidates:
            return
        ascending = end >= cursor
        candidates.sort(key=lambda c: c[0], reverse=not ascending)
        if len(candidates) > 1 and candidates[0][0] == candidates[1][0]:
            work.unsupported += 1
            work.failure = "SCENARIO_UNSUPPORTED: order-changing same-level tie"
            work.failure_bucket = bar.interval.start
            return
        level, action = candidates[0]
        work.events += 1
        work.trace.append(ScenarioTrace(
            bar.interval.start, cursor, level, action,
            not opening, level,
        ))
        if action == "INVALIDATION":
            work.outcomes.append(_outcome(active, "EXPIRED", "PRE_ENTRY_INVALIDATION"))
            work.active = None
            return
        if action == "ENTRY":
            fill = Price(level * (
                Decimal("1") + profile.entry_slippage_bps / Decimal("10000")
            ))
            economics = strategy.post_fill_economics(
                StrategyEntryFillView(fill), active.view
            )
            if (
                fill.value <= economics.stop_price.value
                or economics.stop_price != active.view.stop_price
                or economics.raw_target_price is None
                or economics.raw_target_price.value <= fill.value
            ):
                work.outcomes.append(
                    _outcome(active, "REJECTED", "NON_POSITIVE_OR_UNSUPPORTED_RISK")
                )
                work.active = None
                return
            active.entry_bucket = bar.interval.start
            active.entry_price = fill
            active.target = economics.raw_target_price
        else:
            bps = (profile.stop_slippage_bps if action == "STOP"
                   else profile.target_slippage_bps)
            exit_price = _sell(level, bps)
            work.outcomes.append(_outcome(active, "CLOSED", action, bar, exit_price))
            work.active = None
            return
        # ENTRY can be followed by a target/stop on the same hypothetical leg.
        # Opening is a single observed instant: do not re-process the open.
        if opening:
            return
        cursor = level
        if cursor == end:
            return


def _walk_bar(
    work: _Work,
    strategy: Strategy,
    profile: HistoricalExecutionAssumptionProfile,
    bar: HistoricalBar,
) -> None:
    """Apply the sole registered O-H-L-C scenario without source-event fabrication."""
    active = work.active
    if active is None:
        return
    cutoff = active.policy.strategy_entry_cutoff_at
    if active.entry_price is None and cutoff is not None:
        if bar.interval.start < cutoff < bar.interval.end:
            work.unsupported += 1
            work.failure = "SCENARIO_UNSUPPORTED: unknown in-minute cutoff order"
            work.failure_bucket = bar.interval.start
            return
        if cutoff <= bar.interval.start:
            work.outcomes.append(_outcome(active, "EXPIRED", "STRATEGY_CUTOFF"))
            work.active = None
            return
    if active.entry_price is None and active.view.valid_until <= bar.interval.start:
        work.outcomes.append(_outcome(active, "EXPIRED", "VALIDITY_WINDOW_END"))
        work.active = None
        return
    levels = (bar.open.value, bar.high.value, bar.low.value, bar.close.value)
    _step(work, strategy, profile, bar, levels[0], levels[0], opening=True)
    for start, end in zip(levels[:-1], levels[1:], strict=True):
        if work.failure is not None or work.active is None:
            return
        work.trace.append(ScenarioTrace(
            bar.interval.start, start, end, "ASSUMED_SEGMENT", True,
        ))
        _step(work, strategy, profile, bar, start, end, opening=False)


def _arm(
    strategy: Strategy, run: RunIdentity, candle: CompletedCandle,
    decision: StrategyDecision,
) -> _Active:
    """Reuse strategy-owned intent and policy; never duplicate BTC price formulas."""
    if candle.close is None or candle.low is None:
        raise ValueError("Scenario actionable signal requires complete prices")
    intent = strategy.arm_intent(candle, decision)
    signal = Signal.create(
        instrument_id=candle.instrument_id, interval=candle.interval,
        signal_close=candle.close, signal_low=candle.low,
        run=run, created_at=candle.interval.end,
    )
    view = ArmedSetupView(
        signal.signal_id, intent.raw_trigger, intent.raw_trigger, intent.stop_price,
        candle.interval.end, intent.valid_until, ArmedSetupState.ARMED,
    )
    policy = strategy.armed_policy(signal, view)
    validate_armed_policy(policy, view)
    return _Active(
        config_hash({"domain": "scenario-opportunity-v1",
                     "run_id": str(run.run_id), "signal_id": str(signal.signal_id)}),
        signal, view, policy,
    )


def _manifest(request: ScenarioResearchRequest, strategy: Strategy,
              candles: tuple[CompletedCandle, ...]) -> ScenarioExecutionManifest:
    ds = request.source.dataset
    return ScenarioExecutionManifest({
        "mode_and_schema": {
            "mode": request.mode.value, "schema": "scenario-manifest-v1",
            "simulator": "btc-ohlc-path-scenario-v1",
        },
        "source": {
            "manifest": ds.manifest.semantic_mapping(),
            "dataset_id": str(ds.dataset_id),
            "content_hash": ds.content_hash,
            "source_diagnostic_id": request.source.source_diagnostic_id,
            "five_minute_close_digest": config_hash({
                "close": [None if c.close is None else c.close.value for c in candles],
            }),
        },
        "strategy": {
            "id": strategy.identity.strategy_id,
            "version": strategy.identity.strategy_version,
            "config_id": str(strategy.config_identity.config_id),
            "config_hash": strategy.config_identity.config_hash,
            "engine_calculation_version": request.engine_calculation_version,
        },
        "assumptions": {
            **request.assumptions.mapping(),
            "semantic_hash": request.assumptions.semantic_hash,
        },
        "fills": request.profile.semantic_mapping(),
        "session_and_window": {
            "session": {
                "id": CONTINUOUS_HISTORICAL_SESSION_POLICY.identity.policy_id,
                "version": CONTINUOUS_HISTORICAL_SESSION_POLICY.identity.policy_version,
            },
            "pre_roll_start": ds.manifest.effective_grid.coverage[0].start.isoformat(),
            "is_start": request.is_start.isoformat(),
            "oos_start": request.oos_start.isoformat(),
            "measured_end": request.measured_end.isoformat(),
            "bounds": "half-open UTC",
        },
        "resource_policy": request.resources.mapping(),
        "resource_policy_semantic_hash": config_hash(request.resources.mapping()),
        "implementation": {
            "revision": request.repository_revision,
            "canonical_serializer": "canonical-config-json-v1",
            "scenario_calculation_version": "btc-ohlc-path-scenario-v1",
        },
    })


class ScenarioResearchRunner:
    """Pure, opt-in synthetic/diagnostic scenario lane without strict dispatch."""

    def __init__(self, *, registry: StrategyRegistry = DEFAULT_STRATEGY_REGISTRY) -> None:
        self._registry = registry

    def run_verified(self, request: ScenarioResearchRequest) -> ScenarioResearchResult:
        """Verify a second independent run before allowing full-study method validity."""
        first = self.run(request)
        second = self.run(request)
        if first.result_id != second.result_id or first.mapping() != second.mapping():
            raise ValueError("Scenario deterministic replay mismatch")
        ds = request.source.dataset
        complete = (
            first.failure is None and first.unsupported == 0
            and first.is_observed == 69984 and first.oos_observed == 34848
            and request.measured_end == ds.manifest.effective_grid.coverage[-1].end
            and not request.source.source_diagnostic_id.startswith("synthetic-")
        )
        return replace(
            first, replay_verified=True,
            method_status=ScenarioMethodStatus.VALID if complete else first.method_status,
        )

    def run(self, request: ScenarioResearchRequest) -> ScenarioResearchResult:
        """Simulate assumed events, preserving method-inconclusive failure evidence."""
        if not isinstance(request, ScenarioResearchRequest):
            raise TypeError("Typed scenario research request required")
        dataset = request.source.dataset
        if (
            not request.source.source_diagnostic_id.startswith("synthetic-")
            and self._registry is not DEFAULT_STRATEGY_REGISTRY
        ):
            raise ValueError("Protected runs require the approved strategy registry")
        strategy = self._registry.resolve(request.strategy_selection)
        candles = aggregate_one_minute_to_five_minute(dataset)
        manifest = _manifest(request, strategy, candles)
        run = RunIdentity(
            RunId(manifest.run_id), strategy.identity, strategy.config_identity.config_id,
            strategy.config_identity.config_hash, request.engine_calculation_version,
            CONTINUOUS_HISTORICAL_SESSION_POLICY.identity,
        )
        work = _Work(None, [], [])
        is_count = oos_count = 0

        def finish() -> ScenarioResearchResult:
            # Budget exhaustion is evaluated *before* selecting return evidence:
            # never leak partial economics after a late terminal-state append.
            if work.failure is None and (
                work.events > request.resources.max_events
                or len(work.outcomes) > request.resources.max_outcomes
                or len(work.trace) > request.resources.max_trace_records
            ):
                work.failure = "BUDGET_EXHAUSTED: terminal event/trace/outcome count"
                work.failure_bucket = request.measured_end
            kept_outcomes: tuple[ScenarioOutcome, ...] = (
                () if work.failure is not None else tuple(work.outcomes)
            )
            kept_trace: tuple[ScenarioTrace, ...] = (
                () if work.failure is not None else tuple(work.trace)
            )
            return ScenarioResearchResult(
                manifest, kept_outcomes, kept_trace, is_count, oos_count,
                work.unsupported, work.failure, work.failure_bucket, work.events,
                ScenarioMethodStatus.INVALID if work.failure is not None and
                work.failure.startswith("SOURCE_INVALID") else
                ScenarioMethodStatus.INCONCLUSIVE,
            )

        if (
            dataset.manifest.missing_interval_count
            or len(dataset.bars) != dataset.manifest.effective_grid.expected_minute_count
            or any(c.quality is not CandleQuality.VALID for c in candles)
        ):
            work.failure = "SOURCE_INVALID: missing or incomplete one-minute/five-minute source"
            return finish()
        engine = IndicatorEngine(
            dataset.manifest.instrument_id, request.engine_calculation_version,
            requirements=strategy.indicator_requirements,
        )
        candles_by_end = {c.interval.end: c for c in candles}
        completed = 0
        for bar in dataset.bars:
            if bar.interval.start >= request.measured_end:
                break
            if bar.interval.start < request.is_start:
                # Warm-up only; complete-candle indicator updates still occur below.
                pass
            if len(work.trace) > request.resources.max_trace_records:
                work.failure = "BUDGET_EXHAUSTED: trace records"
            if work.failure is not None:
                work.failure_bucket = bar.interval.start
                return finish()
            if (
                bar.interval.start >= request.is_start
                and len(work.outcomes) >= request.resources.max_outcomes
            ):
                work.failure = "BUDGET_EXHAUSTED: outcomes"
                work.failure_bucket = bar.interval.start
                return finish()
            if bar.interval.start >= request.is_start:
                measured_bars = int((bar.interval.start - request.is_start)
                                    / timedelta(minutes=1)) + 1
                if measured_bars > request.resources.max_bars:
                    work.failure = "BUDGET_EXHAUSTED: minute bars"
                    work.failure_bucket = bar.interval.start
                    return finish()
            if work.active is not None:
                _walk_bar(work, strategy, request.profile, bar)
                if work.failure is not None:
                    return finish()
            if (
                work.events > request.resources.max_events
                or len(work.trace) > request.resources.max_trace_records
                or len(work.outcomes) > request.resources.max_outcomes
            ):
                work.failure = "BUDGET_EXHAUSTED: event/trace/outcome count"
                work.failure_bucket = bar.interval.start
                return finish()
            completed_candle = candles_by_end.get(bar.interval.end)
            if completed_candle is None:
                continue
            # Lifecycle boundary: finish final minute, expire old ARMED,
            # evaluate newly completed 5m strategy, then next minute Open.
            if (
                work.active is not None
                and work.active.entry_price is None
                and work.active.view.valid_until <= completed_candle.interval.end
            ):
                work.outcomes.append(
                    _outcome(work.active, "EXPIRED", "VALIDITY_WINDOW_END")
                )
                work.active = None
            snapshot = engine.update(completed_candle)
            completed += 1
            decision = strategy.evaluate_completed_candle(CompletedCandleStrategyContext(
                candle=completed_candle, indicators=snapshot,
                completed_regular_session_candles=completed,
                continuity=IndicatorContinuity.HEALTHY, feed_state=None,
            ))
            if request.is_start < completed_candle.interval.end <= request.oos_start:
                is_count += 1
            elif request.oos_start < completed_candle.interval.end <= request.measured_end:
                oos_count += 1
            if completed_candle.interval.end <= request.is_start or not decision.actionable:
                continue
            if work.active is not None:
                continue  # One active setup/position; blocked decision is not armed.
            work.active = _arm(strategy, run, completed_candle, decision)
        if work.active is not None:
            work.outcomes.append(_outcome(
                work.active, "OPEN" if work.active.entry_price is not None else "ARMED",
                "DATASET_END_CONDITIONAL",
            ))
        return finish()
