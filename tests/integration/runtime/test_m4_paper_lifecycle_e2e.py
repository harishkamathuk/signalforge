from datetime import date, datetime, timedelta
from decimal import Decimal

from signalforge.config.strategy_v1 import StrategyV1EvaluationConfig
from signalforge.domain.armed import ArmedSetupState, ExpiryReason
from signalforge.domain.execution import ExecutionMode, Fill, TriggerEvent
from signalforge.domain.exits import ExitReason
from signalforge.domain.ids import ConfigId, EntryIntentId, InstrumentId, RunId, TriggerEventId
from signalforge.domain.indicators import IndicatorSnapshot
from signalforge.domain.instruments import TickSizeRule, TickSizeSchedule
from signalforge.domain.market import CandleQuality, CompletedCandle, MarketEvent
from signalforge.domain.money import Price, Quantity
from signalforge.domain.provenance import RunIdentity, StrategyIdentity
from signalforge.domain.signals import Signal
from signalforge.domain.time import IST, CandleInterval
from signalforge.runtime.eligibility import MarketDataFeedState
from signalforge.runtime.execution import PaperExecutionPort
from signalforge.runtime.indicators import IndicatorContinuity
from signalforge.runtime.lifecycle import LifecycleCoordinator, LifecycleState
from signalforge.runtime.position_manager import PositionManager, PositionOpenRejection
from signalforge.runtime.strategy_evaluator import StrategyEvaluationContext, StrategyEvaluator

INSTRUMENT = InstrumentId("NSE:RELIANCE")
QUANTITY = Quantity(10)


def _run() -> RunIdentity:
    return RunIdentity(
        run_id=RunId("run-038"),
        strategy=StrategyIdentity("intraday_momentum_v1", "1.0.0"),
        config_id=ConfigId("config-038"),
        config_hash="hash-038",
        engine_calculation_version="engine-v1",
    )


def _schedule() -> TickSizeSchedule:
    return TickSizeSchedule(
        instrument_id=INSTRUMENT,
        rules=(TickSizeRule(Price(Decimal("0.10")), date(2026, 1, 1)),),
    )


def _candle(*, end_hour: int = 10, end_minute: int = 0) -> CompletedCandle:
    end = datetime(2026, 8, 31, end_hour, end_minute, tzinfo=IST)
    return CompletedCandle(
        instrument_id=INSTRUMENT,
        interval=CandleInterval(start=end - timedelta(minutes=5), end=end),
        quality=CandleQuality.VALID,
        open=Price(Decimal("100.00")),
        high=Price(Decimal("101.00")),
        low=Price(Decimal("99.00")),
        close=Price(Decimal("100.11")),
        volume=1000,
        source="test",
        source_event_count=10,
    )


def _evaluation(candle: CompletedCandle):
    snapshot = IndicatorSnapshot(
        instrument_id=INSTRUMENT,
        interval=candle.interval,
        ready=True,
        calculation_version="engine-v1",
        ema9=Decimal("99.90"),
        ema20=Decimal("101.00"),
        ema50=Decimal("100.00"),
        rsi14=Decimal("60"),
        adx14=Decimal("23"),
        macd_line=Decimal("1"),
        macd_signal=Decimal("0.50"),
        macd_histogram=Decimal("0.50"),
    )
    return StrategyEvaluator(StrategyV1EvaluationConfig()).evaluate(
        candle,
        snapshot,
        StrategyEvaluationContext(
            completed_regular_session_candles=250,
            continuity=IndicatorContinuity.HEALTHY,
            feed_state=MarketDataFeedState.HEALTHY,
        ),
    )


def _event(price: str, *, hour: int = 10, minute: int = 1, event_id: str | None = None) -> MarketEvent:
    at = datetime(2026, 8, 31, hour, minute, tzinfo=IST)
    return MarketEvent(
        instrument_id=INSTRUMENT,
        exchange_timestamp=at,
        received_timestamp=at + timedelta(milliseconds=1),
        price=Price(Decimal(price)),
        quantity=1,
        source="test",
        source_event_id=event_id or f"evt-{hour:02d}{minute:02d}-{price}",
    )


def _coordinator() -> LifecycleCoordinator:
    return LifecycleCoordinator(run=_run(), tick_schedule=_schedule(), quantity=QUANTITY)


def test_full_happy_path_reaches_closed_with_exact_economics_and_audit() -> None:
    coordinator = _coordinator()
    candle = _candle()

    armed = coordinator.process_evaluation(candle, _evaluation(candle))
    assert armed.state is LifecycleState.ARMED
    assert armed.arming is not None
    assert armed.arming.signal.signal_close == Price(Decimal("100.11"))
    assert armed.arming.armed_setup.raw_trigger == Price(Decimal("100.21011"))
    assert armed.arming.armed_setup.tradable_trigger == Price(Decimal("100.30"))

    opened = coordinator.process_market_event(_event("100.50"))
    assert opened.state is LifecycleState.OPEN
    assert opened.execution is not None
    assert opened.execution.fill.reference_price == Price(Decimal("100.30"))
    assert opened.execution.fill.fill_price == Price(Decimal("100.50"))
    assert opened.open_result is not None and opened.open_result.trade is not None
    trade = opened.open_result.trade
    assert trade.stop_price == Price(Decimal("99.00"))
    assert trade.risk_per_share == Price(Decimal("1.50"))
    assert trade.raw_target_price == Price(Decimal("102.750"))
    assert trade.tradable_target_price == Price(Decimal("102.80"))

    closed = coordinator.process_market_event(_event("102.90", minute=2))
    assert closed.state is LifecycleState.CLOSED
    assert closed.exit is not None
    assert closed.exit.reason is ExitReason.TARGET
    assert closed.exit.reference_price == Price(Decimal("102.80"))
    assert closed.exit.fill_price == Price(Decimal("102.90"))
    assert closed.exit.realised_pnl == Decimal("24.00")
    assert closed.exit.realised_r == Decimal("1.6")

    assert [(t.entity_type.value, t.from_state, t.to_state) for t in coordinator.audit_transitions] == [
        ("armed_setup", "none", "armed"),
        ("armed_setup", "armed", "triggered"),
        ("trade", "none", "open"),
        ("position", "none", "open"),
        ("trade", "open", "closed"),
        ("position", "open", "closed"),
    ]


def test_trigger_equality_uses_observed_price_as_fill() -> None:
    coordinator = _coordinator()
    candle = _candle()
    armed = coordinator.process_evaluation(candle, _evaluation(candle))
    assert armed.arming is not None

    opened = coordinator.process_market_event(_event("100.30"))
    assert opened.state is LifecycleState.OPEN
    assert opened.execution is not None
    assert opened.execution.fill.fill_price == Price(Decimal("100.30"))


def test_signal_low_breach_before_trigger_expires_setup() -> None:
    coordinator = _coordinator()
    candle = _candle()
    coordinator.process_evaluation(candle, _evaluation(candle))

    expired = coordinator.process_market_event(_event("99.00"))
    assert expired.state is LifecycleState.EXPIRED
    assert expired.arming is not None
    assert expired.arming.armed_setup.state is ArmedSetupState.EXPIRED
    assert expired.arming.armed_setup.expiry_reason is ExpiryReason.SIGNAL_LOW_BREACH
    assert expired.execution is None


def test_following_completed_candle_expires_untriggered_setup() -> None:
    coordinator = _coordinator()
    signal_candle = _candle()
    coordinator.process_evaluation(signal_candle, _evaluation(signal_candle))

    next_candle = _candle(end_minute=5)
    expired = coordinator.process_completed_candle(next_candle)
    assert expired.state is LifecycleState.EXPIRED
    assert expired.arming is not None
    assert expired.arming.armed_setup.expiry_reason is ExpiryReason.VALIDITY_WINDOW_END


def test_1505_cutoff_expires_armed_setup() -> None:
    coordinator = _coordinator()
    candle = _candle(end_hour=15, end_minute=0)
    coordinator.process_evaluation(candle, _evaluation(candle))

    expired = coordinator.process_time(datetime(2026, 8, 31, 15, 5, tzinfo=IST))
    assert expired.state is LifecycleState.EXPIRED
    assert expired.arming is not None
    assert expired.arming.armed_setup.expiry_reason is ExpiryReason.ENTRY_CUTOFF_REACHED


def test_forced_session_exit_uses_first_observed_price_at_1515() -> None:
    coordinator = _coordinator()
    candle = _candle()
    coordinator.process_evaluation(candle, _evaluation(candle))
    coordinator.process_market_event(_event("100.50"))

    closed = coordinator.process_market_event(_event("101.70", hour=15, minute=15))
    assert closed.exit is not None
    assert closed.exit.reason is ExitReason.FORCED_SESSION_EXIT
    assert closed.exit.fill_price == Price(Decimal("101.70"))


def test_stop_gap_through_uses_actual_observed_exit_price() -> None:
    coordinator = _coordinator()
    candle = _candle()
    coordinator.process_evaluation(candle, _evaluation(candle))
    coordinator.process_market_event(_event("100.50"))

    closed = coordinator.process_market_event(_event("98.70", minute=2))
    assert closed.exit is not None
    assert closed.exit.reason is ExitReason.STOP
    assert closed.exit.reference_price == Price(Decimal("99.00"))
    assert closed.exit.fill_price == Price(Decimal("98.70"))


def test_later_actionable_evaluation_while_open_does_not_pyramid() -> None:
    coordinator = _coordinator()
    first_candle = _candle()
    first = coordinator.process_evaluation(first_candle, _evaluation(first_candle))
    assert first.arming is not None
    first_signal_id = first.arming.signal.signal_id
    coordinator.process_market_event(_event("100.50"))

    later_candle = _candle(end_minute=5)
    still_open = coordinator.process_evaluation(later_candle, _evaluation(later_candle))
    assert still_open.state is LifecycleState.OPEN
    assert still_open.arming is not None
    assert still_open.arming.signal.signal_id == first_signal_id


def test_duplicate_inputs_do_not_duplicate_logical_facts_or_audit() -> None:
    coordinator = _coordinator()
    candle = _candle()
    evaluation = _evaluation(candle)
    coordinator.process_evaluation(candle, evaluation)
    coordinator.process_evaluation(candle, evaluation)
    trigger_event = _event("100.50", event_id="duplicate-trigger")
    first_open = coordinator.process_market_event(trigger_event)
    audit_after_open = tuple(coordinator.audit_transitions)
    second_open = coordinator.process_market_event(trigger_event)

    assert first_open.execution is second_open.execution
    assert tuple(coordinator.audit_transitions) == audit_after_open

    exit_event = _event("102.90", minute=2, event_id="duplicate-exit")
    first_close = coordinator.process_market_event(exit_event)
    audit_after_close = tuple(coordinator.audit_transitions)
    second_close = coordinator.process_market_event(exit_event)
    assert first_close.exit is second_close.exit
    assert tuple(coordinator.audit_transitions) == audit_after_close


def test_non_positive_risk_rejection_is_preserved_at_composed_execution_boundary() -> None:
    end = datetime(2026, 8, 31, 10, 0, tzinfo=IST)
    signal = Signal.create(
        instrument_id=INSTRUMENT,
        interval=CandleInterval(start=end - timedelta(minutes=5), end=end),
        signal_close=Price(Decimal("100.00")),
        signal_low=Price(Decimal("100.00")),
        run=_run(),
        created_at=end,
    )
    trigger = TriggerEvent.create(
        signal_id=signal.signal_id,
        instrument_id=INSTRUMENT,
        reference_price=Price(Decimal("100.00")),
        observed_price=Price(Decimal("100.00")),
        observed_at=datetime(2026, 8, 31, 10, 1, tzinfo=IST),
        run=_run(),
    )
    execution = PaperExecutionPort().execute(trigger, quantity=QUANTITY)
    result = PositionManager(tick_schedule=_schedule()).open_from_fill(execution.fill, signal)

    assert result.opened is False
    assert result.rejection is PositionOpenRejection.NON_POSITIVE_RISK
    assert result.trade is None
    assert result.position is None
