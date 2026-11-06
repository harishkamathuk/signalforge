"""SF-095 synthetic-only strategy and raw historical execution contract tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from signalforge.config.btc_momentum_baseline_v0 import BtcMomentumBaselineV0Config
from signalforge.config.strategy_registry import (
    DEFAULT_STRATEGY_REGISTRY,
    StrategyParameterValidationError,
    StrategyRegistration,
    StrategyRegistry,
    StrategySelection,
)
from signalforge.domain.armed import ArmedSetupState, ExpiryReason
from signalforge.domain.ids import InstrumentId, SignalId
from signalforge.domain.indicators import IndicatorSnapshot
from signalforge.domain.market import CandleQuality, CompletedCandle
from signalforge.domain.money import Price
from signalforge.domain.time import CandleInterval
from signalforge.research.btc_raw_diagnostic_input import RawDiagnosticSource
from signalforge.research.historical_bars import (
    HistoricalBarDataset,
    HistoricalPriceBasis,
    load_historical_bar_fixture,
)
from signalforge.research.historical_execution import (
    CONTINUOUS_HISTORICAL_SESSION_POLICY,
    HistoricalAmbiguityReason,
    HistoricalBarExecutionRunner,
    HistoricalContinuationPolicy,
    HistoricalExecutionAssumptionProfile,
    HistoricalExitReason,
    HistoricalOutcomeCertainty,
    HistoricalPriceMode,
    HistoricalTerminalState,
)
from signalforge.research.historical_grid import HistoricalBarGrid
from signalforge.runtime.btc_momentum_baseline_v0 import (
    BtcMomentumBaselineDecision,
    BtcMomentumBaselineV0Strategy,
)
from signalforge.runtime.indicators import IndicatorContinuity
from signalforge.runtime.strategy import (
    ArmedPolicyIntent,
    ArmedSetupView,
    CompletedCandleStrategyContext,
    PriceBarrierDirection,
    PriceBarrierIntent,
    StrategyEntryFillView,
)

BTC = InstrumentId("DELTA:BTCUSD")
SELECTION = StrategySelection("btc_momentum_baseline_v0", "0.1.0-experimental", {})
EXAMPLE = Path(__file__).resolve().parents[3] / (
    "examples/research/historical-bars-one-session.json"
)


def _context(
    *,
    rsi: str = "58",
    adx: str = "22.1",
    ema9: str = "99",
    ema20: str = "101",
    ema50: str = "100",
    count: int = 250,
    at: datetime | None = None,
) -> CompletedCandleStrategyContext:
    start = at or datetime(2026, 11, 1, 0, 0, tzinfo=UTC)
    interval = CandleInterval(start, start + timedelta(minutes=5))
    candle = CompletedCandle(
        BTC, interval, CandleQuality.VALID,
        Price(Decimal("100")), Price(Decimal("101")),
        Price(Decimal("98")), Price(Decimal("100")),
        10, "synthetic", 5,
    )
    snapshot = IndicatorSnapshot(
        BTC, interval, "engine-v1", ready=True,
        ema9=Decimal(ema9), ema20=Decimal(ema20), ema50=Decimal(ema50),
        rsi14=Decimal(rsi), adx14=Decimal(adx),
        macd_line=Decimal("0"), macd_signal=Decimal("-1"),
        macd_histogram=Decimal("1"),
    )
    return CompletedCandleStrategyContext(
        candle, snapshot, count, IndicatorContinuity.HEALTHY, None
    )


def test_registered_btc_identity_and_frozen_config():
    strategy = DEFAULT_STRATEGY_REGISTRY.resolve(SELECTION)
    assert isinstance(strategy, BtcMomentumBaselineV0Strategy)
    assert strategy.identity.strategy_id == "btc_momentum_baseline_v0"
    assert strategy.identity.strategy_version == "0.1.0-experimental"
    assert strategy.config_identity == DEFAULT_STRATEGY_REGISTRY.resolve(
        SELECTION
    ).config_identity
    assert BtcMomentumBaselineV0Config().identify() == strategy.config_identity
    for parameters in ({"rsi_min": Decimal("57")}, {"timeframe_minutes": 1},
                       {"unknown_option": "enable"}):
        with pytest.raises(StrategyParameterValidationError):
            DEFAULT_STRATEGY_REGISTRY.resolve(
                StrategySelection(
                    SELECTION.strategy_id, SELECTION.strategy_version, parameters
                )
            )


@pytest.mark.parametrize(
    ("overrides", "actionable"),
    [
        ({}, True),
        ({"rsi": "65"}, True),
        ({"rsi": "57.999"}, False),
        ({"rsi": "65.001"}, False),
        ({"adx": "22"}, False),
        ({"ema9": "100"}, False),
        ({"ema20": "100"}, False),
        ({"count": 249}, False),
    ],
)
def test_frozen_boundaries_and_250_candle_readiness(overrides, actionable):
    strategy = DEFAULT_STRATEGY_REGISTRY.resolve(SELECTION)
    decision = strategy.evaluate_completed_candle(_context(**overrides))
    assert decision.actionable is actionable
    if overrides.get("count") == 249:
        assert "insufficient_warmup" in decision.reasons
    if actionable:
        assert decision.macd_signal_positive is False


def test_btc_strategy_rejects_unapproved_instrument() -> None:
    context = _context()
    other = replace(context.candle, instrument_id=InstrumentId("NSE:TEST"))
    with pytest.raises(ValueError, match="approved DELTA:BTCUSD"):
        DEFAULT_STRATEGY_REGISTRY.resolve(SELECTION).evaluate_completed_candle(
            replace(context, candle=other)
        )


def test_raw_arm_intent_and_actual_fill_economics():
    strategy = DEFAULT_STRATEGY_REGISTRY.resolve(SELECTION)
    context = _context()
    decision = strategy.evaluate_completed_candle(context)
    arm = strategy.arm_intent(context.candle, decision)
    assert arm.raw_trigger.value == Decimal("100.100")
    assert arm.stop_price.value == Decimal("98")
    assert arm.valid_until == context.candle.interval.end + timedelta(minutes=5)
    view = ArmedSetupView(
        SignalId("synthetic"), arm.raw_trigger, arm.raw_trigger,
        arm.stop_price, context.candle.interval.end, arm.valid_until,
        ArmedSetupState.ARMED,
    )
    economics = strategy.post_fill_economics(
        StrategyEntryFillView(Price(Decimal("100.2"))), view
    )
    assert economics.stop_price.value == Decimal("98")
    assert economics.raw_target_price is not None
    assert economics.raw_target_price.value == Decimal("103.50")


def _synthetic_continuous_dataset() -> HistoricalBarDataset:
    """Non-performance fixture with OPEN position persisting through UTC midnight."""
    legacy = load_historical_bar_fixture(EXAMPLE)
    start = datetime(2026, 11, 1, 2, 55, tzinfo=UTC)
    minutes = 255 * 5
    original = legacy.bars[0]
    bars = []
    for offset in range(minutes):
        at = start + timedelta(minutes=offset)
        price = Decimal("100.2") if offset >= 251 * 5 else Decimal("100")
        bars.append(replace(
            original,
            instrument_id=BTC,
            interval=CandleInterval(at, at + timedelta(minutes=1)),
            open=Price(price),
            high=Price(price + Decimal("0.01")),
            low=Price(price - Decimal("0.01")),
            close=Price(price),
            provider_timestamp_raw=at.isoformat(),
            provider_timestamp_interpreted=at,
        ))
    manifest = replace(
        legacy.manifest,
        instrument_id=BTC,
        requested_instrument="DELTA:BTCUSD",
        resolved_provider_instrument="BTCUSD",
        expected_session_dates=(),
        price_basis=HistoricalPriceBasis.TRADED,
        limitations=("UNQUALIFIED_HISTORICAL_METADATA", "SYNTHETIC_TEST_ONLY"),
        grid=HistoricalBarGrid(
            "continuous-test", "1",
            (CandleInterval(start, start + timedelta(minutes=minutes)),),
        ),
        requested_start=start,
        requested_end=start + timedelta(minutes=minutes),
        returned_start=start,
        returned_end=start + timedelta(minutes=minutes),
        raw_row_count=minutes,
        canonical_row_count=minutes,
        missing_interval_count=0,
        duplicate_observation_count=0,
        corrupt_rejected_count=0,
    )
    return HistoricalBarDataset(manifest, tuple(bars))


class _SyntheticTrigger(BtcMomentumBaselineV0Strategy):
    """Execution-mechanics fixture; no actual BTC strategy performance evaluated."""

    def evaluate_completed_candle(
        self, context: CompletedCandleStrategyContext
    ) -> BtcMomentumBaselineDecision:
        is_signal = context.completed_regular_session_candles == 251
        return BtcMomentumBaselineDecision(
            context.candle.instrument_id,
            context.candle.interval,
            is_signal,
            is_signal,
            ("synthetic_execution_probe",),
            None,
        )


def test_raw_diagnostic_cross_midnight_open_remains_unresolved():
    dataset = _synthetic_continuous_dataset()
    registry = StrategyRegistry((
        StrategyRegistration(
            "btc_momentum_baseline_v0", "0.1.0-experimental",
            lambda _: _SyntheticTrigger(BtcMomentumBaselineV0Config()),
        ),
    ))
    runner = HistoricalBarExecutionRunner(registry=registry)
    arguments = dict(
        strategy_selection=SELECTION,
        engine_calculation_version="engine-v1",
        tick_schedule=None,
        execution_profile=HistoricalExecutionAssumptionProfile.reference_raw(),
        market_session_policy=CONTINUOUS_HISTORICAL_SESSION_POLICY,
        raw_source=RawDiagnosticSource(dataset, "synthetic-only-test-source"),
        measurement_start=dataset.manifest.requested_start + timedelta(minutes=250 * 5),
    )
    first = runner.run(dataset, **arguments)
    second = runner.run(dataset, **arguments)
    assert first.result_id == second.result_id
    assert first.execution_valid is False
    assert first.price_mode is HistoricalPriceMode.RAW_DIAGNOSTIC
    assert first.tick_schedule_semantic_id == "UNRESOLVED_NOT_EXECUTION_VALID"
    assert first.market_session_policy_identity.policy_id == "continuous_utc"
    assert first.source_diagnostic_id == "synthetic-only-test-source"
    assert len(first.outcomes) == 1
    outcome = first.outcomes[0]
    assert outcome.certainty is HistoricalOutcomeCertainty.UNRESOLVED
    assert outcome.terminal_state is HistoricalTerminalState.UNRESOLVED
    assert outcome.entry_fill is not None
    assert outcome.entry_fill.bucket.start.date() != (
        dataset.manifest.requested_end.date()
    )
    assert outcome.tradable_trigger is None
    assert outcome.tradable_target_price is None
    assert all("forced_session_exit" not in evidence.reachable_actions
               for evidence in outcome.reachability_evidence)


def test_diagnostic_cannot_masquerade_as_execution_valid():
    dataset = _synthetic_continuous_dataset()
    runner = HistoricalBarExecutionRunner()
    with pytest.raises(ValueError, match="tick schedule"):
        runner.run(
            dataset, strategy_selection=SELECTION,
            engine_calculation_version="engine-v1", tick_schedule=None,
            execution_profile=HistoricalExecutionAssumptionProfile.zero(),
        )
    with pytest.raises(ValueError, match="continuous historical session policy"):
        runner.run(
            dataset, strategy_selection=SELECTION,
            engine_calculation_version="engine-v1", tick_schedule=None,
            execution_profile=HistoricalExecutionAssumptionProfile.reference_raw(),
            raw_source=RawDiagnosticSource(dataset, "synthetic-test-evidence"),
            measurement_start=dataset.manifest.requested_start + timedelta(minutes=250 * 5),
        )
    with pytest.raises(ValueError, match="provenance-bound raw source"):
        runner.run(
            dataset, strategy_selection=SELECTION,
            engine_calculation_version="engine-v1", tick_schedule=None,
            execution_profile=HistoricalExecutionAssumptionProfile.reference_raw(),
            market_session_policy=CONTINUOUS_HISTORICAL_SESSION_POLICY,
            measurement_start=dataset.manifest.requested_start + timedelta(minutes=250 * 5),
        )
    assert HistoricalExecutionAssumptionProfile.reference_raw().semantic_id != (
        HistoricalExecutionAssumptionProfile.adverse_raw().semantic_id
    )
    with pytest.raises(ValueError, match="unresolved"):
        HistoricalExecutionAssumptionProfile(
            "invalid", "1", Decimal("0"), Decimal("0"), Decimal("0"),
            Decimal("0"), "today-tick",
            HistoricalPriceMode.RAW_DIAGNOSTIC,
        )


def _synthetic_runner(signal_count: int) -> HistoricalBarExecutionRunner:
    """Inject a deterministic execution probe, never the real BTC strategy signals."""

    class _Probe(_SyntheticTrigger):
        def evaluate_completed_candle(
            self, context: CompletedCandleStrategyContext
        ) -> BtcMomentumBaselineDecision:
            yes = context.completed_regular_session_candles == signal_count
            return BtcMomentumBaselineDecision(
                context.candle.instrument_id, context.candle.interval,
                yes, yes, ("synthetic_probe",), None
            )

    return HistoricalBarExecutionRunner(
        registry=StrategyRegistry((
            StrategyRegistration(
                "btc_momentum_baseline_v0", "0.1.0-experimental",
                lambda _: _Probe(BtcMomentumBaselineV0Config()),
            ),
        ))
    )


def _raw_run(
    dataset, *, profile=None, runner=None, measurement_start=None,
    continuation_policy=HistoricalContinuationPolicy.FAIL_CLOSED_V1,
):
    return (runner or _synthetic_runner(251)).run(
        dataset,
        strategy_selection=SELECTION,
        engine_calculation_version="engine-v1",
        tick_schedule=None,
        execution_profile=profile or HistoricalExecutionAssumptionProfile.reference_raw(),
        market_session_policy=CONTINUOUS_HISTORICAL_SESSION_POLICY,
        raw_source=RawDiagnosticSource(dataset, "synthetic-only-test-source"),
        continuation_policy=continuation_policy,
        measurement_start=measurement_start or (
            dataset.manifest.requested_start + timedelta(minutes=250 * 5)
        ),
    )


def test_pre_roll_can_only_warm_indicators_and_never_arm():
    dataset = _synthetic_continuous_dataset()
    result = _raw_run(dataset, runner=_synthetic_runner(250))
    assert result.outcomes == ()
    assert result.execution_valid is False
    assert result.measurement_start == (
        dataset.manifest.requested_start + timedelta(minutes=250 * 5)
    )


def test_raw_adverse_entry_fill_sets_new_target_from_actual_fill():
    dataset = _synthetic_continuous_dataset()
    reference = _raw_run(dataset)
    adverse = _raw_run(
        dataset, profile=HistoricalExecutionAssumptionProfile.adverse_raw()
    )
    ref = reference.outcomes[0]
    adv = adverse.outcomes[0]
    assert ref.entry_fill is not None
    assert ref.entry_fill.fill_price.value == Decimal("100.2")
    assert adv.entry_fill is not None
    assert adv.entry_fill.fill_price.value == Decimal("100.3002")
    assert adv.raw_target_price is not None
    assert adv.raw_target_price.value == Decimal("100.7655")
    assert ref.raw_target_price is not None
    assert ref.raw_target_price.value == Decimal("100.515")
    assert adverse.result_id != reference.result_id
    assert adverse.execution_valid is False


def test_raw_diagnostic_preserves_stop_target_ambiguity():
    dataset = _synthetic_continuous_dataset()
    entry_index = 251 * 5
    bars = list(dataset.bars)
    bars[entry_index] = replace(
        bars[entry_index],
        high=Price(Decimal("101")),
        low=Price(Decimal("99")),
    )
    changed = HistoricalBarDataset(dataset.manifest, tuple(bars))
    result = _raw_run(changed)
    # Both ambiguous branches close, so chronology can continue safely.
    assert not result.terminated_early
    assert result.outcomes[0].certainty is HistoricalOutcomeCertainty.BOUNDED_AMBIGUOUS
    assert HistoricalAmbiguityReason.STOP_VS_TARGET in (
        result.outcomes[0].ambiguity_reasons
    )
    assert result.execution_valid is False




@pytest.mark.parametrize(
    ("invalidate", "expected_detail"),
    [
        (False, "validity_window_end"),
        (True, "pre_entry_invalidation"),
    ],
)
def test_btc_next_candle_only_expiry_and_signal_low_invalidation(
    invalidate: bool, expected_detail: str,
):
    """Synthetic chronology checks shared ARMED lifecycle with BTC policy."""
    dataset = _synthetic_continuous_dataset()
    bars = list(dataset.bars)
    first = 251 * 5
    for offset in range(5):
        old = bars[first + offset]
        at_stop = invalidate and offset == 0
        bars[first + offset] = replace(
            old,
            open=Price(Decimal("100")),
            high=Price(Decimal("100.01")),
            low=Price(Decimal("99.98" if at_stop else "100")),
            close=Price(Decimal("100")),
        )
    altered = HistoricalBarDataset(dataset.manifest, tuple(bars))
    result = _raw_run(altered)
    assert len(result.outcomes) == 1
    assert result.outcomes[0].certainty is HistoricalOutcomeCertainty.DETERMINATE
    assert result.outcomes[0].terminal_state is HistoricalTerminalState.EXPIRED
    assert result.outcomes[0].detail == expected_detail
    assert result.outcomes[0].entry_fill is None


def test_armed_setup_at_dataset_end_is_not_misclassified_as_open_position():
    dataset = _synthetic_continuous_dataset()
    result = _raw_run(dataset, runner=_synthetic_runner(255))
    assert len(result.outcomes) == 1
    assert result.outcomes[0].terminal_state is HistoricalTerminalState.UNRESOLVED
    assert result.outcomes[0].entry_fill is None
    assert result.outcomes[0].ambiguity_reasons == (
        HistoricalAmbiguityReason.DATASET_END_ARMED,
    )


def test_raw_diagnostic_rejects_unaligned_measurement_start_and_mutable_status():
    dataset = _synthetic_continuous_dataset()
    with pytest.raises(ValueError, match="five-minute bucket"):
        _raw_run(
            dataset, measurement_start=(
                dataset.manifest.requested_start + timedelta(minutes=250 * 5 + 1)
            )
        )
    result = _raw_run(dataset)
    with pytest.raises(ValueError, match="non-execution-valid"):
        replace(result, execution_valid=True)
    with pytest.raises(ValueError, match="RAW_DIAGNOSTIC profile"):
        HistoricalExecutionAssumptionProfile(
            "REFERENCE_RAW", "1.0.0", Decimal("10"), Decimal("0"), Decimal("0"),
            Decimal("0"), "unresolved", HistoricalPriceMode.RAW_DIAGNOSTIC
        )

def test_raw_rejects_cross_paired_source_and_dataset() -> None:
    first = _synthetic_continuous_dataset()
    altered_bars = list(first.bars)
    altered_bars[0] = replace(altered_bars[0], high=Price(Decimal("101")))
    second = HistoricalBarDataset(first.manifest, tuple(altered_bars))
    verified = RawDiagnosticSource(first, "synthetic-first-evidence")
    with pytest.raises(ValueError, match="raw source dataset"):
        _synthetic_runner(251).run(
            second,
            strategy_selection=SELECTION,
            engine_calculation_version="engine-v1",
            tick_schedule=None,
            execution_profile=HistoricalExecutionAssumptionProfile.reference_raw(),
            market_session_policy=CONTINUOUS_HISTORICAL_SESSION_POLICY,
            raw_source=verified,
            measurement_start=second.manifest.requested_start + timedelta(minutes=250 * 5),
        )


def test_blocked_btc_signals_are_not_actionable_opportunities() -> None:
    dataset = _synthetic_continuous_dataset()

    class _RepeatedSignals(_SyntheticTrigger):
        def evaluate_completed_candle(
            self, context: CompletedCandleStrategyContext
        ) -> BtcMomentumBaselineDecision:
            count = context.completed_regular_session_candles
            active = count >= 251
            return BtcMomentumBaselineDecision(
                context.candle.instrument_id,
                context.candle.interval,
                active,
                active,
                ("synthetic_repeat",),
                None,
            )

    runner = HistoricalBarExecutionRunner(registry=StrategyRegistry((
        StrategyRegistration(
            "btc_momentum_baseline_v0", "0.1.0-experimental",
            lambda _: _RepeatedSignals(BtcMomentumBaselineV0Config()),
        ),
    )))
    result = _raw_run(dataset, runner=runner)
    assert result.summary.total_actionable_opportunities == 1
    assert result.summary.blocked_non_actionable_signals == 4
    assert result.summary.unresolved_opportunities == 1
    assert result.summary.determinate_opportunities == 0
    assert result.summary.determinate_coverage_rate == Decimal("0")
    assert len(result.outcomes) == 5
    assert result.semantic_mapping()["summary"]["blocked_non_actionable_signals"] == 4


def test_btc_macd_values_retained_without_filtering() -> None:
    decision = DEFAULT_STRATEGY_REGISTRY.resolve(SELECTION).evaluate_completed_candle(
        _context()
    )
    assert decision.actionable
    assert "macd_line=0" in decision.reasons
    assert "macd_signal=-1" in decision.reasons
    assert "macd_histogram=1" in decision.reasons

def test_frozen_evidence_label_cannot_be_forged_by_raw_bundle_constructor() -> None:
    from signalforge.research.btc_raw_diagnostic_input import (
        FROZEN_PROVISIONAL_REPORT_SHA256,
    )

    with pytest.raises(ValueError, match="protected evidence audit"):
        RawDiagnosticSource(
            _synthetic_continuous_dataset(),
            FROZEN_PROVISIONAL_REPORT_SHA256,
        )


@pytest.mark.parametrize(
    ("exit_kind", "high", "low"),
    [
        ("stop", "100.25", "99"),
        ("target", "100.80", "100"),
    ],
)
def test_adverse_raw_entry_bar_ambiguous_exit_uses_modeled_sell_fill(
    exit_kind: str, high: str, low: str,
) -> None:
    """Both possible post-entry exits apply frozen raw slippage consistently."""
    dataset = _synthetic_continuous_dataset()
    bars = list(dataset.bars)
    entry_index = 251 * 5
    bars[entry_index] = replace(
        bars[entry_index],
        open=Price(Decimal("100")),
        high=Price(Decimal(high)),
        low=Price(Decimal(low)),
        close=Price(Decimal("100")),
    )
    altered = HistoricalBarDataset(dataset.manifest, tuple(bars))

    class _UnambiguousInvalidationFixture(_SyntheticTrigger):
        """Isolate post-fill ordering from pre-entry signal-low invalidation."""

        def armed_policy(self, signal, setup) -> ArmedPolicyIntent:
            return ArmedPolicyIntent()

    runner = HistoricalBarExecutionRunner(registry=StrategyRegistry((
        StrategyRegistration(
            "btc_momentum_baseline_v0", "0.1.0-experimental",
            lambda _: _UnambiguousInvalidationFixture(BtcMomentumBaselineV0Config()),
        ),
    )))
    reference = _raw_run(altered, runner=runner)
    adverse = _raw_run(
        altered,
        profile=HistoricalExecutionAssumptionProfile.adverse_raw(),
        runner=runner,
    )
    for result, bps in ((reference, Decimal("0")), (adverse, Decimal("10"))):
        outcome = result.outcomes[0]
        assert outcome.certainty is HistoricalOutcomeCertainty.BOUNDED_AMBIGUOUS
        assert outcome.entry_fill is not None
        assert len(outcome.possible_outcomes) == 2
        assert outcome.possible_outcomes[0].terminal_state is HistoricalTerminalState.OPEN_POSSIBLE
        branch = outcome.possible_outcomes[1]
        assert branch.exit_reason.value == exit_kind
        assert branch.realised_r is not None
        assert outcome.stop_price is not None
        assert outcome.raw_target_price is not None
        base = (
            outcome.stop_price.value
            if exit_kind == "stop"
            else outcome.raw_target_price.value
        )
        modeled_exit = base * (Decimal("1") - bps / Decimal("10000"))
        entry = outcome.entry_fill.fill_price.value
        expected_r = (modeled_exit - entry) / (entry - outcome.stop_price.value)
        assert branch.realised_r == expected_r
    assert reference.outcomes[0].possible_outcomes[1].realised_r != (
        adverse.outcomes[0].possible_outcomes[1].realised_r
    )


def test_raw_diagnostic_retains_rejected_candle_macd_trace() -> None:
    """All measured candles retain rejection/MACD evidence, never only fills."""
    dataset = _synthetic_continuous_dataset()
    result = _raw_run(dataset, runner=HistoricalBarExecutionRunner())
    assert result.outcomes == ()
    assert len(result.raw_decision_evidence) == 5
    assert all(not row.actionable for row in result.raw_decision_evidence)
    assert all("rsi_not_met" in row.reasons for row in result.raw_decision_evidence)
    assert all(row.macd_line is not None for row in result.raw_decision_evidence)
    assert all(row.macd_signal is not None for row in result.raw_decision_evidence)
    assert all(row.macd_histogram is not None for row in result.raw_decision_evidence)
    assert result.raw_decision_evidence[0].interval.end > result.measurement_start
    mapping = result.semantic_mapping()
    assert len(mapping["raw_decision_evidence"]) == 5
    assert mapping["raw_decision_evidence"][0]["macd_signal"] is not None
    assert result.result_id == _raw_run(
        dataset, runner=HistoricalBarExecutionRunner()
    ).result_id


def test_raw_trace_identifies_blocked_actionable_decisions() -> None:
    dataset = _synthetic_continuous_dataset()
    result = _raw_run(dataset, runner=_synthetic_runner(251))
    assert result.raw_decision_evidence[0].actionable
    assert not result.raw_decision_evidence[0].blocked_by_active_lifecycle
    assert all(
        not row.actionable for row in result.raw_decision_evidence[1:]
    )


def _sf097_same_bar_both_reachable(*, high: str = "100.20") -> HistoricalBarDataset:
    """Synthetic signal-low invalidation and stop are exactly the same barrier."""
    dataset = _synthetic_continuous_dataset()
    bars = list(dataset.bars)
    index = 251 * 5
    bars[index] = replace(
        bars[index],
        open=Price(Decimal("100")),
        high=Price(Decimal(high)),
        low=Price(Decimal("99.90")),
        close=Price(Decimal("100.10")),
    )
    return HistoricalBarDataset(dataset.manifest, tuple(bars))


@pytest.mark.parametrize(
    "profile",
    (
        HistoricalExecutionAssumptionProfile.reference_raw(),
        HistoricalExecutionAssumptionProfile.adverse_raw(),
    ),
)
def test_sf097_bounded_flat_continuation_preserves_possible_expiry_or_stop(
    profile: HistoricalExecutionAssumptionProfile,
) -> None:
    dataset = _sf097_same_bar_both_reachable()
    original = _raw_run(dataset, profile=profile)
    assert original.terminated_early
    assert HistoricalTerminalState.OPEN_POSSIBLE in {
        item.terminal_state for item in original.outcomes[0].possible_outcomes
    }
    policy = HistoricalContinuationPolicy.BOUNDED_FLAT_V1
    result = _raw_run(dataset, profile=profile, continuation_policy=policy)
    repeat = _raw_run(dataset, profile=profile, continuation_policy=policy)
    assert result == repeat
    assert result.result_id == repeat.result_id
    assert result.result_id != original.result_id
    assert result.simulator_calculation_version == (
        "historical-bar-execution-v2-bounded-flat"
    )
    assert original.simulator_calculation_version == "historical-bar-execution-v1"
    assert not result.terminated_early
    assert len(result.raw_decision_evidence) == 5
    outcome = result.outcomes[0]
    assert outcome.certainty is HistoricalOutcomeCertainty.BOUNDED_AMBIGUOUS
    assert outcome.ambiguity_reasons == (
        HistoricalAmbiguityReason.ENTRY_VS_INVALIDATION,
    )
    assert {item.terminal_state for item in outcome.possible_outcomes} == {
        HistoricalTerminalState.EXPIRED, HistoricalTerminalState.CLOSED,
    }
    assert {item.exit_reason for item in outcome.possible_outcomes} == {
        None, HistoricalExitReason.STOP,
    }
    assert outcome.entry_fill is not None
    assert outcome.stop_price is not None
    assert outcome.entry_fill.fill_price.value > outcome.stop_price.value
    assert outcome.possible_outcomes[1].realised_r is not None
    assert result.summary.total_actionable_opportunities == 1
    assert result.summary.bounded_ambiguous_opportunities == 1
    assert result.summary.determinate_coverage_rate == Decimal("0")
    assert result.execution_valid is False


def test_sf097_reachable_target_remains_a_conditional_closed_branch() -> None:
    dataset = _sf097_same_bar_both_reachable(high="100.40")
    result = _raw_run(
        dataset, continuation_policy=HistoricalContinuationPolicy.BOUNDED_FLAT_V1,
    )
    assert not result.terminated_early
    outcomes = result.outcomes[0].possible_outcomes
    assert len(outcomes) == 3
    assert {o.exit_reason for o in outcomes} == {
        None, HistoricalExitReason.STOP, HistoricalExitReason.TARGET,
    }
    assert all(o.terminal_state is not HistoricalTerminalState.OPEN_POSSIBLE
               for o in outcomes)


def test_sf097_invalidating_above_stop_cannot_claim_flat_convergence() -> None:
    dataset = _synthetic_continuous_dataset()
    bars = list(dataset.bars)
    index = 251 * 5
    bars[index] = replace(
        bars[index],
        open=Price(Decimal("100.05")), high=Price(Decimal("100.20")),
        low=Price(Decimal("100.00")), close=Price(Decimal("100.10")),
    )
    changed = HistoricalBarDataset(dataset.manifest, tuple(bars))

    class _InvalidationAboveStop(_SyntheticTrigger):
        def armed_policy(self, signal, setup) -> ArmedPolicyIntent:
            return ArmedPolicyIntent(
                pre_entry_invalidation=PriceBarrierIntent(
                    price=Price(Decimal("100.01")),
                    direction=PriceBarrierDirection.AT_OR_BELOW,
                    expiry_reason=ExpiryReason.SIGNAL_LOW_BREACH,
                )
            )

    runner = HistoricalBarExecutionRunner(registry=StrategyRegistry((
        StrategyRegistration(
            "btc_momentum_baseline_v0", "0.1.0-experimental",
            lambda _: _InvalidationAboveStop(BtcMomentumBaselineV0Config()),
        ),
    )))
    result = _raw_run(
        changed, runner=runner,
        continuation_policy=HistoricalContinuationPolicy.BOUNDED_FLAT_V1,
    )
    assert result.terminated_early
    assert HistoricalTerminalState.OPEN_POSSIBLE in {
        o.terminal_state for o in result.outcomes[0].possible_outcomes
    }


def test_sf097_continuation_rejects_unversioned_policy() -> None:
    dataset = _synthetic_continuous_dataset()
    with pytest.raises(TypeError, match="explicitly versioned"):
        _raw_run(dataset, continuation_policy="bounded_flat_v1")
