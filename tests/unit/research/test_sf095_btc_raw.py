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
from signalforge.domain.armed import ArmedSetupState
from signalforge.domain.ids import InstrumentId, SignalId
from signalforge.domain.indicators import IndicatorSnapshot
from signalforge.domain.market import CandleQuality, CompletedCandle
from signalforge.domain.money import Price
from signalforge.domain.time import CandleInterval
from signalforge.research.historical_bars import (
    HistoricalBarDataset,
    HistoricalPriceBasis,
    load_historical_bar_fixture,
)
from signalforge.research.historical_execution import (
    CONTINUOUS_HISTORICAL_SESSION_POLICY,
    HistoricalAmbiguityReason,
    HistoricalBarExecutionRunner,
    HistoricalExecutionAssumptionProfile,
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
    ArmedSetupView,
    CompletedCandleStrategyContext,
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
        source_diagnostic_id="synthetic-only-test-source",
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
            source_diagnostic_id="test-evidence",
            measurement_start=dataset.manifest.requested_start + timedelta(minutes=250 * 5),
        )
    with pytest.raises(ValueError, match="source diagnostic"):
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


def _raw_run(dataset, *, profile=None, runner=None, measurement_start=None):
    return (runner or _synthetic_runner(251)).run(
        dataset,
        strategy_selection=SELECTION,
        engine_calculation_version="engine-v1",
        tick_schedule=None,
        execution_profile=profile or HistoricalExecutionAssumptionProfile.reference_raw(),
        market_session_policy=CONTINUOUS_HISTORICAL_SESSION_POLICY,
        source_diagnostic_id="synthetic-only-test-source",
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
    assert result.terminated_early
    assert result.outcomes[0].certainty is HistoricalOutcomeCertainty.BOUNDED_AMBIGUOUS
    assert HistoricalAmbiguityReason.STOP_VS_TARGET in (
        result.outcomes[0].ambiguity_reasons
    )
    assert result.execution_valid is False


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
