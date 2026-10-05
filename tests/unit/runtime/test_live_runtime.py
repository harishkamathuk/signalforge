from __future__ import annotations

from contextlib import nullcontext
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import cast

import pytest
from sqlalchemy.orm import Session

from signalforge.config.strategy_v1 import StrategyV1EvaluationConfig
from signalforge.domain.ids import InstrumentId, RunId
from signalforge.domain.instruments import TickSizeRule, TickSizeSchedule
from signalforge.domain.market import CandleQuality, CompletedCandle, MarketEvent
from signalforge.domain.money import Price, Quantity
from signalforge.domain.provenance import RunIdentity
from signalforge.domain.strategy import (
    DecisionReason,
    MomentumResult,
    SetupResult,
    StrategyEvaluation,
    TrendResult,
)
from signalforge.domain.time import IST, CandleInterval
from signalforge.persistence.coordinator import LiveMarketInputCommit, PersistenceCoordinator
from signalforge.persistence.errors import ContradictoryFactError
from signalforge.runtime.candles import CandleEngine
from signalforge.runtime.decision_audit import project_v1_decision
from signalforge.runtime.eligibility import MarketDataFeedState
from signalforge.runtime.indicators import IndicatorContinuity, IndicatorEngine
from signalforge.runtime.lifecycle import LifecycleCoordinator, LifecycleState
from signalforge.runtime.live_runtime import (
    LiveRuntime,
    LiveRuntimeContinuity,
    LiveRuntimeError,
    LiveRuntimeReconciliationRequired,
)
from signalforge.runtime.recovery import (
    RecoveredLifecycle,
    RecoveryDisposition,
    RecoveryResult,
)
from signalforge.runtime.strategy import StrategyRuntimeFacts
from signalforge.runtime.strategy_v1 import IntradayMomentumV1Strategy

INSTRUMENT = InstrumentId("NSE:RELIANCE")
AT = datetime(2026, 10, 5, 4, 0, tzinfo=UTC)


class FakeSession:
    def __enter__(self) -> FakeSession:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def begin(self):
        return nullcontext()


class FakeFeed:
    def __init__(self) -> None:
        self._state = MarketDataFeedState.STARTING
        self.items: list[MarketEvent | None | Exception] = []
        self.started = False
        self.closed = False

    @property
    def state(self) -> MarketDataFeedState:
        return self._state

    def start(self) -> None:
        self.started = True

    def receive_once(self) -> MarketEvent | None:
        if not self.items:
            return None
        item = self.items.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def close(self) -> None:
        self.closed = True


class RecordingStrategy(IntradayMomentumV1Strategy):
    def __init__(self) -> None:
        super().__init__(StrategyV1EvaluationConfig())
        self.contexts = []

    def evaluate_completed_candle(self, context):
        self.contexts.append(context)
        return super().evaluate_completed_candle(context)


def strategy() -> RecordingStrategy:
    return RecordingStrategy()


def run_for(value: RecordingStrategy, suffix: str = "unit") -> RunIdentity:
    return RunIdentity(
        run_id=RunId(f"sf057-{suffix}"),
        strategy=value.identity,
        config_id=value.config_identity.config_id,
        config_hash=value.config_identity.config_hash,
        engine_calculation_version="engine-v1",
    )


def schedule() -> TickSizeSchedule:
    return TickSizeSchedule(
        instrument_id=INSTRUMENT,
        rules=(TickSizeRule(Price(Decimal("0.05")), date(2026, 1, 1)),),
    )


def event(
    minute: int,
    *,
    price: str = "100",
    source_event_id: str | None = None,
) -> MarketEvent:
    at = AT + timedelta(minutes=minute)
    return MarketEvent(
        instrument_id=INSTRUMENT,
        exchange_timestamp=at,
        received_timestamp=at + timedelta(milliseconds=1),
        price=Price(Decimal(price)),
        quantity=5,
        source="openalgo:quote",
        source_event_id=source_event_id,
    )


def context(_candle: CompletedCandle) -> StrategyRuntimeFacts:
    return StrategyRuntimeFacts(
        completed_regular_session_candles=250,
        continuity=IndicatorContinuity.HEALTHY,
        feed_state=None,
    )


def runtime(
    monkeypatch: pytest.MonkeyPatch,
    *,
    feed: FakeFeed | None = None,
    selected_strategy: RecordingStrategy | None = None,
) -> tuple[LiveRuntime, FakeFeed, RecordingStrategy, list[object]]:
    selected_feed = feed or FakeFeed()
    selected_feed._state = MarketDataFeedState.HEALTHY
    selected_strategy = selected_strategy or strategy()
    run = run_for(selected_strategy)
    commits: list[object] = []

    def persist(self, *, run, commit) -> None:
        commits.append(commit)

    monkeypatch.setattr(PersistenceCoordinator, "persist_live_market_input", persist)
    result = LiveRuntime(
        feed=selected_feed,
        run=run,
        instrument_id=INSTRUMENT,
        candle_engine=CandleEngine(instrument_id=INSTRUMENT),
        indicator_engine=IndicatorEngine(
            INSTRUMENT,
            run.engine_calculation_version,
            requirements=selected_strategy.indicator_requirements,
        ),
        lifecycle=LifecycleCoordinator(
            run=run,
            tick_schedule=schedule(),
            quantity=Quantity(10),
            strategy=selected_strategy,
        ),
        strategy=selected_strategy,
        session_factory=lambda: cast(Session, FakeSession()),
        decision_projector=project_v1_decision,
        evaluation_context_factory=context,
        continuity=LiveRuntimeContinuity.CONTINUOUS,
    )
    return result, selected_feed, selected_strategy, commits


def empty_recovery(
    run: RunIdentity,
    *,
    disposition: RecoveryDisposition,
) -> RecoveryResult:
    return RecoveryResult(
        disposition=disposition,
        run=run,
        indicator_state=None,
        lifecycle=RecoveredLifecycle(
            None, None, None, None, None, None, None, None, None, ()
        ),
        market_input_checkpoint=None,
    )


def test_forming_event_does_not_evaluate_strategy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value, _, selected_strategy, commits = runtime(monkeypatch)

    step = value.process_event(event(0), feed_state=MarketDataFeedState.HEALTHY)

    assert step.completed_candle is None
    assert step.indicator_snapshot is None
    assert step.evaluation is None
    assert selected_strategy.contexts == []
    assert len(commits) == 1
    assert commits[0].indicator_state is None


def test_boundary_event_completes_once_and_uses_actual_feed_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value, _, selected_strategy, commits = runtime(monkeypatch)
    value.process_event(event(0), feed_state=MarketDataFeedState.HEALTHY)

    step = value.process_event(
        event(5, price="101"), feed_state=MarketDataFeedState.STARTING
    )

    assert step.completed_candle is not None
    assert step.indicator_snapshot is not None
    assert step.evaluation is not None
    assert len(selected_strategy.contexts) == 1
    assert selected_strategy.contexts[0].feed_state is MarketDataFeedState.STARTING
    assert not step.evaluation.actionable
    assert commits[-1].indicator_state is not None


def test_baseline_no_event_poll_causes_no_runtime_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value, feed, _, commits = runtime(monkeypatch)
    before_candle = value.candle_engine.state
    before_indicator = value.indicator_engine.state
    before_lifecycle = value.lifecycle.snapshot()
    feed.items.append(None)

    step = value.poll_once()

    assert step.market_event is None
    assert value.candle_engine.state == before_candle
    assert value.indicator_engine.state == before_indicator
    assert value.lifecycle.snapshot() == before_lifecycle
    assert commits == []


def test_stale_gap_requires_reconciliation_and_healthy_reconnect_does_not_restore(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value, feed, _, _ = runtime(monkeypatch)
    feed._state = MarketDataFeedState.STALE
    feed.items.append(None)

    feed.items.append(event(0))

    with pytest.raises(LiveRuntimeReconciliationRequired):
        value.poll_once()

    assert value.continuity is LiveRuntimeContinuity.RECONCILIATION_REQUIRED
    assert len(feed.items) == 2

    feed._state = MarketDataFeedState.HEALTHY
    with pytest.raises(LiveRuntimeReconciliationRequired):
        value.poll_once()

    assert len(feed.items) == 2


def test_synthetic_live_source_event_identity_is_rejected_and_terminal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value, _, _, commits = runtime(monkeypatch)

    with pytest.raises(LiveRuntimeError, match="synthetic provider"):
        value.process_event(
            event(0, source_event_id="invented"),
            feed_state=MarketDataFeedState.HEALTHY,
        )

    assert value.terminal
    assert commits == []


def test_persistence_failure_makes_mutated_runtime_terminal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value, _, _, _ = runtime(monkeypatch)

    def fail(self, *, run, commit) -> None:
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(PersistenceCoordinator, "persist_live_market_input", fail)

    with pytest.raises(RuntimeError, match="database unavailable"):
        value.process_event(event(0), feed_state=MarketDataFeedState.HEALTHY)

    assert value.terminal
    with pytest.raises(LiveRuntimeError, match="terminal"):
        value.process_event(event(1), feed_state=MarketDataFeedState.HEALTHY)


def test_new_recovery_completes_before_feed_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    selected_strategy = strategy()
    run = run_for(selected_strategy, "new")
    feed = FakeFeed()
    order: list[str] = []

    def inspect(self, **kwargs):
        order.append("recover")
        return empty_recovery(run, disposition=RecoveryDisposition.NEW)

    def start() -> None:
        order.append("start")
        feed.started = True

    def add(self, value):
        order.append("persist_run")
        return value

    monkeypatch.setattr("signalforge.runtime.live_runtime.RecoveryBootstrap.inspect", inspect)
    monkeypatch.setattr(
        "signalforge.runtime.live_runtime.PostgresRunProvenanceRepository.add", add
    )
    feed.start = start

    value = LiveRuntime.bootstrap(
        feed=feed,
        run=run,
        instrument_id=INSTRUMENT,
        tick_schedule=schedule(),
        quantity=Quantity(10),
        strategy=selected_strategy,
        session_factory=lambda: cast(Session, FakeSession()),
        decision_projector=project_v1_decision,
        evaluation_context_factory=context,
    )

    assert order == ["recover", "persist_run", "start"]
    assert value.continuity is LiveRuntimeContinuity.CONTINUOUS


def test_resumable_recovery_is_inspected_before_feed_start_and_is_not_continuous(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    selected_strategy = strategy()
    run = run_for(selected_strategy, "resumable")
    feed = FakeFeed()
    order: list[str] = []

    def inspect(self, **kwargs):
        order.append("recover")
        return empty_recovery(run, disposition=RecoveryDisposition.RESUMABLE)

    def start() -> None:
        order.append("start")
        feed.started = True

    monkeypatch.setattr("signalforge.runtime.live_runtime.RecoveryBootstrap.inspect", inspect)
    feed.start = start

    value = LiveRuntime.bootstrap(
        feed=feed,
        run=run,
        instrument_id=INSTRUMENT,
        tick_schedule=schedule(),
        quantity=Quantity(10),
        strategy=selected_strategy,
        session_factory=lambda: cast(Session, FakeSession()),
        decision_projector=project_v1_decision,
        evaluation_context_factory=context,
    )

    assert order == ["recover"]
    assert not feed.started
    assert value.continuity is LiveRuntimeContinuity.RECONCILIATION_REQUIRED


def test_contradictory_recovery_prevents_live_subscription(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    selected_strategy = strategy()
    run = run_for(selected_strategy, "contradictory")
    feed = FakeFeed()

    def inspect(self, **kwargs):
        raise ContradictoryFactError("corrupt durable state")

    monkeypatch.setattr("signalforge.runtime.live_runtime.RecoveryBootstrap.inspect", inspect)

    with pytest.raises(ContradictoryFactError):
        LiveRuntime.bootstrap(
            feed=feed,
            run=run,
            instrument_id=INSTRUMENT,
            tick_schedule=schedule(),
            quantity=Quantity(10),
            strategy=selected_strategy,
            session_factory=lambda: cast(Session, FakeSession()),
            decision_projector=project_v1_decision,
            evaluation_context_factory=context,
        )

    assert not feed.started


def test_cross_instrument_event_fails_terminal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value, _, _, _ = runtime(monkeypatch)
    wrong = MarketEvent(
        instrument_id=InstrumentId("NSE:TCS"),
        exchange_timestamp=AT,
        received_timestamp=AT + timedelta(milliseconds=1),
        price=Price(Decimal("100")),
        quantity=1,
        source="openalgo:quote",
        source_event_id=None,
    )

    with pytest.raises(LiveRuntimeError, match="instrument"):
        value.process_event(wrong, feed_state=MarketDataFeedState.HEALTHY)

    assert value.terminal


def actionable_candle_and_decision() -> tuple[CompletedCandle, StrategyEvaluation]:
    interval = CandleInterval.five_minutes(
        datetime(2026, 10, 5, 10, 0, tzinfo=IST)
    )
    candle = CompletedCandle(
        instrument_id=INSTRUMENT,
        interval=interval,
        quality=CandleQuality.VALID,
        open=Price(Decimal("100")),
        high=Price(Decimal("102")),
        low=Price(Decimal("100")),
        close=Price(Decimal("101")),
        volume=100,
        source="openalgo:quote",
        source_event_count=10,
    )
    decision = StrategyEvaluation(
        instrument_id=INSTRUMENT,
        interval=interval,
        trend=TrendResult(True),
        momentum=MomentumResult(True, True, True, None),
        setup=SetupResult(True),
        qualified=True,
        actionable=True,
        reasons=(DecisionReason.QUALIFIED, DecisionReason.ACTIONABLE),
    )
    return candle, decision


def test_armed_state_survives_gap_without_post_gap_trigger(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value, _, _, _ = runtime(monkeypatch)
    candle, decision = actionable_candle_and_decision()
    armed = value.lifecycle.process_evaluation(candle, decision)
    assert armed.state is LifecycleState.ARMED
    before = value.lifecycle.snapshot()

    value.mark_gap()

    with pytest.raises(LiveRuntimeReconciliationRequired):
        value.process_event(
            MarketEvent(
                instrument_id=INSTRUMENT,
                exchange_timestamp=datetime(2026, 10, 5, 10, 6, tzinfo=IST),
                received_timestamp=datetime(2026, 10, 5, 10, 6, tzinfo=IST),
                price=Price(Decimal("200")),
                quantity=1,
                source="openalgo:quote",
                source_event_id=None,
            ),
            feed_state=MarketDataFeedState.HEALTHY,
        )

    assert value.lifecycle.snapshot() == before
    assert value.lifecycle.state is LifecycleState.ARMED


def test_open_state_survives_gap_without_post_gap_exit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value, _, _, _ = runtime(monkeypatch)
    candle, decision = actionable_candle_and_decision()
    value.lifecycle.process_evaluation(candle, decision)
    value.lifecycle.process_market_event(
        MarketEvent(
            instrument_id=INSTRUMENT,
            exchange_timestamp=datetime(2026, 10, 5, 10, 6, tzinfo=IST),
            received_timestamp=datetime(2026, 10, 5, 10, 6, tzinfo=IST),
            price=Price(Decimal("102")),
            quantity=1,
            source="openalgo:quote",
            source_event_id=None,
        )
    )
    assert value.lifecycle.state is LifecycleState.OPEN
    before = value.lifecycle.snapshot()

    value.mark_gap()

    with pytest.raises(LiveRuntimeReconciliationRequired):
        value.process_event(
            MarketEvent(
                instrument_id=INSTRUMENT,
                exchange_timestamp=datetime(2026, 10, 5, 10, 7, tzinfo=IST),
                received_timestamp=datetime(2026, 10, 5, 10, 7, tzinfo=IST),
                price=Price(Decimal("1")),
                quantity=1,
                source="openalgo:quote",
                source_event_id=None,
            ),
            feed_state=MarketDataFeedState.HEALTHY,
        )

    assert value.lifecycle.snapshot() == before
    assert value.lifecycle.state is LifecycleState.OPEN


def test_direct_event_in_stale_state_cannot_advance_armed_or_candle_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value, _, _, commits = runtime(monkeypatch)
    before_candle = value.candle_engine.state
    before_lifecycle = value.lifecycle.snapshot()

    with pytest.raises(LiveRuntimeReconciliationRequired):
        value.process_event(event(0), feed_state=MarketDataFeedState.STALE)

    assert value.continuity is LiveRuntimeContinuity.RECONCILIATION_REQUIRED
    assert value.candle_engine.state == before_candle
    assert value.lifecycle.snapshot() == before_lifecycle
    assert commits == []


def test_healthy_live_event_preserves_paper_trigger_fill_and_open_semantics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value, _, _, commits = runtime(monkeypatch)
    candle, decision = actionable_candle_and_decision()
    value.lifecycle.process_evaluation(candle, decision)
    trigger = MarketEvent(
        instrument_id=INSTRUMENT,
        exchange_timestamp=datetime(2026, 10, 5, 10, 6, tzinfo=IST),
        received_timestamp=datetime(2026, 10, 5, 10, 6, tzinfo=IST),
        price=Price(Decimal("102")),
        quantity=1,
        source="openalgo:quote",
        source_event_id=None,
    )

    step = value.process_event(trigger, feed_state=MarketDataFeedState.HEALTHY)

    assert step.lifecycle.state is LifecycleState.OPEN
    assert len(commits) == 1
    commit = commits[0]
    assert len(commit.triggers) == 1
    assert len(commit.intents) == 1
    assert len(commit.fills) == 1
    assert len(commit.outcomes) == 1
    assert len(commit.trades) == 1
    assert len(commit.positions) == 1


def test_healthy_live_event_preserves_paper_target_exit_semantics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value, _, _, commits = runtime(monkeypatch)
    candle, decision = actionable_candle_and_decision()
    value.lifecycle.process_evaluation(candle, decision)
    value.process_event(
        MarketEvent(
            instrument_id=INSTRUMENT,
            exchange_timestamp=datetime(2026, 10, 5, 10, 6, tzinfo=IST),
            received_timestamp=datetime(2026, 10, 5, 10, 6, tzinfo=IST),
            price=Price(Decimal("102")),
            quantity=1,
            source="openalgo:quote",
            source_event_id=None,
        ),
        feed_state=MarketDataFeedState.HEALTHY,
    )
    assert value.lifecycle.state is LifecycleState.OPEN

    step = value.process_event(
        MarketEvent(
            instrument_id=INSTRUMENT,
            exchange_timestamp=datetime(2026, 10, 5, 10, 7, tzinfo=IST),
            received_timestamp=datetime(2026, 10, 5, 10, 7, tzinfo=IST),
            price=Price(Decimal("105")),
            quantity=1,
            source="openalgo:quote",
            source_event_id=None,
        ),
        feed_state=MarketDataFeedState.HEALTHY,
    )

    assert step.lifecycle.state is LifecycleState.CLOSED
    assert len(commits) == 2
    exit_commit = commits[-1]
    assert len(exit_commit.exits) == 1
    assert len(exit_commit.trades) == 1
    assert len(exit_commit.positions) == 1


def test_live_runtime_exposes_no_broker_order_surface() -> None:
    public_names = {name for name in dir(LiveRuntime) if not name.startswith("_")}

    assert not public_names & {
        "place_order",
        "modify_order",
        "cancel_order",
        "placeorder",
        "modifyorder",
        "cancelorder",
    }


def test_armed_runtime_rejects_non_healthy_direct_event_before_price_processing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value, _, _, commits = runtime(monkeypatch)
    candle, decision = actionable_candle_and_decision()
    value.lifecycle.process_evaluation(candle, decision)
    before = value.lifecycle.snapshot()

    with pytest.raises(LiveRuntimeError, match="Price-sensitive lifecycle"):
        value.process_event(
            MarketEvent(
                instrument_id=INSTRUMENT,
                exchange_timestamp=datetime(2026, 10, 5, 10, 6, tzinfo=IST),
                received_timestamp=datetime(2026, 10, 5, 10, 6, tzinfo=IST),
                price=Price(Decimal("200")),
                quantity=1,
                source="openalgo:quote",
                source_event_id=None,
            ),
            feed_state=MarketDataFeedState.STARTING,
        )

    assert value.terminal
    assert value.lifecycle.snapshot() == before
    assert commits == []


def test_live_commit_rejects_mismatched_indicator_calculation_version() -> None:
    selected_strategy = strategy()
    run = run_for(selected_strategy, "commit-mismatch")
    wrong_state = IndicatorEngine(
        INSTRUMENT,
        "other-engine",
        requirements=selected_strategy.indicator_requirements,
    ).state
    coordinator = PersistenceCoordinator(cast(Session, FakeSession()))

    with pytest.raises(ValueError, match="calculation version"):
        coordinator.persist_live_market_input(
            run=run,
            commit=LiveMarketInputCommit(indicator_state=wrong_state),
        )



def test_receive_that_discovers_stale_interval_requires_reconciliation_same_poll(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class StaleDuringReceiveFeed(FakeFeed):
        def receive_once(self) -> MarketEvent | None:
            self._state = MarketDataFeedState.STALE
            return None

    feed = StaleDuringReceiveFeed()
    value, _, _, commits = runtime(monkeypatch, feed=feed)
    before_candle = value.candle_engine.state
    before_lifecycle = value.lifecycle.snapshot()

    step = value.poll_once()

    assert step.market_event is None
    assert step.feed_state is MarketDataFeedState.STALE
    assert step.continuity is LiveRuntimeContinuity.RECONCILIATION_REQUIRED
    assert value.candle_engine.state == before_candle
    assert value.lifecycle.snapshot() == before_lifecycle
    assert commits == []
