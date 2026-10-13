from __future__ import annotations

import inspect
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path

from signalforge.config.identity import ConfigIdentity, ConfigStatus, identify_config
from signalforge.config.strategy_registry import (
    StrategyRegistration,
    StrategyRegistry,
    StrategySelection,
)
from signalforge.domain.armed import ExpiryReason
from signalforge.domain.ids import InstrumentId
from signalforge.domain.indicators import EmaRequirement, IndicatorRequirements
from signalforge.domain.instruments import TickSizeRule, TickSizeSchedule
from signalforge.domain.market import CandleQuality, CompletedCandle
from signalforge.domain.money import Price
from signalforge.domain.provenance import StrategyIdentity
from signalforge.domain.signals import Signal
from signalforge.domain.time import IST, CandleInterval, to_ist
from signalforge.research.historical_bars import (
    CorporateActionPolicy,
    HistoricalBar,
    HistoricalBarDataset,
    HistoricalDatasetManifest,
    load_historical_bar_fixture,
)
from signalforge.research.historical_execution import (
    HistoricalAmbiguityReason,
    HistoricalBarExecutionRunner,
    HistoricalExecutionAssumptionProfile,
    HistoricalExitReason,
    HistoricalFillTiming,
    HistoricalOutcomeCertainty,
    HistoricalTerminalState,
)
from signalforge.runtime.strategy import (
    ArmedPolicyIntent,
    ArmedSetupView,
    ArmIntent,
    CompletedCandleStrategyContext,
    PositionEconomics,
    PriceBarrierDirection,
    PriceBarrierIntent,
    StrategyDecision,
    StrategyEntryFillView,
)

INSTRUMENT = InstrumentId("NSE:TEST")
SESSION = date(2026, 10, 9)
VERSION = "historical-execution-fixture-v1"


@dataclass(frozen=True, slots=True)
class _DelayedBreakoutDecision:
    instrument_id: InstrumentId
    interval: CandleInterval
    qualified: bool
    actionable: bool
    reasons: tuple[str, ...]


class _DelayedBreakoutStrategy:
    """Test-only ADR-011 third shape; never production-registered."""

    def __init__(
        self,
        *,
        signal_times: tuple[time, ...] = (time(9, 20),),
        cutoff: time | None = time(14, 55),
        validity_minutes: int = 10,
        target_r: Decimal = Decimal("2"),
        invalidation: bool = True,
        stop_override: Decimal | None = None,
    ) -> None:
        self.signal_times = signal_times
        self.cutoff = cutoff
        self.validity_minutes = validity_minutes
        self.target_r = target_r
        self.invalidation = invalidation
        self.stop_override = stop_override

    @property
    def identity(self) -> StrategyIdentity:
        return StrategyIdentity("test_delayed_breakout", "1.0.0")

    @property
    def config_identity(self) -> ConfigIdentity:
        return identify_config(
            {
                "strategy_id": "test_delayed_breakout",
                "strategy_version": "1.0.0",
                "signal_times": [item.isoformat() for item in self.signal_times],
                "cutoff": None if self.cutoff is None else self.cutoff.isoformat(),
                "validity_minutes": self.validity_minutes,
                "target_r": self.target_r,
                "invalidation": self.invalidation,
                "stop_override": self.stop_override,
            },
            status=ConfigStatus.EXPERIMENTAL,
        )

    @property
    def indicator_requirements(self) -> IndicatorRequirements:
        return IndicatorRequirements.of(EmaRequirement(1))

    def evaluate_completed_candle(
        self,
        context: CompletedCandleStrategyContext,
    ) -> _DelayedBreakoutDecision:
        actionable = to_ist(context.candle.interval.end).time() in self.signal_times
        return _DelayedBreakoutDecision(
            context.candle.instrument_id,
            context.candle.interval,
            actionable,
            actionable,
            ("delayed_breakout",) if actionable else ("not_fixture_signal",),
        )

    def arm_intent(
        self,
        candle: CompletedCandle,
        decision: StrategyDecision,
    ) -> ArmIntent:
        assert decision.actionable
        assert candle.close is not None and candle.low is not None
        stop = (
            candle.low
            if self.stop_override is None
            else Price(self.stop_override)
        )
        return ArmIntent(
            raw_trigger=Price(candle.close.value * Decimal("1.002")),
            stop_price=stop,
            valid_until=candle.interval.end + timedelta(minutes=self.validity_minutes),
        )

    def armed_policy(
        self,
        signal: Signal,
        setup: ArmedSetupView,
    ) -> ArmedPolicyIntent:
        cutoff_at = (
            None
            if self.cutoff is None
            else datetime.combine(
                to_ist(signal.interval.end).date(),
                self.cutoff,
                tzinfo=IST,
            )
        )
        barrier = (
            None
            if not self.invalidation
            else PriceBarrierIntent(
                Price(setup.stop_price.value + Decimal("0.05")),
                PriceBarrierDirection.AT_OR_BELOW,
                ExpiryReason.SIGNAL_LOW_BREACH,
            )
        )
        return ArmedPolicyIntent(
            pre_entry_invalidation=barrier,
            strategy_entry_cutoff_at=cutoff_at,
        )

    def post_fill_economics(
        self,
        fill: StrategyEntryFillView,
        setup: ArmedSetupView,
    ) -> PositionEconomics:
        risk = fill.fill_price.value - setup.stop_price.value
        return PositionEconomics(
            setup.stop_price,
            None if risk <= 0 else Price(fill.fill_price.value + self.target_r * risk),
        )


class _UnsupportedPostFillStopStrategy(_DelayedBreakoutStrategy):
    @property
    def config_identity(self) -> ConfigIdentity:
        return identify_config(
            {
                "strategy_id": "test_delayed_breakout",
                "strategy_version": "1.0.0",
                "fixture_variant": "unsupported_post_fill_stop",
            },
            status=ConfigStatus.EXPERIMENTAL,
        )

    def post_fill_economics(
        self,
        fill: StrategyEntryFillView,
        setup: ArmedSetupView,
    ) -> PositionEconomics:
        changed_stop = Price(setup.stop_price.value + Decimal("0.05"))
        risk = fill.fill_price.value - changed_stop.value
        return PositionEconomics(
            changed_stop,
            None if risk <= 0 else Price(fill.fill_price.value + Decimal("2") * risk),
        )


def _registry(
    strategy: _DelayedBreakoutStrategy | None = None,
) -> StrategyRegistry:
    selected = strategy or _DelayedBreakoutStrategy()
    return StrategyRegistry(
        (
            StrategyRegistration(
                "test_delayed_breakout",
                "1.0.0",
                lambda parameters: selected,
            ),
        )
    )


def _bar(
    start: datetime,
    *,
    open_: str = "100.00",
    high: str = "100.10",
    low: str = "99.98",
    close: str = "100.00",
) -> HistoricalBar:
    return HistoricalBar(
        instrument_id=INSTRUMENT,
        interval=CandleInterval(start, start + timedelta(minutes=1)),
        open=Price(Decimal(open_)),
        high=Price(Decimal(high)),
        low=Price(Decimal(low)),
        close=Price(Decimal(close)),
        volume=100,
        quality=CandleQuality.VALID,
        source_provider="fixture",
        source_record_count=1,
        provider_timestamp_raw=start.isoformat(),
        provider_timestamp_interpreted=start,
        canonicalisation_version=VERSION,
    )


def _dataset(
    *,
    ambiguity: bool = False,
    entry_invalidation_ambiguity: bool = False,
    entry_stop_ambiguity: bool = False,
    entry_target_ambiguity: bool = False,
    first_execution_trigger: bool = False,
    gap_entry_with_later_stop: bool = False,
    exit_gap: str | None = None,
    hold_open: bool = False,
    late_entry: bool = False,
    late_trigger_at_session_cutoff: bool = False,
    missing_offset: int | None = None,
) -> HistoricalBarDataset:
    start = datetime(2026, 10, 9, 9, 15, tzinfo=IST)
    bars: list[HistoricalBar] = []
    for offset in range(375):
        at = start + timedelta(minutes=offset)
        kwargs: dict[str, str] = {}
        if offset == 4:
            kwargs = {
                "open_": "100.00",
                "high": "110.00",
                "low": "99.90",
                "close": "100.03",
            }
        elif offset == 5:
            kwargs = {
                "open_": "100.10",
                "high": "100.25" if first_execution_trigger else "100.24",
                "low": "100.00",
                "close": "100.20",
            }
        elif offset == 6:
            if gap_entry_with_later_stop:
                kwargs = {
                    "open_": "100.30",
                    "high": "100.35",
                    "low": "99.90",
                    "close": "100.20",
                }
            else:
                kwargs = {
                    "open_": "100.20",
                    "high": "101.10" if entry_target_ambiguity else "100.25",
                    "low": (
                        "99.80"
                        if entry_stop_ambiguity
                        else "99.94"
                        if entry_invalidation_ambiguity
                        else "100.00"
                    ),
                    "close": "100.20",
                }
        elif offset == 7:
            if exit_gap == "stop":
                kwargs = {
                    "open_": "99.80",
                    "high": "100.00",
                    "low": "99.70",
                    "close": "99.90",
                }
            elif exit_gap == "target":
                kwargs = {
                    "open_": "101.10",
                    "high": "101.20",
                    "low": "101.00",
                    "close": "101.10",
                }
            elif hold_open:
                kwargs = {
                    "open_": "100.30",
                    "high": "100.50",
                    "low": "100.20",
                    "close": "100.30",
                }
            else:
                kwargs = {
                    "open_": "100.30",
                    "high": "101.10",
                    "low": "99.80" if ambiguity else "100.20",
                    "close": "100.80",
                }
        if late_entry and offset == 354:
            kwargs = {
                "open_": "100.00",
                "high": "110.00",
                "low": "99.90",
                "close": "100.03",
            }
        if late_entry and offset == 355:
            kwargs = (
                {
                    "open_": "100.10",
                    "high": "100.19",
                    "low": "100.00",
                    "close": "100.10",
                }
                if late_trigger_at_session_cutoff
                else {
                    "open_": "100.30",
                    "high": "100.35",
                    "low": "100.20",
                    "close": "100.30",
                }
            )
        if late_entry and late_trigger_at_session_cutoff and 356 <= offset < 360:
            kwargs = {
                "open_": "100.10",
                "high": "100.19",
                "low": "100.00",
                "close": "100.10",
            }
        if late_entry and late_trigger_at_session_cutoff and offset == 360:
            kwargs = {
                "open_": "100.10",
                "high": "100.25",
                "low": "100.00",
                "close": "100.20",
            }
        if missing_offset == offset:
            continue
        bars.append(_bar(at, **kwargs))

    manifest = HistoricalDatasetManifest(
        provider="fixture",
        acquisition_adapter="fixture",
        acquisition_version="1",
        requested_instrument="NSE:TEST",
        resolved_provider_instrument="NSE:TEST",
        instrument_id=INSTRUMENT,
        requested_start=start,
        requested_end=datetime(2026, 10, 9, 15, 30, tzinfo=IST),
        returned_start=bars[0].interval.start,
        returned_end=bars[-1].interval.end,
        interval_minutes=1,
        acquired_at=datetime(2026, 10, 12, 12, 0, tzinfo=IST),
        provider_timestamp_representation="ISO-8601",
        timezone_interpretation="Asia/Kolkata interval-start",
        canonicalisation_version=VERSION,
        expected_session_dates=(SESSION,),
        raw_row_count=len(bars),
        canonical_row_count=len(bars),
        missing_interval_count=375 - len(bars),
        duplicate_observation_count=0,
        corrupt_rejected_count=0,
        corporate_action_policy=CorporateActionPolicy.RAW_UNADJUSTED,
        limitations=("test-only",),
    )
    return HistoricalBarDataset(manifest, tuple(bars))


def _ticks(tick: str = "0.05") -> TickSizeSchedule:
    return TickSizeSchedule(
        INSTRUMENT,
        (TickSizeRule(Price(Decimal(tick)), date(2026, 1, 1)),),
    )


def _run(
    dataset: HistoricalBarDataset,
    profile: HistoricalExecutionAssumptionProfile | None = None,
    strategy: _DelayedBreakoutStrategy | None = None,
    tick_schedule: TickSizeSchedule | None = None,
):
    selected = strategy or _DelayedBreakoutStrategy()
    return HistoricalBarExecutionRunner(registry=_registry(selected)).run(
        dataset,
        strategy_selection=StrategySelection("test_delayed_breakout", "1.0.0", {}),
        engine_calculation_version="engine-v1",
        tick_schedule=tick_schedule or _ticks(),
        execution_profile=profile or HistoricalExecutionAssumptionProfile.zero(),
    )


def test_registered_strategies_run_through_historical_runner_contract() -> None:
    root = Path(__file__).parents[3]
    dataset = load_historical_bar_fixture(
        root / "examples/research/historical-bars-one-session.json"
    )
    runner = HistoricalBarExecutionRunner()
    profile = HistoricalExecutionAssumptionProfile.zero()

    momentum = runner.run(
        dataset,
        strategy_selection=StrategySelection("intraday_momentum_v1", "1.0.0", {}),
        engine_calculation_version="engine-v1",
        tick_schedule=_ticks(),
        execution_profile=profile,
    )
    mean_reversion = runner.run(
        dataset,
        strategy_selection=StrategySelection("rsi_mean_reversion_v1", "1.0.0", {}),
        engine_calculation_version="engine-v1",
        tick_schedule=_ticks(),
        execution_profile=profile,
    )

    assert momentum.strategy_id == "intraday_momentum_v1"
    assert mean_reversion.strategy_id == "rsi_mean_reversion_v1"
    # This canonical infrastructure fixture is intentionally not constructed to
    # force either real strategy into a trade. Distinct lifecycle semantics are
    # pressure-tested by the shared semantic-matrix tests; this test proves both
    # real registered implementations traverse the same historical runner API.
    assert momentum.summary.total_actionable_opportunities == 0
    assert mean_reversion.summary.total_actionable_opportunities == 0


def test_third_strategy_shape_runs_deterministically_without_signal_candle_lookahead() -> None:
    dataset = _dataset()

    first = _run(dataset)
    second = _run(dataset)

    assert first == second
    assert first.result_id == second.result_id
    assert first.summary.total_actionable_opportunities == 1
    assert first.summary.determinate_coverage_rate == Decimal("1")
    outcome = first.outcomes[0]
    assert outcome.certainty is HistoricalOutcomeCertainty.DETERMINATE
    assert outcome.terminal_state is HistoricalTerminalState.CLOSED
    assert outcome.entry_fill is not None
    assert to_ist(outcome.entry_fill.bucket.start).time() == datetime.strptime(
        "09:21", "%H:%M"
    ).time()
    assert outcome.entry_fill.timing is HistoricalFillTiming.INTRABAR_UNKNOWN
    assert outcome.entry_fill.fill_price == Price(Decimal("100.25"))
    assert outcome.realised_r == Decimal("2")
    # The 09:15-09:20 signal candle itself reached far above the trigger;
    # execution still cannot begin before the completed-candle boundary.
    assert to_ist(outcome.signal_interval.end).time() == datetime.strptime(
        "09:20", "%H:%M"
    ).time()


def test_raw_trigger_reach_does_not_trigger_until_tradable_trigger_is_reached() -> None:
    outcome = _run(_dataset()).outcomes[0]

    assert outcome.entry_fill is not None
    assert to_ist(outcome.entry_fill.bucket.start) == datetime(
        2026, 10, 9, 9, 21, tzinfo=IST
    )


def test_intrabar_trigger_and_invalidation_are_bounded() -> None:
    result = _run(_dataset(entry_invalidation_ambiguity=True))
    outcome = result.outcomes[0]

    assert outcome.certainty is HistoricalOutcomeCertainty.BOUNDED_AMBIGUOUS
    assert outcome.ambiguity_reasons == (
        HistoricalAmbiguityReason.ENTRY_VS_INVALIDATION,
    )
    assert result.summary.determinate_coverage_rate == Decimal("0")
    assert result.terminated_early is True


def test_gap_entry_at_open_precedes_later_same_bar_invalidation_and_stop() -> None:
    outcome = _run(_dataset(gap_entry_with_later_stop=True)).outcomes[0]

    assert outcome.certainty is HistoricalOutcomeCertainty.DETERMINATE
    assert outcome.terminal_state is HistoricalTerminalState.CLOSED
    assert outcome.entry_fill is not None
    assert outcome.entry_fill.timing is HistoricalFillTiming.BAR_OPEN_EXACT
    assert outcome.realised_r == Decimal("-1")


def test_entry_and_stop_same_minute_is_bounded() -> None:
    strategy = _DelayedBreakoutStrategy(invalidation=False)
    outcome = _run(
        _dataset(entry_stop_ambiguity=True),
        strategy=strategy,
    ).outcomes[0]

    assert outcome.certainty is HistoricalOutcomeCertainty.BOUNDED_AMBIGUOUS
    assert outcome.ambiguity_reasons == (
        HistoricalAmbiguityReason.ENTRY_VS_POST_FILL_STOP,
    )


def test_entry_and_target_same_minute_is_bounded() -> None:
    strategy = _DelayedBreakoutStrategy(invalidation=False)
    outcome = _run(
        _dataset(entry_target_ambiguity=True),
        strategy=strategy,
    ).outcomes[0]

    assert outcome.certainty is HistoricalOutcomeCertainty.BOUNDED_AMBIGUOUS
    assert outcome.ambiguity_reasons == (
        HistoricalAmbiguityReason.ENTRY_VS_POST_FILL_TARGET,
    )


def test_multiple_competing_actions_are_explicit() -> None:
    strategy = _DelayedBreakoutStrategy(cutoff=time(9, 21, 30))
    outcome = _run(
        _dataset(entry_invalidation_ambiguity=True),
        strategy=strategy,
    ).outcomes[0]

    assert outcome.certainty is HistoricalOutcomeCertainty.BOUNDED_AMBIGUOUS
    assert set(outcome.ambiguity_reasons) == {
        HistoricalAmbiguityReason.ENTRY_VS_STRATEGY_CUTOFF,
        HistoricalAmbiguityReason.ENTRY_VS_INVALIDATION,
        HistoricalAmbiguityReason.MULTIPLE_COMPETING_ACTIONS,
    }


def test_stop_gap_uses_observed_open_as_fill_base() -> None:
    outcome = _run(_dataset(exit_gap="stop")).outcomes[0]

    assert outcome.exit_reason is HistoricalExitReason.STOP
    assert outcome.exit_fill is not None
    assert outcome.exit_fill.timing is HistoricalFillTiming.BAR_OPEN_EXACT
    assert outcome.exit_fill.base_price == Price(Decimal("99.80"))


def test_target_gap_uses_observed_open_as_fill_base() -> None:
    outcome = _run(_dataset(exit_gap="target")).outcomes[0]

    assert outcome.exit_reason is HistoricalExitReason.TARGET
    assert outcome.exit_fill is not None
    assert outcome.exit_fill.timing is HistoricalFillTiming.BAR_OPEN_EXACT
    assert outcome.exit_fill.base_price == Price(Decimal("101.10"))


def test_exact_validity_boundary_expires_before_trigger() -> None:
    strategy = _DelayedBreakoutStrategy(validity_minutes=1)
    outcome = _run(_dataset(), strategy=strategy).outcomes[0]

    assert outcome.certainty is HistoricalOutcomeCertainty.DETERMINATE
    assert outcome.terminal_state is HistoricalTerminalState.EXPIRED
    assert outcome.entry_fill is None
    assert outcome.detail == "validity_window_end"


def test_trigger_vs_cutoff_inside_minute_is_bounded() -> None:
    strategy = _DelayedBreakoutStrategy(cutoff=time(9, 20, 30))
    outcome = _run(
        _dataset(first_execution_trigger=True),
        strategy=strategy,
    ).outcomes[0]

    assert outcome.certainty is HistoricalOutcomeCertainty.BOUNDED_AMBIGUOUS
    assert HistoricalAmbiguityReason.ENTRY_VS_STRATEGY_CUTOFF in (
        outcome.ambiguity_reasons
    )


def test_compulsory_1515_exit_precedes_same_boundary_price_reach() -> None:
    strategy = _DelayedBreakoutStrategy(
        signal_times=(time(15, 10),),
        cutoff=None,
    )
    outcome = _run(
        _dataset(late_entry=True),
        strategy=strategy,
    ).outcomes[0]

    assert outcome.exit_reason is HistoricalExitReason.FORCED_SESSION_EXIT
    assert outcome.exit_fill is not None
    assert to_ist(outcome.exit_fill.bucket.start).time() == time(15, 15)
    assert outcome.exit_fill.timing is HistoricalFillTiming.EXACT_BOUNDARY


def test_entry_at_1515_boundary_is_blocked_by_compulsory_session_cutoff() -> None:
    strategy = _DelayedBreakoutStrategy(
        signal_times=(time(15, 10),),
        cutoff=None,
    )
    outcome = _run(
        _dataset(late_entry=True, late_trigger_at_session_cutoff=True),
        strategy=strategy,
    ).outcomes[0]

    assert outcome.terminal_state is HistoricalTerminalState.EXPIRED
    assert outcome.entry_fill is None
    assert outcome.detail == "forced_session_entry_expiry"


def test_stop_and_target_same_minute_is_bounded_not_ordered() -> None:
    result = _run(_dataset(ambiguity=True))
    outcome = result.outcomes[0]

    assert result.terminated_early is False
    assert outcome.certainty is HistoricalOutcomeCertainty.BOUNDED_AMBIGUOUS
    assert HistoricalAmbiguityReason.STOP_VS_TARGET in outcome.ambiguity_reasons
    assert len(outcome.possible_outcomes) == 2
    assert {branch.realised_r for branch in outcome.possible_outcomes} == {
        Decimal("-1"),
        Decimal("2"),
    }


def test_missing_minute_while_armed_is_unresolved_and_terminates_run() -> None:
    result = _run(_dataset(missing_offset=6))

    assert result.terminated_early is True
    outcome = result.outcomes[0]
    assert outcome.certainty is HistoricalOutcomeCertainty.UNRESOLVED
    assert outcome.entry_fill is None
    assert outcome.ambiguity_reasons == (
        HistoricalAmbiguityReason.MISSING_EXECUTION_EVIDENCE,
    )


def test_missing_active_minute_is_unresolved_and_terminates_run() -> None:
    result = _run(_dataset(missing_offset=7))

    assert result.terminated_early is True
    assert result.summary.unresolved_opportunities == 1
    outcome = result.outcomes[0]
    assert outcome.certainty is HistoricalOutcomeCertainty.UNRESOLVED
    assert outcome.ambiguity_reasons == (
        HistoricalAmbiguityReason.MISSING_EXECUTION_EVIDENCE,
    )
    assert len(outcome.affected_quality_buckets) == 1


def test_unsupported_post_fill_policy_is_unresolved_not_silently_reinterpreted() -> None:
    strategy = _UnsupportedPostFillStopStrategy()
    result = _run(_dataset(), strategy=strategy)
    outcome = result.outcomes[0]

    assert result.terminated_early is True
    assert outcome.certainty is HistoricalOutcomeCertainty.UNRESOLVED
    assert outcome.ambiguity_reasons == (
        HistoricalAmbiguityReason.UNSUPPORTED_STRATEGY_POLICY,
    )


def test_non_positive_risk_modeled_entry_is_rejected() -> None:
    strategy = _DelayedBreakoutStrategy(
        invalidation=False,
        stop_override=Decimal("100.30"),
    )
    outcome = _run(_dataset(), strategy=strategy).outcomes[0]

    assert outcome.certainty is HistoricalOutcomeCertainty.DETERMINATE
    assert outcome.terminal_state is HistoricalTerminalState.REJECTED
    assert outcome.detail == "non_positive_risk"


def test_new_actionable_signal_is_blocked_while_position_remains_open() -> None:
    strategy = _DelayedBreakoutStrategy(
        signal_times=(time(9, 20), time(9, 25)),
    )
    result = _run(_dataset(hold_open=True), strategy=strategy)

    assert sum(
        outcome.terminal_state is HistoricalTerminalState.BLOCKED
        for outcome in result.outcomes
    ) == 1
    assert sum(
        outcome.exit_reason is HistoricalExitReason.FORCED_SESSION_EXIT
        for outcome in result.outcomes
    ) == 1


def test_reachability_evidence_is_retained_and_identity_material() -> None:
    result = _run(_dataset())
    outcome = result.outcomes[0]

    assert [item.reachable_actions for item in outcome.reachability_evidence] == [
        (),
        ("entry_trigger",),
        ("target",),
    ]
    assert result.result_id == _run(_dataset()).result_id


def test_fixed_bps_profile_is_adverse_tick_normalized_and_identity_material() -> None:
    zero = HistoricalExecutionAssumptionProfile.zero()
    adverse = HistoricalExecutionAssumptionProfile(
        "adverse-fixed-bps",
        "1",
        Decimal("10"),
        Decimal("10"),
        Decimal("10"),
        Decimal("10"),
        "nse-tick-v1",
    )

    zero_result = _run(_dataset(), zero)
    adverse_result = _run(_dataset(), adverse)

    assert zero.semantic_id != adverse.semantic_id
    assert zero_result.execution_profile_semantic_id != (
        adverse_result.execution_profile_semantic_id
    )
    assert zero_result.result_id != adverse_result.result_id
    assert zero_result.outcomes[0].opportunity_id == (
        adverse_result.outcomes[0].opportunity_id
    )
    assert zero_result.simulator_calculation_version == "historical-bar-execution-v1"
    assert zero_result.outcomes[0].entry_fill is not None
    assert adverse_result.outcomes[0].entry_fill is not None
    assert adverse_result.outcomes[0].entry_fill.fill_price.value > (
        zero_result.outcomes[0].entry_fill.fill_price.value
    )
    adverse_outcome = adverse_result.outcomes[0]
    assert adverse_outcome.raw_target_price is not None
    expected_risk = (
        adverse_outcome.entry_fill.fill_price.value
        - adverse_outcome.stop_price.value
    )
    assert adverse_outcome.raw_target_price.value == (
        adverse_outcome.entry_fill.fill_price.value + Decimal("2") * expected_risk
    )


def test_tick_schedule_semantic_identity_is_result_provenance() -> None:
    first = _run(_dataset(), tick_schedule=_ticks("0.05"))
    second = _run(_dataset(), tick_schedule=_ticks("0.10"))

    assert first.tick_schedule_semantic_id != second.tick_schedule_semantic_id
    assert first.result_id != second.result_id
    assert first.outcomes[0].opportunity_id == second.outcomes[0].opportunity_id


def test_historical_execution_module_has_no_event_backtest_or_real_strategy_dispatch() -> None:
    import signalforge.research.historical_execution as module

    source = inspect.getsource(module)
    for forbidden in (
        "MarketEvent",
        "ReplayInput",
        "ExecutionMode.PAPER",
        "intraday_momentum_v1",
        "rsi_mean_reversion_v1",
    ):
        assert forbidden not in source
