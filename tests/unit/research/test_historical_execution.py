from __future__ import annotations

import inspect
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal

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
from signalforge.domain.time import IST, CandleInterval, to_ist, to_utc
from signalforge.research.historical_bars import (
    CorporateActionPolicy,
    HistoricalBar,
    HistoricalBarDataset,
    HistoricalDatasetManifest,
)
from signalforge.research.historical_execution import (
    HistoricalAmbiguityReason,
    HistoricalBarExecutionRunner,
    HistoricalExecutionAssumptionProfile,
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

    @property
    def identity(self) -> StrategyIdentity:
        return StrategyIdentity("test_delayed_breakout", "1.0.0")

    @property
    def config_identity(self) -> ConfigIdentity:
        return identify_config(
            {
                "strategy_id": "test_delayed_breakout",
                "strategy_version": "1.0.0",
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
        actionable = to_ist(context.candle.interval.end).time() == datetime.strptime(
            "09:20", "%H:%M"
        ).time()
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
        return ArmIntent(
            raw_trigger=Price(candle.close.value * Decimal("1.002")),
            stop_price=candle.low,
            valid_until=candle.interval.end + timedelta(minutes=10),
        )

    def armed_policy(
        self,
        signal: Signal,
        setup: ArmedSetupView,
    ) -> ArmedPolicyIntent:
        cutoff = datetime.combine(
            to_ist(signal.interval.end).date(),
            datetime.strptime("14:55", "%H:%M").time(),
            tzinfo=IST,
        )
        return ArmedPolicyIntent(
            pre_entry_invalidation=PriceBarrierIntent(
                Price(Decimal("99.95")),
                PriceBarrierDirection.AT_OR_BELOW,
                ExpiryReason.SIGNAL_LOW_BREACH,
            ),
            strategy_entry_cutoff_at=cutoff,
        )

    def post_fill_economics(
        self,
        fill: StrategyEntryFillView,
        setup: ArmedSetupView,
    ) -> PositionEconomics:
        risk = fill.fill_price.value - setup.stop_price.value
        return PositionEconomics(
            setup.stop_price,
            None if risk <= 0 else Price(fill.fill_price.value + Decimal("2") * risk),
        )


def _registry() -> StrategyRegistry:
    return StrategyRegistry(
        (
            StrategyRegistration(
                "test_delayed_breakout",
                "1.0.0",
                lambda parameters: _DelayedBreakoutStrategy(),
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
    missing_active_minute: bool = False,
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
            # raw trigger 100.23006 is reachable; tradable 100.25 is not.
            kwargs = {
                "open_": "100.10",
                "high": "100.24",
                "low": "100.00",
                "close": "100.20",
            }
        elif offset == 6:
            kwargs = {
                "open_": "100.20",
                "high": "100.25",
                "low": "100.00",
                "close": "100.20",
            }
        elif offset == 7:
            kwargs = {
                "open_": "100.30",
                "high": "101.10",
                "low": "99.80" if ambiguity else "100.20",
                "close": "100.80",
            }
        if missing_active_minute and offset == 7:
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


def _ticks() -> TickSizeSchedule:
    return TickSizeSchedule(
        INSTRUMENT,
        (TickSizeRule(Price(Decimal("0.05")), date(2026, 1, 1)),),
    )


def _run(
    dataset: HistoricalBarDataset,
    profile: HistoricalExecutionAssumptionProfile | None = None,
):
    return HistoricalBarExecutionRunner(registry=_registry()).run(
        dataset,
        strategy_selection=StrategySelection("test_delayed_breakout", "1.0.0", {}),
        engine_calculation_version="engine-v1",
        tick_schedule=_ticks(),
        execution_profile=profile or HistoricalExecutionAssumptionProfile.zero(),
    )


def test_third_strategy_shape_runs_deterministically_without_signal_candle_lookahead() -> None:
    dataset = _dataset()

    first = _run(dataset)
    second = _run(dataset)

    assert first == second
    assert first.summary.total_actionable_opportunities == 1
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


def test_stop_and_target_same_minute_is_bounded_not_ordered() -> None:
    outcome = _run(_dataset(ambiguity=True)).outcomes[0]

    assert outcome.certainty is HistoricalOutcomeCertainty.BOUNDED_AMBIGUOUS
    assert HistoricalAmbiguityReason.STOP_VS_TARGET in outcome.ambiguity_reasons
    assert len(outcome.possible_outcomes) == 2
    assert {branch.realised_r for branch in outcome.possible_outcomes} == {
        Decimal("-1"),
        Decimal("2"),
    }


def test_missing_active_minute_is_unresolved_and_terminates_run() -> None:
    result = _run(_dataset(missing_active_minute=True))

    assert result.terminated_early is True
    assert result.summary.unresolved_opportunities == 1
    outcome = result.outcomes[0]
    assert outcome.certainty is HistoricalOutcomeCertainty.UNRESOLVED
    assert outcome.ambiguity_reasons == (
        HistoricalAmbiguityReason.MISSING_EXECUTION_EVIDENCE,
    )
    assert len(outcome.affected_quality_buckets) == 1


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
    assert zero_result.outcomes[0].entry_fill is not None
    assert adverse_result.outcomes[0].entry_fill is not None
    assert adverse_result.outcomes[0].entry_fill.fill_price.value > (
        zero_result.outcomes[0].entry_fill.fill_price.value
    )


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
