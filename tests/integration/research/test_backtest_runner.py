from __future__ import annotations

from collections.abc import Iterator
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
from signalforge.runtime.replay import (
    InMemoryReplaySource,
    ReplayInput,
    ReplaySourceIdentity,
)
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


def _source(events: tuple[MarketEvent, ...]) -> InMemoryReplaySource:
    return InMemoryReplaySource(instrument_id=INSTRUMENT, events=events)


def _experiment(
    events: tuple[MarketEvent, ...],
    *,
    strategy_id: str = "intraday_momentum_v1",
    source_id: str | None = None,
    quantity: int = 10,
    tick_size: str = "0.10",
) -> ExperimentDefinition:
    source = _source(events)
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
                quantity=Quantity(quantity),
                tick_schedule=TickSizeSchedule(
                    instrument_id=INSTRUMENT,
                    rules=(
                        TickSizeRule(
                            tick_size=Price(Decimal(tick_size)),
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
        source=_source(events),
    )
    second = BacktestRunner().run(
        experiment=experiment,
        instrument_id=INSTRUMENT,
        source=_source(events),
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
    assert trade.stop_price == Price(Decimal("156.2"))
    assert trade.risk_per_share == Price(Decimal("0.3"))
    assert trade.raw_target_price == Price(Decimal("156.95"))
    assert trade.tradable_target_price == Price(Decimal("157.0"))
    assert trade.exit_price == Price(Decimal("156.7"))
    assert trade.realised_pnl == Decimal("2.0")
    assert trade.realised_r == Decimal("0.6666666666666666666666666667")


def test_research_identity_scopes_execution_variants_without_changing_legacy_run_id() -> None:
    events = _events()
    coarse = BacktestRunner().run(
        experiment=_experiment(events, tick_size="0.10"),
        instrument_id=INSTRUMENT,
        source=_source(events),
    )
    fine = BacktestRunner().run(
        experiment=_experiment(events, tick_size="0.05"),
        instrument_id=INSTRUMENT,
        source=_source(events),
    )

    assert coarse.run.run_id == fine.run.run_id
    assert coarse.trade_results[0].trade_id == fine.trade_results[0].trade_id

    assert coarse.experiment_id != fine.experiment_id
    assert coarse.backtest_run_id != fine.backtest_run_id
    assert (
        coarse.trade_results[0].backtest_trade_id
        != fine.trade_results[0].backtest_trade_id
    )
    assert coarse.trade_results[0].tradable_target_price != (
        fine.trade_results[0].tradable_target_price
    )


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
        source=_source(events),
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


def test_backtest_accepts_replay_source_protocol_directly() -> None:
    events = _events()
    source = _source(events)
    result = BacktestRunner().run(
        experiment=_experiment(events),
        instrument_id=INSTRUMENT,
        source=source,
    )

    assert result.source == source.identity
    assert result.events == source.identity.event_count


def test_historical_backtest_does_not_fabricate_live_feed_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from signalforge.runtime.strategy_v1 import IntradayMomentumV1Strategy

    events = _events()
    observed_feed_states: list[object] = []
    original = IntradayMomentumV1Strategy.evaluate_completed_candle

    def capture_feed_state(self, context):
        observed_feed_states.append(context.feed_state)
        return original(self, context)

    monkeypatch.setattr(
        IntradayMomentumV1Strategy,
        "evaluate_completed_candle",
        capture_feed_state,
    )

    BacktestRunner().run(
        experiment=_experiment(events),
        instrument_id=INSTRUMENT,
        source=_source(events),
    )

    assert observed_feed_states
    assert set(observed_feed_states) == {None}


def test_rsi_reference_strategy_uses_same_backtest_runner_deterministically() -> None:
    events = _events()
    experiment = _experiment(events, strategy_id="rsi_mean_reversion_v1")

    first = BacktestRunner().run(
        experiment=experiment,
        instrument_id=INSTRUMENT,
        source=_source(events),
    )
    second = BacktestRunner().run(
        experiment=experiment,
        instrument_id=INSTRUMENT,
        source=_source(events),
    )

    assert first == second
    assert first.strategy.strategy_id == "rsi_mean_reversion_v1"
    assert first.strategy.strategy_version == "1.0.0"
    assert first.source.source_id == second.source.source_id


def test_backtest_rejects_off_session_history_before_business_logic() -> None:
    regular = _events()
    first = regular[0]
    off_session = MarketEvent(
        instrument_id=INSTRUMENT,
        exchange_timestamp=first.exchange_timestamp.replace(hour=9, minute=0),
        received_timestamp=first.received_timestamp.replace(hour=9, minute=0),
        price=first.price,
        quantity=1,
        source="off-session",
        source_event_id="off-session",
    )
    events = (off_session, *regular)

    with pytest.raises(ValueError, match="outside the canonical NSE regular-session"):
        BacktestRunner().run(
            experiment=_experiment(events),
            instrument_id=INSTRUMENT,
            source=_source(events),
        )


def test_backtest_rejects_market_data_that_contradicts_dataset_source() -> None:
    events = _events()

    with pytest.raises(ValueError, match="dataset source_id"):
        BacktestRunner().run(
            experiment=_experiment(events, source_id="not-the-source"),
            instrument_id=INSTRUMENT,
            source=_source(events),
        )


class _ReplaySourceStub:
    def __init__(
        self,
        *,
        identity: ReplaySourceIdentity,
        inputs: tuple[ReplayInput, ...],
    ) -> None:
        self._identity = identity
        self._inputs = inputs

    @property
    def identity(self) -> ReplaySourceIdentity:
        return self._identity

    def __iter__(self) -> Iterator[ReplayInput]:
        return iter(self._inputs)


def test_backtest_rejects_source_identity_event_count_mismatch() -> None:
    events = _events()
    canonical = _source(events)
    source = _ReplaySourceStub(
        identity=ReplaySourceIdentity(
            source_id=canonical.identity.source_id,
            instrument_id=INSTRUMENT,
            event_count=canonical.identity.event_count + 1,
        ),
        inputs=tuple(canonical),
    )

    with pytest.raises(ValueError, match="event_count contradicts"):
        BacktestRunner().run(
            experiment=_experiment(events),
            instrument_id=INSTRUMENT,
            source=source,
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
    canonical = _source(events)
    source = _ReplaySourceStub(
        identity=canonical.identity,
        inputs=(
            ReplayInput(
                event=earlier,
                sequence=0,
                source_id=canonical.identity.source_id,
            ),
        ),
    )

    with pytest.raises(ValueError, match="outside experiment dataset range"):
        BacktestRunner().run(
            experiment=experiment,
            instrument_id=INSTRUMENT,
            source=source,
        )
