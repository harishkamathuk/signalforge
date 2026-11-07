"""SF-258 synthetic-only scenario engine and strict-lane isolation checks."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from signalforge.config.strategy_registry import (
    StrategyRegistration,
    StrategyRegistry,
    StrategySelection,
)
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
    HistoricalExecutionAssumptionProfile,
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
)
from signalforge.runtime.btc_momentum_baseline_v0 import (
    BtcMomentumBaselineDecision,
    BtcMomentumBaselineV0Strategy,
)
from signalforge.config.btc_momentum_baseline_v0 import BtcMomentumBaselineV0Config
from signalforge.runtime.strategy import CompletedCandleStrategyContext


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
        o, h, l, c = prices.get(offset, ("100", "100.05", "99.95", "100"))
        bars.append(replace(
            original, instrument_id=BTC,
            interval=CandleInterval(at, at + timedelta(minutes=1)),
            open=Price(Decimal(o)), high=Price(Decimal(h)),
            low=Price(Decimal(l)), close=Price(Decimal(c)),
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
             budgets: ScenarioResourcePolicy | None = None) -> ScenarioResearchRequest:
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
