from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from signalforge.config.rsi_mean_reversion_v1 import RsiMeanReversionV1Config
from signalforge.domain.armed import ExpiryReason
from signalforge.domain.exits import ExitReason
from signalforge.domain.ids import InstrumentId, RunId
from signalforge.domain.instruments import TickSizeRule, TickSizeSchedule
from signalforge.domain.market import CandleQuality, CompletedCandle, MarketEvent
from signalforge.domain.money import Price, Quantity
from signalforge.domain.provenance import RunIdentity
from signalforge.domain.time import IST, CandleInterval
from signalforge.runtime.eligibility import MarketDataFeedState
from signalforge.runtime.indicators import IndicatorContinuity
from signalforge.runtime.lifecycle import LifecycleCoordinator, LifecycleState
from signalforge.runtime.position_manager import PositionOpenRejection
from signalforge.runtime.replay import InMemoryReplaySource
from signalforge.runtime.replay_runtime import ReplayRuntime
from signalforge.runtime.rsi_mean_reversion_v1 import (
    RsiMeanReversionDecision,
    RsiMeanReversionV1Strategy,
)
from signalforge.runtime.strategy import StrategyRuntimeFacts

INSTRUMENT = InstrumentId("NSE:REFERENCE")


def _strategy() -> RsiMeanReversionV1Strategy:
    return RsiMeanReversionV1Strategy(RsiMeanReversionV1Config())


def _run(strategy: RsiMeanReversionV1Strategy) -> RunIdentity:
    return RunIdentity(
        run_id=RunId("run-rsi-reference-replay"),
        strategy=strategy.identity,
        config_id=strategy.config_identity.config_id,
        config_hash=strategy.config_identity.config_hash,
        engine_calculation_version="engine-v1",
    )


def _schedule() -> TickSizeSchedule:
    return TickSizeSchedule(
        instrument_id=INSTRUMENT,
        rules=(TickSizeRule(Price(Decimal("0.10")), date(2026, 1, 1)),),
    )


def _event(at: datetime, price: str, suffix: str) -> MarketEvent:
    return MarketEvent(
        instrument_id=INSTRUMENT,
        exchange_timestamp=at,
        received_timestamp=at + timedelta(milliseconds=1),
        price=Price(Decimal(price)),
        quantity=1,
        source="rsi-reference-replay",
        source_event_id=f"{at.isoformat()}-{suffix}",
    )


def _facts(_candle: CompletedCandle) -> StrategyRuntimeFacts:
    return StrategyRuntimeFacts(
        completed_regular_session_candles=250,
        continuity=IndicatorContinuity.HEALTHY,
        feed_state=MarketDataFeedState.HEALTHY,
    )


def _runtime(events: tuple[MarketEvent, ...]) -> ReplayRuntime:
    strategy = _strategy()
    source = InMemoryReplaySource(instrument_id=INSTRUMENT, events=events)
    return ReplayRuntime(
        source=source,
        run=_run(strategy),
        tick_schedule=_schedule(),
        quantity=Quantity(10),
        strategy=strategy,
        evaluation_context_factory=_facts,
    )


def _qualifying_prefix(*, signal_low: str = "85.97", signal_close: str = "86.03") -> tuple[
    MarketEvent, ...
]:
    start = datetime(2026, 8, 31, 10, 0, tzinfo=IST)
    events = [
        _event(start + timedelta(minutes=5 * index), str(100 - index), f"boundary-{index}")
        for index in range(14)
    ]
    events.append(_event(start + timedelta(minutes=70), signal_low, "signal-open-low"))
    events.append(_event(start + timedelta(minutes=74), signal_close, "signal-close"))
    events.append(_event(start + timedelta(minutes=75), "85.90", "next-window"))
    return tuple(events)


def test_reference_replay_warmup_then_qualifies_with_rsi_only() -> None:
    runtime = _runtime(_qualifying_prefix())

    steps = runtime.run_all()
    evaluations = [step.evaluation for step in steps if step.evaluation is not None]

    assert len(evaluations) == 15
    assert evaluations[0].reasons == ("rsi_unavailable",)
    assert evaluations[-1].qualified is True
    assert evaluations[-1].actionable is True
    assert evaluations[-1].reasons == ("rsi_below_threshold",)
    assert evaluations[-1].rsi14 is not None
    assert evaluations[-1].rsi14 < Decimal("30")
    assert runtime.indicator_engine.state.ema_states == ()
    assert runtime.indicator_engine.state.adx_state is None
    assert runtime.indicator_engine.state.macd_state is None


def test_reference_replay_arms_with_raw_close_and_shared_tick_normalization() -> None:
    runtime = _runtime(_qualifying_prefix())

    runtime.run_all()
    snapshot = runtime.lifecycle.snapshot()

    assert snapshot.state is LifecycleState.ARMED
    assert snapshot.arming is not None
    assert snapshot.arming.armed_setup.raw_trigger == Price(Decimal("86.03"))
    assert snapshot.arming.armed_setup.tradable_trigger == Price(Decimal("86.10"))
    assert snapshot.arming.armed_setup.signal_low == Price(Decimal("85.97"))
    assert (
        snapshot.arming.armed_setup.valid_until
        == snapshot.arming.armed_setup.armed_at + timedelta(minutes=5)
    )


def test_reference_replay_low_breach_does_not_invalidate_then_trigger_opens() -> None:
    prefix = _qualifying_prefix()
    armed_at = datetime(2026, 8, 31, 11, 15, tzinfo=IST)
    events = prefix + (
        _event(armed_at + timedelta(seconds=30), "85.90", "below-stop"),
        _event(armed_at + timedelta(minutes=1), "86.10", "trigger"),
    )
    runtime = _runtime(events)

    runtime.run_all()
    snapshot = runtime.lifecycle.snapshot()

    assert snapshot.state is LifecycleState.OPEN
    assert snapshot.arming is not None
    assert snapshot.arming.armed_setup.expiry_reason is None
    assert snapshot.execution is not None
    assert snapshot.execution.fill.fill_price == Price(Decimal("86.10"))
    assert snapshot.open_result is not None
    assert snapshot.open_result.opened
    assert snapshot.open_result.trade is not None
    assert snapshot.open_result.trade.stop_price == Price(Decimal("85.97"))
    assert snapshot.open_result.trade.raw_target_price == Price(Decimal("86.23"))
    assert snapshot.open_result.trade.tradable_target_price == Price(Decimal("86.30"))


@pytest.mark.parametrize(
    ("exit_price", "expected_reason"),
    (
        ("85.90", ExitReason.STOP),
        ("86.30", ExitReason.TARGET),
    ),
)
def test_reference_replay_open_position_exits_through_shared_rules(
    exit_price: str,
    expected_reason: ExitReason,
) -> None:
    prefix = _qualifying_prefix()
    armed_at = datetime(2026, 8, 31, 11, 15, tzinfo=IST)
    runtime = _runtime(
        prefix
        + (
            _event(armed_at + timedelta(minutes=1), "86.10", "trigger"),
            _event(armed_at + timedelta(minutes=2), exit_price, "exit"),
        )
    )

    runtime.run_all()
    snapshot = runtime.lifecycle.snapshot()

    assert snapshot.state is LifecycleState.CLOSED
    assert snapshot.exit is not None
    assert snapshot.exit.reason is expected_reason


def test_reference_replay_explicit_time_expires_at_following_candle_end() -> None:
    runtime = _runtime(_qualifying_prefix())

    runtime.run_all()
    armed = runtime.lifecycle.snapshot()
    assert armed.arming is not None

    expired = runtime.process_time(armed.arming.armed_setup.valid_until)

    assert expired.state is LifecycleState.EXPIRED
    assert expired.arming is not None
    assert expired.arming.armed_setup.terminal_at == armed.arming.armed_setup.valid_until
    assert expired.arming.armed_setup.expiry_reason is ExpiryReason.VALIDITY_WINDOW_END


def test_reference_zero_risk_fill_uses_generic_rejection() -> None:
    prefix = _qualifying_prefix(signal_low="86.00", signal_close="86.00")
    armed_at = datetime(2026, 8, 31, 11, 15, tzinfo=IST)
    runtime = _runtime(
        prefix + (_event(armed_at + timedelta(minutes=1), "86.00", "zero-risk-trigger"),)
    )

    runtime.run_all()
    snapshot = runtime.lifecycle.snapshot()

    assert snapshot.state is LifecycleState.TRIGGERED
    assert snapshot.open_result is not None
    assert snapshot.open_result.opened is False
    assert snapshot.open_result.rejection is PositionOpenRejection.NON_POSITIVE_RISK
    assert snapshot.open_result.trade is None
    assert snapshot.open_result.position is None


def test_reference_shared_session_safety_preempts_strategy_policy() -> None:
    strategy = _strategy()
    run = _run(strategy)
    coordinator = LifecycleCoordinator(
        run=run,
        tick_schedule=_schedule(),
        quantity=Quantity(10),
        strategy=strategy,
    )
    end = datetime(2026, 8, 31, 15, 10, tzinfo=IST)
    candle = CompletedCandle(
        instrument_id=INSTRUMENT,
        interval=CandleInterval(start=end - timedelta(minutes=5), end=end),
        quality=CandleQuality.VALID,
        open=Price(Decimal("100")),
        high=Price(Decimal("101")),
        low=Price(Decimal("99")),
        close=Price(Decimal("100")),
        volume=100,
        source="session-safety-test",
        source_event_count=1,
    )
    decision = RsiMeanReversionDecision(
        INSTRUMENT,
        candle.interval,
        qualified=True,
        actionable=True,
        reasons=("rsi_below_threshold",),
        rsi14=Decimal("20"),
    )
    coordinator.process_evaluation(candle, decision)
    forced_at = datetime(2026, 8, 31, 15, 15, tzinfo=IST)
    event = _event(forced_at, "200", "forced-boundary")

    snapshot = coordinator.process_market_event(event)

    assert snapshot.state is LifecycleState.EXPIRED
    assert snapshot.arming is not None
    assert snapshot.arming.armed_setup.expiry_reason is ExpiryReason.ENTRY_CUTOFF_REACHED
    assert snapshot.arming.armed_setup.terminal_at == forced_at
