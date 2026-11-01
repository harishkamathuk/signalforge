from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

from signalforge.domain.execution import ExecutionMode, Fill
from signalforge.domain.exits import ExitReason
from signalforge.domain.ids import (
    ConfigId,
    EntryIntentId,
    InstrumentId,
    RunId,
    TriggerEventId,
)
from signalforge.domain.instruments import TickSizeRule, TickSizeSchedule
from signalforge.domain.market import MarketEvent
from signalforge.domain.money import Price, Quantity
from signalforge.domain.provenance import RunIdentity, StrategyIdentity
from signalforge.domain.signals import Signal
from signalforge.domain.time import CandleInterval
from signalforge.research.backtest import BacktestRunner
from signalforge.runtime.market_session import (
    NSE_INTRADAY_MARKET_SESSION_POLICY,
)
from signalforge.runtime.position_manager import PositionManager
from signalforge.runtime.replay import InMemoryReplaySource
from signalforge.runtime.strategy import PositionEconomics

INSTRUMENT = InstrumentId("TEST:ASSET")


class _SyntheticSessionPolicy:
    def accepts_event(self, at: datetime) -> bool:
        return at.hour == 3

    def compulsory_exit_at(self, at: datetime) -> datetime:
        return at.replace(hour=3, minute=2, second=0, microsecond=0)


def _run() -> RunIdentity:
    return RunIdentity(
        run_id=RunId("run-sf089"),
        strategy=StrategyIdentity("test_strategy", "1.0.0"),
        config_id=ConfigId("config-sf089"),
        config_hash="hash-sf089",
        engine_calculation_version="engine-v1",
    )


def _schedule() -> TickSizeSchedule:
    return TickSizeSchedule(
        instrument_id=INSTRUMENT,
        rules=(TickSizeRule(Price(Decimal("0.01")), date(2026, 1, 1)),),
    )


def _event(at: datetime, price: str) -> MarketEvent:
    return MarketEvent(
        instrument_id=INSTRUMENT,
        exchange_timestamp=at,
        received_timestamp=at,
        price=Price(Decimal(price)),
        quantity=1,
        source="sf089-test",
    )


def test_nse_policy_preserves_existing_boundaries() -> None:
    from signalforge.domain.time import IST

    assert NSE_INTRADAY_MARKET_SESSION_POLICY.accepts_event(
        datetime(2026, 8, 31, 9, 15, tzinfo=IST)
    )
    assert NSE_INTRADAY_MARKET_SESSION_POLICY.accepts_event(
        datetime(2026, 8, 31, 15, 30, tzinfo=IST)
    )
    assert not NSE_INTRADAY_MARKET_SESSION_POLICY.accepts_event(
        datetime(2026, 8, 31, 9, 14, tzinfo=IST)
    )
    assert NSE_INTRADAY_MARKET_SESSION_POLICY.compulsory_exit_at(
        datetime(2026, 8, 31, 10, 0, tzinfo=IST)
    ) == datetime(2026, 8, 31, 15, 15, tzinfo=IST)


def test_backtest_input_validation_uses_injected_policy_not_nse_constants() -> None:
    policy = _SyntheticSessionPolicy()
    runner = BacktestRunner(market_session_policy=policy)
    at = datetime(2026, 8, 31, 3, 0, tzinfo=UTC)
    source = InMemoryReplaySource(
        instrument_id=INSTRUMENT,
        events=(_event(at, "100"),),
    )
    experiment = SimpleNamespace(
        dataset=SimpleNamespace(
            start_at=at - timedelta(minutes=1),
            end_at=at + timedelta(minutes=1),
        )
    )

    inputs = tuple(
        runner._validated_inputs(
            experiment=experiment,
            instrument_id=INSTRUMENT,
            source=source,
        )
    )

    assert len(inputs) == 1
    assert inputs[0].event.exchange_timestamp == at


def test_position_manager_uses_injected_compulsory_exit_boundary() -> None:
    policy = _SyntheticSessionPolicy()
    signal_at = datetime(2026, 8, 31, 3, 0, tzinfo=UTC)
    signal = Signal.create(
        instrument_id=INSTRUMENT,
        interval=CandleInterval(
            start=signal_at - timedelta(minutes=1),
            end=signal_at,
        ),
        signal_close=Price(Decimal("100")),
        signal_low=Price(Decimal("99")),
        run=_run(),
        created_at=signal_at,
    )
    fill = Fill.create(
        entry_intent_id=EntryIntentId("intent-sf089"),
        trigger_event_id=TriggerEventId("trigger-sf089"),
        signal_id=signal.signal_id,
        instrument_id=INSTRUMENT,
        reference_price=Price(Decimal("100")),
        fill_price=Price(Decimal("100")),
        quantity=Quantity(1),
        execution_mode=ExecutionMode.PAPER,
        filled_at=signal_at,
        run=_run(),
    )
    manager = PositionManager(
        tick_schedule=_schedule(),
        market_session_policy=policy,
    )
    opened = manager.open_from_fill(
        fill,
        signal,
        PositionEconomics(
            stop_price=Price(Decimal("99")),
            raw_target_price=Price(Decimal("110")),
        ),
    )
    assert opened.trade is not None
    assert opened.position is not None

    before = _event(datetime(2026, 8, 31, 3, 1, tzinfo=UTC), "100")
    assert manager.process_market_event(opened.trade, opened.position, before) is None

    at_exit = _event(datetime(2026, 8, 31, 3, 2, tzinfo=UTC), "100")
    exit_fact = manager.process_market_event(opened.trade, opened.position, at_exit)

    assert exit_fact is not None
    assert exit_fact.reason is ExitReason.FORCED_SESSION_EXIT
