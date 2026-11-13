"""SF-258 synthetic-only scenario engine and strict-lane isolation checks."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from signalforge.config.btc_momentum_baseline_v0 import BtcMomentumBaselineV0Config
from signalforge.config.strategy_registry import (
    StrategyRegistration,
    StrategyRegistry,
    StrategySelection,
)
from signalforge.domain.armed import ExpiryReason
from signalforge.domain.ids import InstrumentId
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
    HistoricalBarExecutionRunner,
    HistoricalContinuationPolicy,
    HistoricalExecutionAssumptionProfile,
    HistoricalTerminalState,
)
from signalforge.research.historical_grid import HistoricalBarGrid
from signalforge.research.scenario_execution import (
    ScenarioAssumptionSet,
    ScenarioMethodStatus,
    ScenarioMode,
    ScenarioResearchRequest,
    ScenarioResearchRunner,
    ScenarioResourcePolicy,
    VersionedRule,
    _step,
    _Work,
)
from signalforge.runtime.btc_momentum_baseline_v0 import (
    BtcMomentumBaselineDecision,
    BtcMomentumBaselineV0Strategy,
)
from signalforge.runtime.strategy import (
    ArmedPolicyIntent,
    ArmedSetupView,
    CompletedCandleStrategyContext,
    PositionEconomics,
    PriceBarrierDirection,
    PriceBarrierIntent,
    StrategyEntryFillView,
)

BTC = InstrumentId("DELTA:BTCUSD")
SEL = StrategySelection("btc_momentum_baseline_v0", "0.1.0-experimental", {})
EXAMPLE = Path(__file__).resolve().parents[3] / (
    "examples/research/historical-bars-one-session.json"
)
START = datetime(2026, 11, 1, 2, 55, tzinfo=UTC)
MINUTES = 260 * 5


class _SignalAt(BtcMomentumBaselineV0Strategy):
    """Test-only signal timing; all entry and post-fill policy remains strategy-owned."""

    def __init__(self, counts: tuple[int, ...]) -> None:
        super().__init__(BtcMomentumBaselineV0Config())
        self.counts = counts

    def evaluate_completed_candle(
        self, context: CompletedCandleStrategyContext,
    ) -> BtcMomentumBaselineDecision:
        actionable = context.completed_regular_session_candles in self.counts
        return BtcMomentumBaselineDecision(
            context.candle.instrument_id, context.candle.interval,
            actionable, actionable,
            ("synthetic_signal",) if actionable else ("synthetic_no_signal",),
            None,
        )


def _source(*, overrides: dict[int, tuple[str, str, str, str]] | None = None
            ) -> RawDiagnosticSource:
    legacy = load_historical_bar_fixture(EXAMPLE)
    original = legacy.bars[0]
    prices = overrides or {}
    bars = []
    for offset in range(MINUTES):
        at = START + timedelta(minutes=offset)
        o, h, low, c = prices.get(offset, ("100", "100.05", "99.95", "100"))
        bars.append(replace(
            original, instrument_id=BTC,
            interval=CandleInterval(at, at + timedelta(minutes=1)),
            open=Price(Decimal(o)), high=Price(Decimal(h)),
            low=Price(Decimal(low)), close=Price(Decimal(c)),
            provider_timestamp_raw=at.isoformat(), provider_timestamp_interpreted=at,
        ))
    manifest = replace(
        legacy.manifest, instrument_id=BTC,
        requested_instrument="BTCUSD", resolved_provider_instrument="BTCUSD",
        expected_session_dates=(),
        price_basis=HistoricalPriceBasis.TRADED,
        limitations=("UNQUALIFIED_HISTORICAL_METADATA", "SYNTHETIC_TEST_ONLY"),
        grid=HistoricalBarGrid(
            "scenario-synthetic", "1",
            (CandleInterval(START, START + timedelta(minutes=MINUTES)),),
        ),
        requested_start=START, requested_end=START + timedelta(minutes=MINUTES),
        returned_start=START, returned_end=START + timedelta(minutes=MINUTES),
        raw_row_count=MINUTES, canonical_row_count=MINUTES,
        missing_interval_count=0, duplicate_observation_count=0,
        corrupt_rejected_count=0,
    )
    return RawDiagnosticSource(
        HistoricalBarDataset(manifest, tuple(bars)), "synthetic-sf258",
    )


def _request(source: RawDiagnosticSource, *,
             profile: HistoricalExecutionAssumptionProfile | None = None,
             budgets: ScenarioResourcePolicy | None = None,
             fixture_identity: str = "synthetic-default-shape") -> ScenarioResearchRequest:
    return ScenarioResearchRequest(
        mode=ScenarioMode.SCENARIO_RESEARCH, source=source,
        strategy_selection=SEL, engine_calculation_version="synthetic-engine-v1",
        assumptions=ScenarioAssumptionSet.btc_ohlc_path_v1(),
        profile=profile or HistoricalExecutionAssumptionProfile.reference_raw(),
        resources=budgets or ScenarioResourcePolicy(
            "FINITE_FAIL_CLOSED", "1.0.0", 100, 1000, 1000, 1000, 1,
        ),
        is_start=START + timedelta(minutes=1250),
        oos_start=START + timedelta(minutes=1255),
        measured_end=START + timedelta(minutes=MINUTES),
        repository_revision="synthetic-test-code",
        synthetic_fixture_identity=fixture_identity,
    )


def _runner(*signals: int) -> ScenarioResearchRunner:
    registry = StrategyRegistry((
        StrategyRegistration(SEL.strategy_id, SEL.strategy_version,
                             lambda params: _SignalAt(tuple(signals))),
    ))
    return ScenarioResearchRunner(registry=registry)


def test_assumptions_explicit_versioned_and_unknown_rejected():
    assumptions = ScenarioAssumptionSet.btc_ohlc_path_v1()
    assert len(assumptions.semantic_hash) == 64
    assert len([assumptions.mapping()[k] for k in (
        "price_path_rule", "event_tie_policy", "gap_policy",
        "time_boundary_policy", "fill_application_policy",
    )]) == 5
    with pytest.raises(ValueError, match="Unknown or contradictory"):
        replace(assumptions, event_tie_policy=VersionedRule(
            "REJECT_SAME_LEVEL_TIE_V1", "2.0.0",
        ))
    with pytest.raises(ValueError, match="finite"):
        ScenarioResourcePolicy("FINITE_FAIL_CLOSED", "1.0.0", 0, 100, 100, 100, 1)
    with pytest.raises(ValueError, match="max_states=1"):
        ScenarioResourcePolicy("FINITE_FAIL_CLOSED", "1.0.0", 100, 100, 100, 100, 2)
    with pytest.raises(ValueError, match="SCENARIO_RESEARCH"):
        replace(_request(_source()), mode="RAW_DIAGNOSTIC")


def test_replay_identity_and_budget_sensitive_run_id(tmp_path: Path):
    source = _source()
    req = _request(source)
    first = _runner(251).run(req)
    second = _runner(251).run(req)
    assert first.mapping() == second.mapping()
    assert first.result_id == second.result_id
    assert first.manifest.run_id == second.manifest.run_id
    assert first.execution_valid is False
    assert first.point_metrics_allowed is False
    assert first.method_status is ScenarioMethodStatus.INCONCLUSIVE
    smaller = replace(req, resources=replace(req.resources, max_bars=101))
    assert _runner(251).run(smaller).manifest.run_id != first.manifest.run_id
    out = tmp_path / "scenario.json"
    first.write_new(out)
    original = out.read_bytes()
    with pytest.raises(FileExistsError):
        first.write_new(out)
    assert out.read_bytes() == original
    assert b"SCENARIO_CONDITIONED" in original


@pytest.mark.parametrize("profile", [
    HistoricalExecutionAssumptionProfile.reference_raw(),
    HistoricalExecutionAssumptionProfile.adverse_raw(),
])
def test_entry_target_stop_assumed_order_and_raw_profile(profile):
    # Signal at count=251 (minute 1254). Next minute rising first reaches
    # trigger, then target, then low. Both reachability orders are assumptions.
    prices = {1255: ("100", "105", "98", "100")}
    result = _runner(251).run(_request(_source(overrides=prices), profile=profile))
    closed = [x for x in result.outcomes if x.state == "CLOSED"]
    assert len(closed) == 1
    assert closed[0].reason == "TARGET"
    assert closed[0].holding_span_1m_buckets == 1
    assert closed[0].r is not None and closed[0].r > 0
    assert any(x.action == "ENTRY" and x.assumed for x in result.trace)
    assert any(x.action == "TARGET" and x.assumed for x in result.trace)
    assert result.execution_valid is False


def test_expiry_before_new_signal_and_no_retroactive_bar_reuse():
    # First setup stays unfilled through all five following minutes.
    # Fresh signal at completed 5m boundary arms after old expiry; only
    # minute 1260 (not 1259) can trigger the new setup.
    prices = {i: ("100", "100.05", "100", "100") for i in range(1255, 1260)}
    prices[1260] = ("100.2", "100.4", "100.1", "100.2")
    result = _runner(251, 252).run(_request(_source(overrides=prices)))
    assert any(x.state == "EXPIRED" and x.reason == "VALIDITY_WINDOW_END"
               for x in result.outcomes)
    assert any(x.entry_bucket == START + timedelta(minutes=1260)
               for x in result.outcomes)
    assert all(x.entry_bucket != START + timedelta(minutes=1259)
               for x in result.outcomes)


def test_open_blocks_next_signal_and_persists_at_dataset_end():
    prices = {i: ("100.2", "100.21", "100.1", "100.2")
              for i in range(1255, MINUTES)}
    result = _runner(251, 252).run(_request(_source(overrides=prices)))
    assert len(result.outcomes) == 1
    assert result.outcomes[0].state == "OPEN"
    assert result.outcomes[0].exit_bucket is None


def test_preentry_invalidation_before_entry_on_declared_path():
    # Gap at the observed open invalidates before later hypothetical high.
    prices = {1255: ("98", "101", "97.9", "100")}
    result = _runner(251).run(_request(_source(overrides=prices)))
    assert any(x.state == "EXPIRED" and x.reason == "PRE_ENTRY_INVALIDATION"
               for x in result.outcomes)
    assert all(x.entry_price is None for x in result.outcomes)


def test_budgets_fail_closed_and_cannot_publish_partial_economics():
    prices = {1255: ("100", "105", "98", "100")}
    req = _request(_source(overrides=prices))
    limited = replace(req, resources=replace(req.resources, max_events=1))
    result = _runner(251).run(limited)
    assert result.failure is not None and "BUDGET_EXHAUSTED" in result.failure
    assert result.outcomes == ()
    assert result.trace == ()
    assert result.point_metrics_allowed is False
    assert result.failure_bucket is not None


def test_strict_runner_namespace_and_default_unchanged():
    source = _source()
    req = _request(source)
    scenario = _runner(251).run(req)
    strict = HistoricalBarExecutionRunner().run(
        source.dataset, strategy_selection=SEL,
        engine_calculation_version="synthetic-engine-v1", tick_schedule=None,
        execution_profile=HistoricalExecutionAssumptionProfile.reference_raw(),
        market_session_policy=CONTINUOUS_HISTORICAL_SESSION_POLICY,
        raw_source=source, measurement_start=req.is_start,
    )
    assert strict.execution_valid is False
    assert strict.simulator_calculation_version != (
        scenario.manifest.mapping()["mode_and_schema"]["simulator"]
    )
    assert strict.result_id != scenario.result_id

class _EarlyCutoff(_SignalAt):
    """Test-only strategy shape with a known early entry cutoff."""

    def armed_policy(self, signal, setup: ArmedSetupView) -> ArmedPolicyIntent:
        del signal
        return ArmedPolicyIntent(
            strategy_entry_cutoff_at=setup.armed_at + timedelta(minutes=2),
        )


class _ExtendedTarget(_SignalAt):
    """Test-only alternative post-fill economics, never a BTC production rule."""

    def post_fill_economics(
        self, fill: StrategyEntryFillView, setup: ArmedSetupView
    ) -> PositionEconomics:
        return PositionEconomics(
            stop_price=setup.stop_price,
            raw_target_price=Price(
                fill.fill_price.value
                + Decimal("3") * (fill.fill_price.value - setup.stop_price.value)
            ),
        )


def test_three_distinct_strategy_shapes_reuse_scenario_contract():
    """ADR-008: BTC, cutoff and independent economics share generic state mechanics."""
    source = _source(overrides={1255: ("100", "100.4", "99.9", "100")})
    request = _request(source)
    baseline = _runner(251).run(replace(
        request, synthetic_fixture_identity="synthetic-btc-baseline-251",
    ))
    early = ScenarioResearchRunner(registry=StrategyRegistry((
        StrategyRegistration(
            SEL.strategy_id, SEL.strategy_version,
            lambda params: _EarlyCutoff((251,)),
        ),
    ))).run(replace(
        request, synthetic_fixture_identity="synthetic-early-cutoff-251",
    ))
    extended = ScenarioResearchRunner(registry=StrategyRegistry((
        StrategyRegistration(
            SEL.strategy_id, SEL.strategy_version,
            lambda params: _ExtendedTarget((251,)),
        ),
    ))).run(replace(
        request, synthetic_fixture_identity="synthetic-extended-target-251",
    ))
    assert len({
        baseline.manifest.run_id, early.manifest.run_id, extended.manifest.run_id,
    }) == 3
    assert any(o.reason == "TARGET" for o in baseline.outcomes)
    assert any(o.reason == "TARGET" for o in extended.outcomes) is False
    assert early.execution_valid is False
    assert all(o.mapping()["certainty"] == "SCENARIO_CONDITIONED"
               for o in baseline.outcomes + extended.outcomes)


def test_armed_time_cutoff_at_minute_boundary_is_determinate():
    source = _source(overrides={
        1255: ("100", "100", "100", "100"),
        1256: ("100", "100", "100", "100"),
        1257: ("100", "101", "99.5", "100"),
    })
    registry = StrategyRegistry((
        StrategyRegistration(SEL.strategy_id, SEL.strategy_version,
                             lambda params: _EarlyCutoff((251,))),
    ))
    result = ScenarioResearchRunner(registry=registry).run(_request(source))
    assert any(x.reason == "STRATEGY_CUTOFF" for x in result.outcomes)
    assert all(x.entry_price is None for x in result.outcomes)


def test_terminal_resource_budget_never_exposes_partial_economics():
    # Exactly one completed expiry at dataset end must be counted before publication.
    source = _source()
    request = _request(source, budgets=ScenarioResourcePolicy(
        "FINITE_FAIL_CLOSED", "1.0.0", 100, 1000, 1, 1000, 1,
    ))
    first = _runner(259, 260).run(request)
    assert first.failure is not None and first.failure.startswith("BUDGET_EXHAUSTED")
    assert first.outcomes == ()
    assert first.trace == ()
    assert first.failure_bucket is not None


def test_source_and_mode_negative_gates():
    source = _source()
    request = _request(source)
    with pytest.raises(ValueError, match="frozen BTC baseline"):
        replace(request, strategy_selection=StrategySelection(
            "intraday_momentum_v1", "1.0.0", {},
        ))
    with pytest.raises(ValueError, match="RAW"):
        replace(request, profile=HistoricalExecutionAssumptionProfile.zero())
    with pytest.raises(ValueError, match="Unaudited raw source"):
        replace(source, source_diagnostic_id="unverified")


def test_verified_replay_keeps_synthetic_study_inconclusive():
    result = _runner(251).run_verified(_request(_source()))
    assert result.replay_verified is True
    assert result.method_status is ScenarioMethodStatus.INCONCLUSIVE
    assert result.point_metrics_allowed is False

class _MidMinuteCutoff(_SignalAt):
    """Synthetic policy shape with intentionally unorderable minute cutoff."""

    def armed_policy(self, signal, setup: ArmedSetupView) -> ArmedPolicyIntent:
        del signal
        return ArmedPolicyIntent(
            strategy_entry_cutoff_at=setup.armed_at + timedelta(seconds=90),
        )


def test_post_fill_stop_and_observed_open_gap_stop_use_selected_sell_profile():
    entry_and_stop = _source(overrides={
        1255: ("100", "100.2", "99.9", "100"),
    })
    ordinary = _runner(251).run(_request(entry_and_stop))
    stops = [out for out in ordinary.outcomes if out.reason == "STOP"]
    assert len(stops) == 1
    assert stops[0].holding_span_1m_buckets == 1
    assert stops[0].r is not None and stops[0].r < 0

    entry_then_gap = _source(overrides={
        1255: ("100.2", "100.21", "100.1", "100.2"),
        1256: ("99.8", "100.3", "99.7", "100"),
    })
    adverse = _runner(251).run(_request(
        entry_then_gap, profile=HistoricalExecutionAssumptionProfile.adverse_raw(),
    ))
    gap_stop = [out for out in adverse.outcomes if out.reason == "STOP"]
    assert len(gap_stop) == 1
    assert gap_stop[0].exit_price == Decimal("99.7002")
    assert gap_stop[0].holding_span_1m_buckets == 2
    assert all(out.mapping()["certainty"] == "SCENARIO_CONDITIONED"
               for out in gap_stop)


def test_unorderable_inminute_cutoff_fails_closed_without_point_economics():
    source = _source()
    registry = StrategyRegistry((
        StrategyRegistration(
            SEL.strategy_id, SEL.strategy_version,
            lambda params: _MidMinuteCutoff((251,)),
        ),
    ))
    result = ScenarioResearchRunner(registry=registry).run(_request(source))
    assert result.failure is not None
    assert result.failure.startswith("SCENARIO_UNSUPPORTED")
    assert result.unsupported == 1
    assert result.outcomes == ()
    assert result.trace == ()
    assert result.failure_bucket == START + timedelta(minutes=1256)


def test_missing_source_and_invalid_ohlc_fail_closed():
    source = _source()
    with pytest.raises(ValueError, match="high must be at least"):
        replace(source.dataset.bars[0], high=Price(Decimal("90")))
    bars = source.dataset.bars[:1255] + source.dataset.bars[1256:]
    manifest = replace(
        source.dataset.manifest, raw_row_count=MINUTES - 1,
        canonical_row_count=MINUTES - 1, missing_interval_count=1,
    )
    corrupt = RawDiagnosticSource(
        HistoricalBarDataset(manifest, bars), "synthetic-sf258-missing",
    )
    result = _runner(251).run(_request(corrupt))
    assert result.failure is not None and result.failure.startswith("SOURCE_INVALID")
    assert result.method_status is ScenarioMethodStatus.INVALID
    assert not result.point_metrics_allowed


def test_dataset_end_armed_and_cross_midnight_open_are_conditional():
    source = _source(overrides={
        i: ("100.2", "100.21", "100.1", "100.2")
        for i in range(1255, MINUTES)
    })
    open_result = _runner(251).run(_request(source))
    final_open = [o for o in open_result.outcomes if o.state == "OPEN"]
    assert len(final_open) == 1
    assert final_open[0].entry_bucket is not None
    assert final_open[0].entry_bucket.date() != source.dataset.bars[-1].interval.start.date()
    assert final_open[0].exit_bucket is None

    armed_result = _runner(260).run(_request(_source()))
    assert [o.state for o in armed_result.outcomes] == ["ARMED"]
    assert armed_result.outcomes[0].entry_bucket is None
    assert armed_result.point_metrics_allowed is False


def test_outcome_limit_accepts_exact_capacity_and_rejects_next_outcome():
    """A full capacity is allowed; only an additional outcome exhausts the run."""
    prices = {
        1255: ("100", "105", "98", "100"),
        1260: ("100", "105", "98", "100"),
    }
    source = _source(overrides=prices)
    request = _request(source, budgets=ScenarioResourcePolicy(
        "FINITE_FAIL_CLOSED", "1.0.0", 100, 1000, 1, 1000, 1,
    ))
    at_capacity = _runner(251).run(request)
    assert at_capacity.failure is None
    assert len(at_capacity.outcomes) == 1
    assert at_capacity.outcomes[0].state == "CLOSED"
    assert at_capacity.attempted_outcome_count == 1
    assert at_capacity.point_metrics_allowed is False

    overflow = _runner(251, 252).run(request)
    assert overflow.failure is not None
    assert overflow.failure.startswith("BUDGET_EXHAUSTED")
    assert overflow.outcomes == ()
    assert overflow.trace == ()
    assert overflow.attempted_outcome_count == 2
    assert overflow.failure_bucket == START + timedelta(minutes=1260)


@pytest.mark.parametrize("entered", [False, True])
def test_failure_retains_active_opportunity_and_last_complete_source(entered):
    """No partial economics, but a failed active state remains reproducible."""
    prices = {
        i: (("100.2", "100.21", "100.1", "100.2") if entered
            else ("100", "100.05", "100", "100"))
        for i in range(1255, MINUTES)
    }
    source = _source(overrides=prices)
    request = _request(source, budgets=ScenarioResourcePolicy(
        "FINITE_FAIL_CLOSED", "1.0.0", 8, 1000, 1000, 1000, 1,
    ))
    first = _runner(251).run(request)
    second = _runner(251).run(request)
    assert first.failure is not None and first.failure.startswith("BUDGET_EXHAUSTED")
    assert first.outcomes == ()
    assert first.trace == ()
    assert first.blocked_decisions == ()
    assert first.failure_opportunity_id
    assert first.failure_signal_interval_start == START + timedelta(minutes=1250)
    assert first.last_complete_bucket == START + timedelta(minutes=1257)
    assert first.failure_bucket == START + timedelta(minutes=1258)
    assert first.terminal_active_state == ("OPEN" if entered else "ARMED")
    assert first.mapping() == second.mapping()
    assert first.result_id == second.result_id


def test_blocked_completed_candle_decisions_are_separately_auditable():
    """A blocked signal neither disappears nor arms a competing setup."""
    prices = {
        i: ("100.2", "100.21", "100.1", "100.2")
        for i in range(1255, MINUTES)
    }
    result = _runner(251, 252).run(_request(_source(overrides=prices)))
    assert result.failure is None
    assert len(result.outcomes) == 1
    assert result.outcomes[0].state == "OPEN"
    assert result.blocked_actionable_count == 1
    assert len(result.blocked_decisions) == 1
    blocked = result.blocked_decisions[0]
    assert blocked.interval_start == START + timedelta(minutes=1255)
    assert blocked.interval_end == START + timedelta(minutes=1260)
    assert blocked.blocking_state == "OPEN"
    assert blocked.blocking_opportunity_id == result.outcomes[0].opportunity_id
    assert result.mapping()["blocked_decisions"] == [blocked.mapping()]
    assert result.execution_valid is False
def test_scenario_output_refuses_protected_data_root_and_symlink(tmp_path: Path):
    """Neither direct nor resolved aliases may write into SF-088 evidence trees."""
    result = _runner(251).run(_request(_source()))
    protected = tmp_path / ".signalforge-data" / "evidence"
    protected.mkdir(parents=True)
    with pytest.raises(ValueError, match="protected evidence trees"):
        result.write_new(protected / "scenario.json")
    assert not (protected / "scenario.json").exists()

    alias = tmp_path / "evidence-alias"
    alias.symlink_to(protected, target_is_directory=True)
    with pytest.raises(ValueError, match="protected evidence trees"):
        result.write_new(alias / "scenario.json")
    assert not (protected / "scenario.json").exists()

    ordinary = tmp_path / "permitted-scenario.json"
    result.write_new(ordinary)
    assert ordinary.is_file()


def test_protected_style_bars_cannot_become_synthetic_by_relabeling():
    """Construct a metadata-only Delta analogue; never load protected archives."""
    source = _source()
    protected_manifest = replace(
        source.dataset.manifest,
        provider="delta_exchange_india",
        acquisition_adapter="sf095-protected-first-pass-read-only",
        limitations=("UNQUALIFIED_HISTORICAL_METADATA",),
    )
    provider_bars = tuple(
        replace(bar, source_provider="delta_exchange_india")
        for bar in source.dataset.bars
    )
    disguised = RawDiagnosticSource(
        HistoricalBarDataset(protected_manifest, provider_bars),
        "synthetic-masquerading-as-protected",
    )
    # The raw-source wrapper permits this diagnostic prefix; the scenario
    # request must independently check actual fixture provenance fields.
    with pytest.raises(ValueError, match="test-only fixture source provenance"):
        _request(disguised)

    unmarked = RawDiagnosticSource(
        replace(source.dataset, manifest=replace(
            source.dataset.manifest,
            limitations=("UNQUALIFIED_HISTORICAL_METADATA",),
        )),
        "synthetic-without-test-marker",
    )
    with pytest.raises(ValueError, match="test-only fixture source provenance"):
        _request(unmarked)


def test_strict_expiry_order_discrepancy_isolated_from_scenario_boundary():
    """Strict blocks a fresh 5m decision before expiring the old setup; scenario does not."""
    prices = {i: ("100", "100.05", "100", "100") for i in range(1255, 1260)}
    prices[1260] = ("100.2", "100.4", "100.1", "100.2")
    source = _source(overrides=prices)
    request = _request(source)
    registry = StrategyRegistry((
        StrategyRegistration(
            SEL.strategy_id, SEL.strategy_version,
            lambda params: _SignalAt((251, 252)),
        ),
    ))
    scenario = ScenarioResearchRunner(registry=registry).run(request)
    strict = HistoricalBarExecutionRunner(registry=registry).run(
        source.dataset, strategy_selection=SEL,
        engine_calculation_version=request.engine_calculation_version,
        tick_schedule=None,
        execution_profile=request.profile,
        market_session_policy=CONTINUOUS_HISTORICAL_SESSION_POLICY,
        raw_source=source,
        measurement_start=request.is_start,
        continuation_policy=HistoricalContinuationPolicy.FAIL_CLOSED_V1,
    )
    new_signal_end = START + timedelta(minutes=1260)
    assert scenario.failure is None
    assert any(x.entry_bucket == new_signal_end for x in scenario.outcomes)
    assert any(
        x.terminal_state is HistoricalTerminalState.BLOCKED
        and x.signal_interval.end == new_signal_end
        for x in strict.outcomes
    )
    assert all(
        not (x.entry_fill is not None and x.signal_interval.end == new_signal_end)
        for x in strict.outcomes
    )
    assert strict.execution_valid is False
    assert scenario.execution_valid is False


def test_order_changing_equal_level_tie_fails_closed_defensively():
    """Valid long policies prohibit equal barriers; a malformed private state cannot choose."""
    bar = _source().dataset.bars[1255]
    price = Price(Decimal("100"))
    # This bypasses accepted arming validation solely to pressure-test the
    # hypothetical first-crossing helper's defensive tie branch.
    invalidation = PriceBarrierIntent(
        price, PriceBarrierDirection.AT_OR_BELOW,
        ExpiryReason.SIGNAL_LOW_BREACH,
    )
    active = SimpleNamespace(
        entry_price=None,
        view=SimpleNamespace(tradable_trigger=price),
        policy=SimpleNamespace(pre_entry_invalidation=invalidation),
    )
    work = _Work(active, [], [], [])
    _step(
        work, _SignalAt((251,)),
        HistoricalExecutionAssumptionProfile.reference_raw(),
        bar, price.value, price.value, opening=True,
    )
    assert work.unsupported == 1
    assert work.failure == "SCENARIO_UNSUPPORTED: order-changing same-level tie"
    assert work.failure_bucket == bar.interval.start
    assert work.outcomes == []
    assert work.trace == []


@pytest.mark.parametrize("case", ["open", "closed", "armed", "expired", "rejected"])
@pytest.mark.parametrize("profile", [
    HistoricalExecutionAssumptionProfile.reference_raw(),
    HistoricalExecutionAssumptionProfile.adverse_raw(),
])
def test_released_validator_uses_frozen_runner_lifecycle_semantics(case, profile, monkeypatch):
    """Feed genuine frozen-runner mappings from fabricated source into SF-278.

    Dates overlap the registered split solely to exercise boundary checks. The
    source and strategy remain conspicuously synthetic, with only 1,300 fabricated
    minutes; these tests cannot establish real-artifact compatibility/full coverage.
    """
    from signalforge.research.stage6_validation import SPLIT, validate_result

    monkeypatch.setitem(globals(), "START", datetime(2026, 6, 30, 2, 55, tzinfo=UTC))
    prices = {}
    signals = (260,) if case == "armed" else (251, 252, 253)
    if case in ("open", "closed", "rejected"):
        prices = {i: ("100.2", "100.21", "100.1", "100.2") for i in range(1255, MINUTES)}
    if case == "closed":
        prices[1266] = ("100.2", "105", "100.1", "100.2")
    if case == "expired":
        prices = {i: ("100", "100.05", "100", "100") for i in range(1255, 1260)}
        signals = (251,)
    source = _source(overrides=prices)
    request = replace(_request(source, profile=profile), oos_start=SPLIT)
    runner = _runner(*signals)
    if case == "rejected":
        class RejectSyntheticEntry(_SignalAt):
            def post_fill_economics(self, fill, setup):
                return PositionEconomics(fill.fill_price, None)
        runner = ScenarioResearchRunner(registry=StrategyRegistry((
            StrategyRegistration(SEL.strategy_id, SEL.strategy_version,
                                 lambda params: RejectSyntheticEntry((251,))),
        )))
    result = runner.run_verified(request)
    assert result.failure is None
    states = [outcome.state for outcome in result.outcomes]
    assert {"open": "OPEN", "closed": "CLOSED", "armed": "ARMED",
            "expired": "EXPIRED", "rejected": "REJECTED"}[case] in states
    if case in ("open", "closed"):
        first = result.outcomes[0]
        assert first.entry_bucket < SPLIT
        assert first.exit_bucket is None or first.exit_bucket >= SPLIT
        assert result.blocked_actionable_count > 0
    report = validate_result(result.mapping())
    assert report["checks"]["SAVED_LIFECYCLE_CONSISTENCY"] == "PASS"
    assert report["status"] == "INCONCLUSIVE"
    assert report["point_metrics_allowed"] is False


# SF-283: prospective v2 saved-byte reconstruction; v1 semantics remain frozen.
from signalforge.config.identity import config_hash  # noqa: E402
from signalforge.research.scenario_report_evidence import (  # noqa: E402
    write_source_quality_evidence,
    write_strict_reference_evidence,
)
from signalforge.research.scenario_reportability import (  # noqa: E402
    ReportabilityError,
    report_from_saved_bytes,
)


def _sf283_roundtrip(
    tmp_path: Path, *, signals: tuple[int, ...] = (251,),
    prices: dict[int, tuple[str, str, str, str]] | None = None,
    split_minute: int = 1260,
    profile: HistoricalExecutionAssumptionProfile | None = None,
    runner: ScenarioResearchRunner | None = None,
    ambiguous_minutes: tuple[int, ...] = (),
):
    """Actual synthetic runner -> canonical bytes -> detached saved-only report."""
    source = _source(overrides=prices)
    request = replace(
        _request(source, profile=profile),
        oos_start=START + timedelta(minutes=split_minute),
    )
    result = (runner or _runner(*signals)).run_verified(request)
    src = tmp_path / "source-quality.json"
    strict = tmp_path / "strict-reference.json"
    target = tmp_path / "result-v2.json"
    write_source_quality_evidence(request, result, src)
    assessed = tuple(
        request.is_start + timedelta(minutes=n)
        for n in range(int((request.measured_end - request.is_start) / timedelta(minutes=1)))
    )
    ambiguous = tuple(START + timedelta(minutes=n) for n in ambiguous_minutes)
    write_strict_reference_evidence(
        result, request, strict,
        assessed_intervals=assessed, ambiguous_intervals=ambiguous,
        producer_id="synthetic-independent-strict-diagnostic-v1",
    )
    result.write_reportable_new(target, source_companion=src, strict_companion=strict)
    # Reporting has no access to source, request or runner objects.
    report = report_from_saved_bytes(target.read_bytes(), src.read_bytes(), strict.read_bytes())
    return result, report, target, src, strict


def test_sf283_s01_full_grid_and_s15_saved_byte_report(tmp_path):
    result, report, target, src, strict = _sf283_roundtrip(tmp_path, signals=())
    assert report["status"] == "COMPLETE_PERSISTED_REPORTABILITY"
    assert report["execution_valid"] is False
    assert report["certainty"] == "SCENARIO_CONDITIONED"
    assert report["windows"]["IS"]["economics"]["expected_completed_5m_decisions"] == 2
    assert report["windows"]["OOS"]["economics"]["expected_completed_5m_decisions"] == 8
    assert report["closed_cohort_reconciliation"]["total_closed"] == 0
    assert result.result_id == config_hash({
        "domain": "scenario-result-v1", "result": result.mapping(),
    })
    assert report_from_saved_bytes(
        target.read_bytes(), src.read_bytes(), strict.read_bytes(),
    ) == report
    with pytest.raises(FileExistsError):
        result.write_reportable_new(target, source_companion=src, strict_companion=strict)


def test_sf283_s02_is_contained(tmp_path):
    prices = {1255: ("100", "105", "98", "100")}
    _, report, *_ = _sf283_roundtrip(tmp_path, prices=prices)
    assert report["closed_cohort_reconciliation"]["IS_CONTAINED"] == 1
    assert report["closed_cohort_reconciliation"]["OOS_CONTAINED"] == 0
    is_window = report["windows"]["IS"]
    economics = is_window["economics"]
    assert economics["closed_contained"] == 1
    # Independently derived oracle from synthetic strategy: trigger=100.1,
    # stop=99.95, target=100.325, so modeled gross R=1.5.
    assert economics["wins"] == 1
    assert economics["win_rate"]["value"] == "1"
    assert Decimal(economics["average_r_expectancy"]["value"]) == Decimal("1.5")
    assert Decimal(economics["sum_gross_r"]) == Decimal("1.5")
    assert economics["frequency_per_1000_expected_5m_decisions"]["value"] == "500"
    assert economics["holding_span_1m_buckets_sorted"] == [1]
    assert economics["exit_reason_counts"] == {"TARGET": 1}
    assert economics["maximum_cumulative_r_drawdown"]["value"] == "0"
    assert is_window["source_quality"]["expected_intervals"] == 10
    assert is_window["source_quality"]["primary_disposition_counts"]["VALID"] == 10
    assert is_window["strict_reference"]["eligible_intervals"] == 10


def test_sf283_s03_oos_contained(tmp_path):
    prices = {1265: ("100", "105", "98", "100")}
    _, report, *_ = _sf283_roundtrip(tmp_path, prices=prices, signals=(253,))
    assert report["closed_cohort_reconciliation"]["OOS_CONTAINED"] == 1


def test_sf283_s04_split_signal_and_cross_window(tmp_path):
    prices = {1255: ("100", "105", "98", "100")}
    _, report, *_ = _sf283_roundtrip(tmp_path, prices=prices, split_minute=1255)
    counts = report["closed_cohort_reconciliation"]
    assert counts["CROSS_WINDOW"] == 1
    assert counts["IS_CONTAINED"] == 0 and counts["OOS_CONTAINED"] == 0
    assert report["windows"]["IS"]["actionable_accepted_signals"] == 1
    assert report["windows"]["OOS"]["accepted_entry_events"] == 1


def test_sf283_s05_rejected_and_attempt_boundary(tmp_path):
    class RejectSyntheticEntry(_SignalAt):
        def post_fill_economics(self, fill, setup):
            return PositionEconomics(fill.fill_price, None)

    registry = StrategyRegistry((
        StrategyRegistration(SEL.strategy_id, SEL.strategy_version,
                             lambda params: RejectSyntheticEntry((251,))),
    ))
    runner = ScenarioResearchRunner(registry=registry)
    result, report, *_ = _sf283_roundtrip(
        tmp_path, runner=runner, prices={1255: ("100", "105", "98", "100")},
    )
    assert result.outcomes[0].state == "REJECTED"
    assert result.outcomes[0].attempted_entry_bucket is not None
    assert report["windows"]["IS"]["lifecycle_by_signal_window"]["REJECTED"] == 1
    assert report["closed_cohort_reconciliation"]["total_closed"] == 0


@pytest.mark.parametrize("prices,expected", [
    ({1255: ("98", "101", "97.9", "100")}, "PRE_ENTRY_INVALIDATION"),
    ({i: ("100", "100.05", "100", "100") for i in range(1255, 1260)},
     "VALIDITY_WINDOW_END"),
])
def test_sf283_s06_expiry_provenance(tmp_path, prices, expected):
    result, report, *_ = _sf283_roundtrip(tmp_path, prices=prices)
    assert result.outcomes[0].reason == expected
    assert result.outcomes[0].terminal_event_bucket is not None
    assert report["windows"]["IS"]["lifecycle_by_signal_window"]["EXPIRED"] == 1


def test_sf283_s07_terminal_open(tmp_path):
    prices = {i: ("100.2", "100.21", "100.1", "100.2")
              for i in range(1255, MINUTES)}
    result, report, *_ = _sf283_roundtrip(tmp_path, prices=prices)
    assert result.outcomes[-1].state == "OPEN"
    assert report["windows"]["IS"]["lifecycle_by_signal_window"]["OPEN"] == 1
    assert report["closed_cohort_reconciliation"]["total_closed"] == 0


def test_sf283_s08_terminal_armed(tmp_path):
    result, report, *_ = _sf283_roundtrip(tmp_path, signals=(260,))
    assert result.outcomes[-1].state == "ARMED"
    assert report["windows"]["OOS"]["lifecycle_by_signal_window"]["ARMED"] == 1


def test_sf283_s09_invalid_source_withholds(tmp_path):
    source = _source()
    bars = source.dataset.bars[:1255] + source.dataset.bars[1256:]
    manifest = replace(
        source.dataset.manifest, raw_row_count=MINUTES - 1,
        canonical_row_count=MINUTES - 1, missing_interval_count=1,
    )
    missing = RawDiagnosticSource(
        HistoricalBarDataset(manifest, bars), "synthetic-sf283-source-missing",
    )
    request = replace(_request(missing), oos_start=START + timedelta(minutes=1260))
    result = _runner(251).run_verified(request)
    assert result.failure is not None
    src = tmp_path / "source.json"
    strict = tmp_path / "strict.json"
    output = tmp_path / "result.json"
    write_source_quality_evidence(request, result, src)
    assessed = tuple(
        request.is_start + timedelta(minutes=i)
        for i in range(int((request.measured_end - request.is_start) /
                           timedelta(minutes=1)))
    )
    write_strict_reference_evidence(
        result, request, strict, assessed_intervals=assessed,
        ambiguous_intervals=(), producer_id="synthetic-strict-fixture-v1",
    )
    result.write_reportable_new(output, source_companion=src, strict_companion=strict)
    with pytest.raises(ReportabilityError):
        report_from_saved_bytes(output.read_bytes(), src.read_bytes(), strict.read_bytes())


def test_sf283_s10_independent_strict_ambiguity(tmp_path):
    _, report, *_ = _sf283_roundtrip(tmp_path, signals=(), ambiguous_minutes=(1252,))
    assert report["windows"]["IS"]["strict_reference"]["ambiguous_count"] == 1
    assert report["windows"]["OOS"]["strict_reference"]["ambiguous_count"] == 0


def test_sf283_s11_no_closes_undefined_ratios_and_zero_frequency(tmp_path):
    _, report, *_ = _sf283_roundtrip(tmp_path, signals=())
    economics = report["windows"]["IS"]["economics"]
    assert economics["win_rate"]["reason"] == "NO_CLOSED_TRADES"
    assert economics["average_r_expectancy"]["reason"] == "NO_CLOSED_TRADES"
    assert economics["profit_factor_r"]["reason"] == "NO_CLOSED_TRADES"
    assert economics["maximum_cumulative_r_drawdown"]["reason"] == "EMPTY_COHORT"
    assert economics["frequency_per_1000_expected_5m_decisions"]["value"] == "0"


def test_sf283_s12_winner_without_losses_undefined_profit_factor(tmp_path):
    _, report, *_ = _sf283_roundtrip(
        tmp_path, prices={1255: ("100", "105", "98", "100")},
    )
    assert report["windows"]["IS"]["economics"]["profit_factor_r"]["reason"] == "NO_LOSING_R"


def test_sf283_s13_unique_real_runner_exit_buckets(tmp_path):
    prices = {1255: ("100", "105", "98", "100"),
              1265: ("100", "105", "98", "100")}
    result, report, *_ = _sf283_roundtrip(
        tmp_path, signals=(251, 253), prices=prices,
    )
    exited = [o.exit_bucket for o in result.outcomes if o.state == "CLOSED"]
    assert len(exited) == 2 and len(set(exited)) == 2
    assert report["closed_cohort_reconciliation"]["total_closed"] == 2


def test_sf283_s14_profile_isolation_repeatability(tmp_path):
    prices = {1255: ("100", "105", "98", "100")}
    source = _source(overrides=prices)
    base = replace(_request(source), oos_start=START + timedelta(minutes=1260))
    a = _runner(251).run_verified(base)
    again = _runner(251).run_verified(base)
    b = _runner(251).run_verified(replace(
        base, profile=HistoricalExecutionAssumptionProfile.adverse_raw(),
    ))
    assert a.mapping() == again.mapping()
    assert a.reportable_mapping() == again.reportable_mapping()
    assert a.manifest.run_id != b.manifest.run_id


@pytest.mark.parametrize("mutation", ["invalid-result-hash", "absent-companion",
                                     "corrupt-source", "unknown-contract"])
def test_sf283_s16_missing_or_contradictory_saved_evidence(tmp_path, mutation):
    from signalforge.config.identity import canonical_config_json
    from signalforge.research.scenario_reportability import _decode_canonical

    result, report, output, src, strict = _sf283_roundtrip(tmp_path, signals=())
    document = _decode_canonical(output.read_bytes())
    source = src.read_bytes()
    strict_bytes = strict.read_bytes()
    if mutation == "invalid-result-hash":
        document["scenario_result_id"] = "invalid"
    elif mutation == "absent-companion":
        strict_bytes = b"{}"
    elif mutation == "corrupt-source":
        source = b"{}"
    else:
        document["result"]["report_contract"] = "unknown"
    with pytest.raises(ReportabilityError):
        report_from_saved_bytes(
            (canonical_config_json(document) + "\n").encode(), source, strict_bytes,
        )


def test_sf283_s06_strategy_cutoff_from_real_synthetic_runner(tmp_path):
    registry = StrategyRegistry((
        StrategyRegistration(
            SEL.strategy_id, SEL.strategy_version,
            lambda params: _EarlyCutoff((251,)),
        ),
    ))
    no_fill = {
        i: ("100", "100.05", "100", "100") for i in range(1255, 1260)
    }
    result, report, *_ = _sf283_roundtrip(
        tmp_path, runner=ScenarioResearchRunner(registry=registry),
        prices=no_fill,
    )
    assert result.outcomes[0].state == "EXPIRED"
    assert result.outcomes[0].reason == "STRATEGY_CUTOFF"
    assert report["windows"]["IS"]["lifecycle_by_signal_window"]["EXPIRED"] == 1


def test_sf283_s13_duplicate_close_bucket_fails_closed_math():
    from signalforge.research.scenario_reportability import _economics

    same_exit = (START + timedelta(minutes=1255)).isoformat()
    closed = [
        {"exit_bucket": same_exit, "r": "1", "reason": "TARGET",
         "holding_span_1m_buckets": 1},
        {"exit_bucket": same_exit, "r": "-1", "reason": "STOP",
         "holding_span_1m_buckets": 1},
    ]
    with pytest.raises(ReportabilityError, match="DUPLICATE_MODELED_CLOSE_BUCKET"):
        _economics(closed, 2, 2)


def test_sf283_s14_two_hash_bound_profiles_do_not_pool(tmp_path):
    from signalforge.research.scenario_reportability import compare_profile_reports

    reference_dir = tmp_path / "reference"
    adverse_dir = tmp_path / "adverse"
    reference_dir.mkdir()
    adverse_dir.mkdir()
    price = {1255: ("100", "105", "98", "100")}
    _, ref, *_ = _sf283_roundtrip(
        reference_dir, prices=price,
        profile=HistoricalExecutionAssumptionProfile.reference_raw(),
    )
    _, adv, *_ = _sf283_roundtrip(
        adverse_dir, prices=price,
        profile=HistoricalExecutionAssumptionProfile.adverse_raw(),
    )
    combined = compare_profile_reports(ref, adv)
    assert combined["status"] == "SCENARIO_CONDITIONED_PROFILE_COMPARISON"
    assert combined["basis"] == "REFERENCE_RAW_MINUS_ADVERSE_RAW"
    assert ref["scenario_run_id"] != adv["scenario_run_id"]
    assert combined["windows"]["IS"]["closed_contained_difference"] == 0
    with pytest.raises(ReportabilityError, match="PROFILE_ISOLATION_REQUIRED"):
        compare_profile_reports(ref, ref)


def test_sf283_saved_byte_cli_synthetic_only(tmp_path):
    import json
    import subprocess
    import sys

    _, report, result, source, strict = _sf283_roundtrip(tmp_path, signals=())
    script = Path(__file__).resolve().parents[3] / "scripts/scenario_report_saved.py"
    command = [
        sys.executable, str(script),
        "--result", str(result),
        "--source-companion", str(source),
        "--strict-companion", str(strict),
    ]
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    assert completed.returncode == 0
    assert json.loads(completed.stdout) == report
    blocked = subprocess.run(
        [*command[:-1], str(tmp_path / "missing.json")],
        capture_output=True, text=True, check=False,
    )
    assert blocked.returncode == 2
    assert json.loads(blocked.stdout)["status"] == "WITHHELD"


def test_sf283_companion_producers_reject_wrong_source_or_profile(tmp_path):
    source = _source()
    req = replace(_request(source), oos_start=START + timedelta(minutes=1260))
    result = _runner(251).run_verified(req)
    mismatched_source = replace(
        req, source=_source(overrides={1255: ("100", "105", "98", "100")}),
    )
    with pytest.raises(ValueError, match="does not match result manifest"):
        write_source_quality_evidence(
            mismatched_source, result, tmp_path / "wrong-source.json",
        )
    mismatched_profile = replace(
        req, profile=HistoricalExecutionAssumptionProfile.adverse_raw(),
    )
    with pytest.raises(ValueError, match="does not match result manifest"):
        write_strict_reference_evidence(
            result, mismatched_profile, tmp_path / "wrong-strict.json",
            assessed_intervals=(), ambiguous_intervals=(),
            producer_id="synthetic-independent-strict-diagnostic-v1",
        )
    assert not (tmp_path / "wrong-source.json").exists()
    assert not (tmp_path / "wrong-strict.json").exists()


@pytest.mark.parametrize("mutation,reason", [
    ("wrong-r", "CONTRADICTORY_MODELED_R"),
    ("wrong-holding-span", "CONTRADICTORY_HOLDING_SPAN"),
    ("entry-before-signal", "ENTRY_BEFORE_COMPLETED_SIGNAL"),
    ("terminal-outside", "INVALID_TERMINAL_BOUNDARY"),
    ("source-count", "SOURCE_COUNT_MISMATCH"),
    ("strict-mask", "STRICT_DENOMINATOR_MISMATCH"),
])
def test_sf283_s16_semantic_conflict_with_consistent_canonical_hashes(
    tmp_path, mutation, reason,
):
    """Even rehashed, mutually bound contradictory saved bytes must fail."""
    from hashlib import sha256

    from signalforge.config.identity import canonical_config_json
    from signalforge.research.scenario_reportability import _decode_canonical

    _, _, output, source, strict = _sf283_roundtrip(
        tmp_path, prices={1255: ("100", "105", "98", "100")},
    )
    doc = _decode_canonical(output.read_bytes())
    result = doc["result"]
    evidence = _decode_canonical(source.read_bytes())
    strict_evidence = _decode_canonical(strict.read_bytes())
    row = result["outcomes"][0]
    if mutation == "wrong-r":
        row["r"] = Decimal("-1")
    elif mutation == "wrong-holding-span":
        row["holding_span_1m_buckets"] = 5
    elif mutation == "entry-before-signal":
        row["entry_bucket"] = row["signal_interval_start"]
    elif mutation == "terminal-outside":
        row["terminal_event_bucket"] = (
            START + timedelta(minutes=MINUTES + 1)
        ).isoformat()
    elif mutation == "source-count":
        evidence["windows"]["IS"]["primary_disposition_counts"]["VALID"] -= 1
    else:
        strict_evidence["windows"]["IS"]["eligible_intervals"] -= 1

    legacy = dict(result)
    legacy["schema_version"] = "scenario-result-v1"
    legacy.pop("report_contract")
    legacy.pop("companion_sha256")
    future = (
        "signal_interval_start", "signal_interval_end", "valid_until_boundary",
        "strategy_cutoff_boundary", "terminal_event_bucket",
        "attempted_entry_bucket", "modeled_stop_price", "modeled_target_price",
    )
    legacy["outcomes"] = [
        {key: value for key, value in outcome.items() if key not in future}
        for outcome in result["outcomes"]
    ]
    legacy_id = config_hash({"domain": "scenario-result-v1", "result": legacy})
    for companion in (evidence, strict_evidence):
        companion["scenario_result_v1_id"] = legacy_id
    source_bytes = (canonical_config_json(evidence) + "\n").encode()
    strict_bytes = (canonical_config_json(strict_evidence) + "\n").encode()
    result["companion_sha256"] = {
        "source_quality": sha256(source_bytes).hexdigest(),
        "strict_reference": sha256(strict_bytes).hexdigest(),
    }
    doc["scenario_result_id"] = config_hash({
        "domain": "scenario-result-v2", "result": result,
    })
    document = (canonical_config_json(doc) + "\n").encode()
    with pytest.raises(ReportabilityError, match=reason):
        report_from_saved_bytes(document, source_bytes, strict_bytes)
