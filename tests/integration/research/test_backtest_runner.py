from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest

from signalforge.config.strategy_registry import StrategySelection
from signalforge.domain.ids import InstrumentId
from signalforge.domain.instruments import TickSizeRule, TickSizeSchedule
from signalforge.domain.market import MarketEvent
from signalforge.domain.money import Price, Quantity
from signalforge.domain.trades import TradeState
from signalforge.research.backtest import BacktestRunner
from signalforge.research.contracts import (
    DatasetDefinition,
    DatasetSourceDefinition,
    ExperimentDefinition,
    InstrumentExecutionDefinition,
    UniverseDefinition,
)
from signalforge.runtime.replay import InMemoryReplaySource
from tests.integration.runtime.test_replay_golden_session import _golden_events

INSTRUMENT = InstrumentId("NSE:RELIANCE")


def _events() -> tuple[MarketEvent, ...]:
    result: list[MarketEvent] = []
    for item in _golden_events():
        result.append(
            MarketEvent(
                instrument_id=INSTRUMENT,
                exchange_timestamp=datetime.fromisoformat(str(item["exchange_timestamp"])),
                received_timestamp=datetime.fromisoformat(str(item["received_timestamp"])),
                price=Price(Decimal(str(item["price"]))),
                quantity=int(item["quantity"]),
                source=str(item["source"]),
                source_event_id=str(item["source_event_id"]),
            )
        )
    return tuple(result)


def _experiment(
    events: tuple[MarketEvent, ...],
    *,
    strategy_id: str = "intraday_momentum_v1",
    source_id: str | None = None,
) -> ExperimentDefinition:
    source = InMemoryReplaySource(instrument_id=INSTRUMENT, events=events)
    return ExperimentDefinition.create(
        strategy_selection=StrategySelection(strategy_id, "1.0.0", {}),
        universe=UniverseDefinition((INSTRUMENT,)),
        dataset=DatasetDefinition(
            (
                DatasetSourceDefinition(
                    INSTRUMENT,
                    source_id or source.identity.source_id,
                ),
            ),
            events[0].exchange_timestamp,
            events[-1].exchange_timestamp,
        ),
        engine_calculation_version="engine-v1",
        execution=(
            InstrumentExecutionDefinition(
                instrument_id=INSTRUMENT,
                quantity=Quantity(10),
                tick_schedule=TickSizeSchedule(
                    instrument_id=INSTRUMENT,
                    rules=(
                        TickSizeRule(
                            tick_size=Price(Decimal("0.10")),
                            effective_from=date(2026, 1, 1),
                        ),
                    ),
                ),
            ),
        ),
    )


def test_v1_golden_backtest_preserves_replay_identity_counts_and_economics() -> None:
    events = _events()
    experiment = _experiment(events)

    first = BacktestRunner().run(
        experiment=experiment,
        instrument_id=INSTRUMENT,
        events=events,
    )
    second = BacktestRunner().run(
        experiment=experiment,
        instrument_id=INSTRUMENT,
        events=events,
    )

    assert first == second
    assert first.events == 302
    assert first.evaluations == 300
    assert first.qualified == 1
    assert first.actionable == 1
    assert first.signals == 1
    assert first.trades == 1
    assert first.exits == 1
    assert first.open_rejections == ()
    assert first.final_lifecycle_state == "closed"
    assert str(first.run.run_id) == (
        "ace5ec067a78720d3f0d4ab28dd47cc05924e6143a54ba8192690a9944cac80a"
    )
    assert first.source.source_id == (
        "b00a6d65ded8d5449a48ed012eb04e00b4bf65621e9939cd3f5b344940b3acbb"
    )

    assert len(first.trade_results) == 1
    trade = first.trade_results[0]
    assert trade.state is TradeState.CLOSED
    assert trade.entry_price == Price(Decimal("156.5"))
    assert trade.stop_price == Price(Decimal("156.3"))
    assert trade.risk_per_share == Price(Decimal("0.2"))
    assert trade.raw_target_price == Price(Decimal("156.8"))
    assert trade.tradable_target_price == Price(Decimal("156.8"))
    assert trade.exit_price == Price(Decimal("156.7"))
    assert trade.realised_pnl == Decimal("2.0")
    assert trade.realised_r == Decimal("1")


def test_backtest_surfaces_open_incomplete_trade_explicitly() -> None:
    all_events = _events()
    trigger_index = next(
        index
        for index, event in enumerate(all_events)
        if event.source_event_id == "g-trigger"
    )
    events = all_events[: trigger_index + 1]
    result = BacktestRunner().run(
        experiment=_experiment(events),
        instrument_id=INSTRUMENT,
        events=events,
    )

    assert result.final_lifecycle_state == "open"
    assert result.trades == 1
    assert result.exits == 0
    assert len(result.trade_results) == 1
    trade = result.trade_results[0]
    assert trade.state is TradeState.OPEN
    assert trade.exit_id is None
    assert trade.exit_price is None
    assert trade.realised_pnl is None
    assert trade.realised_r is None


def test_rsi_reference_strategy_uses_same_backtest_runner_deterministically() -> None:
    events = _events()
    experiment = _experiment(events, strategy_id="rsi_mean_reversion_v1")

    first = BacktestRunner().run(
        experiment=experiment,
        instrument_id=INSTRUMENT,
        events=events,
    )
    second = BacktestRunner().run(
        experiment=experiment,
        instrument_id=INSTRUMENT,
        events=events,
    )

    assert first == second
    assert first.strategy.strategy_id == "rsi_mean_reversion_v1"
    assert first.strategy.strategy_version == "1.0.0"
    assert first.source.source_id == second.source.source_id


def test_backtest_rejects_market_data_that_contradicts_dataset_source() -> None:
    events = _events()

    with pytest.raises(ValueError, match="dataset source_id"):
        BacktestRunner().run(
            experiment=_experiment(events, source_id="not-the-source"),
            instrument_id=INSTRUMENT,
            events=events,
        )


def test_backtest_rejects_event_outside_experiment_range() -> None:
    events = _events()
    experiment = _experiment(events)
    earlier = MarketEvent(
        instrument_id=INSTRUMENT,
        exchange_timestamp=events[0].exchange_timestamp.replace(hour=9, minute=14),
        received_timestamp=events[0].received_timestamp.replace(hour=9, minute=14),
        price=events[0].price,
        quantity=1,
        source="outside",
        source_event_id="outside",
    )

    with pytest.raises(ValueError, match="outside experiment dataset range"):
        BacktestRunner().run(
            experiment=experiment,
            instrument_id=INSTRUMENT,
            events=(earlier, *events),
        )
