from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest

from signalforge.config.strategy_registry import StrategySelection
from signalforge.domain.ids import InstrumentId
from signalforge.domain.instruments import TickSizeRule, TickSizeSchedule
from signalforge.domain.market import MarketEvent
from signalforge.domain.money import Price, Quantity
from signalforge.research.contracts import (
    DatasetDefinition,
    DatasetSourceDefinition,
    ExperimentDefinition,
    InstrumentExecutionDefinition,
    UniverseDefinition,
)
from signalforge.research.orchestration import (
    ResearchExperimentError,
    ResearchOrchestrator,
)
from signalforge.runtime.replay import InMemoryReplaySource
from tests.integration.runtime.test_replay_golden_session import _golden_events

A = InstrumentId("NSE:AAA")
B = InstrumentId("NSE:BBB")


def _events(instrument_id: InstrumentId) -> tuple[MarketEvent, ...]:
    result: list[MarketEvent] = []
    for item in _golden_events():
        result.append(
            MarketEvent(
                instrument_id=instrument_id,
                exchange_timestamp=datetime.fromisoformat(str(item["exchange_timestamp"])),
                received_timestamp=datetime.fromisoformat(str(item["received_timestamp"])),
                price=Price(Decimal(str(item["price"]))),
                quantity=int(item["quantity"]),
                source=str(item["source"]),
                source_event_id=f"{instrument_id}:{item['source_event_id']}",
            )
        )
    return tuple(result)


def _source(instrument_id: InstrumentId) -> InMemoryReplaySource:
    return InMemoryReplaySource(
        instrument_id=instrument_id,
        events=_events(instrument_id),
    )


def _experiment(
    source_a: InMemoryReplaySource,
    source_b: InMemoryReplaySource,
) -> ExperimentDefinition:
    events_a = _events(A)
    return ExperimentDefinition.create(
        strategy_selection=StrategySelection("intraday_momentum_v1", "1.0.0", {}),
        universe=UniverseDefinition((B, A)),
        dataset=DatasetDefinition(
            (
                DatasetSourceDefinition(B, source_b.identity.source_id),
                DatasetSourceDefinition(A, source_a.identity.source_id),
            ),
            events_a[0].exchange_timestamp,
            events_a[-1].exchange_timestamp,
        ),
        engine_calculation_version="engine-v1",
        execution=(
            _execution(B),
            _execution(A),
        ),
    )


def _execution(instrument_id: InstrumentId) -> InstrumentExecutionDefinition:
    return InstrumentExecutionDefinition(
        instrument_id=instrument_id,
        quantity=Quantity(10),
        tick_schedule=TickSizeSchedule(
            instrument_id=instrument_id,
            rules=(
                TickSizeRule(
                    tick_size=Price(Decimal("0.10")),
                    effective_from=date(2026, 1, 1),
                ),
            ),
        ),
    )


def test_two_instrument_experiment_is_deterministic_and_order_independent() -> None:
    source_a = _source(A)
    source_b = _source(B)
    experiment = _experiment(source_a, source_b)

    first = ResearchOrchestrator().run(
        experiment=experiment,
        sources={B: source_b, A: source_a},
    )
    second = ResearchOrchestrator().run(
        experiment=experiment,
        sources={A: _source(A), B: _source(B)},
    )

    assert first == second
    assert first.experiment_id == experiment.experiment_id
    assert tuple(result.instrument_id for result in first.instrument_results) == (A, B)
    assert len(first.trade_dataset) == 2
    assert tuple(trade.instrument_id for trade in first.trade_dataset) == (A, B)

    assert first.analytics.trade_count == 2
    assert first.analytics.realised_trade_count == 2
    assert first.analytics.open_trade_count == 0
    assert first.analytics.wins == 2
    assert first.analytics.losses == 0
    assert first.analytics.win_rate == Decimal("1")
    assert first.analytics.expectancy_r == Decimal(
        "0.6666666666666666666666666667"
    )
    assert first.analytics.profit_factor is None
    assert first.analytics.gross_pnl == Decimal("4.0")
    assert first.analytics.max_drawdown_r == Decimal("0")
    assert first.analytics.economics_basis == "gross"

    assert tuple(item.instrument_id for item in first.per_instrument) == (A, B)
    assert all(item.analytics.trade_count == 1 for item in first.per_instrument)
    assert all(item.analytics.gross_pnl == Decimal("2.0") for item in first.per_instrument)


def test_orchestrator_validates_complete_source_mapping_before_running_any_instrument() -> None:
    source_a = _source(A)
    source_b = _source(B)
    experiment = _experiment(source_a, source_b)

    with pytest.raises(ResearchExperimentError, match="missing=.*NSE:BBB"):
        ResearchOrchestrator().run(
            experiment=experiment,
            sources={A: source_a},
        )


def test_orchestrator_does_not_mask_unexpected_backtest_defects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_a = _source(A)
    source_b = _source(B)
    experiment = _experiment(source_a, source_b)

    def explode(*args: object, **kwargs: object) -> object:
        raise RuntimeError("internal backtest defect")

    monkeypatch.setattr(
        "signalforge.research.orchestration.BacktestRunner.run",
        explode,
    )

    with pytest.raises(RuntimeError, match="internal backtest defect"):
        ResearchOrchestrator().run(
            experiment=experiment,
            sources={A: source_a, B: source_b},
        )


def test_orchestrator_reports_instrument_when_independent_backtest_fails() -> None:
    source_a = _source(A)
    regular_b = _events(B)
    first_b = regular_b[0]
    off_session_b = MarketEvent(
        instrument_id=B,
        exchange_timestamp=first_b.exchange_timestamp.replace(hour=9, minute=0),
        received_timestamp=first_b.received_timestamp.replace(hour=9, minute=0),
        price=first_b.price,
        quantity=1,
        source="off-session",
        source_event_id="off-session-b",
    )
    bad_b = InMemoryReplaySource(
        instrument_id=B,
        events=(off_session_b, *regular_b),
    )
    experiment = _experiment(source_a, bad_b)

    with pytest.raises(ResearchExperimentError, match="instrument NSE:BBB") as exc_info:
        ResearchOrchestrator().run(
            experiment=experiment,
            sources={A: source_a, B: bad_b},
        )

    assert exc_info.value.__cause__ is not None
    assert isinstance(exc_info.value.__cause__, ValueError)
