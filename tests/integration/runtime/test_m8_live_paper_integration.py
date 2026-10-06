from __future__ import annotations

import os
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from signalforge.adapters.openalgo.config import OpenAlgoConfig
from signalforge.adapters.openalgo.history import HistoricalCompletedCandle
from signalforge.adapters.openalgo.live_market_data import (
    OpenAlgoMarketDataAdapter,
    OpenAlgoMarketDataDisconnected,
)
from signalforge.adapters.openalgo.market_data_config import OpenAlgoMarketDataConfig
from signalforge.adapters.openalgo.reference import OpenAlgoSubscriptionIdentity
from signalforge.adapters.openalgo.websocket_transport import (
    OpenAlgoWebSocketUnavailable,
)
from signalforge.config.strategy_v1 import StrategyV1EvaluationConfig
from signalforge.domain.ids import InstrumentId, RunId
from signalforge.domain.instruments import TickSizeRule, TickSizeSchedule
from signalforge.domain.market import CandleQuality
from signalforge.domain.money import Price, Quantity
from signalforge.domain.provenance import RunIdentity
from signalforge.domain.time import IST, CandleInterval
from signalforge.persistence.repositories import (
    PostgresArmedSetupRepository,
    PostgresEntryIntentRepository,
    PostgresExitRepository,
    PostgresFillRepository,
    PostgresIndicatorCheckpointRepository,
    PostgresMarketInputCheckpointRepository,
    PostgresPositionRepository,
    PostgresPreparedIndicatorCheckpointRepository,
    PostgresRunPreparedIndicatorCheckpointRepository,
    PostgresSignalRepository,
    PostgresStateTransitionRepository,
    PostgresStrategyDecisionRepository,
    PostgresTradeRepository,
    PostgresTriggerEventRepository,
)
from signalforge.runtime.decision_audit import project_v1_decision
from signalforge.runtime.eligibility import MarketDataFeedState
from signalforge.runtime.live_runtime import (
    LiveRuntime,
    LiveRuntimeContinuity,
    LiveRuntimeReconciliationRequired,
)
from signalforge.runtime.prepared_indicators import build_prepared_checkpoint
from signalforge.runtime.strategy import StrategyRuntimeFacts
from signalforge.runtime.strategy_v1 import IntradayMomentumV1Strategy

INSTRUMENT = InstrumentId("NSE:SF059")
TARGET_DATE = datetime(2026, 10, 5, tzinfo=IST).date()
REST_CONFIG = OpenAlgoConfig(host="http://127.0.0.1:5000", api_key="sf059-secret")
MD_CONFIG = OpenAlgoMarketDataConfig(
    ws_url="ws://127.0.0.1:8765",
    stale_after_seconds=10,
    reconnect_attempts=2,
    reconnect_delay_seconds=0,
    receive_timeout_seconds=1,
)
SUBSCRIPTION = OpenAlgoSubscriptionIdentity(symbol="SF059", exchange="NSE")


@pytest.fixture(scope="module")
def postgres_engine() -> Iterator[Engine]:
    database_url = os.environ.get("DATABASE_URL")
    if database_url is None:
        pytest.fail("DATABASE_URL is required for SF-059 integration tests")
    engine = sa.create_engine(database_url)
    try:
        yield engine
    finally:
        engine.dispose()


@dataclass
class FakeConnection:
    messages: list[object]
    sent: list[str] = field(default_factory=list)
    closed: bool = False

    def send_text(self, message: str) -> None:
        self.sent.append(message)

    def receive_text(self, timeout_seconds: float) -> str:
        assert timeout_seconds > 0
        if not self.messages:
            raise AssertionError("SF-059 fake WebSocket message queue exhausted")
        item = self.messages.pop(0)
        if isinstance(item, Exception):
            raise item
        assert isinstance(item, str)
        return item

    def close(self) -> None:
        self.closed = True


@dataclass
class FakeConnector:
    connections: list[object]

    def connect(self, *, url: str, timeout_seconds: float) -> FakeConnection:
        assert url == MD_CONFIG.ws_url
        assert timeout_seconds > 0
        if not self.connections:
            raise OpenAlgoWebSocketUnavailable("no deterministic SF-059 connection")
        item = self.connections.pop(0)
        if isinstance(item, Exception):
            raise item
        assert isinstance(item, FakeConnection)
        return item


@dataclass
class RuntimeFacts:
    runtime: LiveRuntime | None = None

    def __call__(self, _candle: object) -> StrategyRuntimeFacts:
        assert self.runtime is not None
        state = self.runtime.indicator_engine.state
        return StrategyRuntimeFacts(
            completed_regular_session_candles=state.completed_candle_count,
            continuity=state.continuity,
            feed_state=self.runtime.feed.state,
        )


def _auth_success() -> str:
    return '{"type":"auth","status":"success","broker":"zerodha"}'


def _subscribe_success() -> str:
    return (
        '{"type":"subscribe","status":"success","subscriptions":['
        '{"symbol":"SF059","exchange":"NSE","mode":"QUOTE"}]}'
    )


def _quote(*, at: datetime, price: str, volume: int) -> str:
    epoch_ms = int(at.timestamp() * 1000)
    return (
        '{"type":"market_data","symbol":"SF059","exchange":"NSE","mode":2,'
        f'"data":{{"ltp":{price},"volume":{volume},"timestamp":{epoch_ms},'
        f'"open":{price},"high":{price},"low":{price},"close":{price}}}}}'
    )


def _strategy() -> IntradayMomentumV1Strategy:
    return IntradayMomentumV1Strategy(StrategyV1EvaluationConfig())


def _run(strategy: IntradayMomentumV1Strategy, suffix: str) -> RunIdentity:
    return RunIdentity(
        run_id=RunId(f"sf059-{suffix}-{uuid4().hex[:10]}"),
        strategy=strategy.identity,
        config_id=strategy.config_identity.config_id,
        config_hash=strategy.config_identity.config_hash,
        engine_calculation_version="engine-v1",
    )


def _tick_schedule() -> TickSizeSchedule:
    return TickSizeSchedule(
        instrument_id=INSTRUMENT,
        rules=(TickSizeRule(Price(Decimal("0.05")), TARGET_DATE),),
    )


def _historical_candles() -> tuple[HistoricalCompletedCandle, ...]:
    sessions = (
        datetime(2026, 9, 28, tzinfo=IST).date(),
        datetime(2026, 9, 29, tzinfo=IST).date(),
        datetime(2026, 9, 30, tzinfo=IST).date(),
        datetime(2026, 10, 1, tzinfo=IST).date(),
    )
    pattern = (
        Decimal("0.4"),
        Decimal("0.4"),
        Decimal("0.4"),
        Decimal("-0.4"),
        Decimal("-0.4"),
    )
    close = Decimal("100")
    candles: list[HistoricalCompletedCandle] = []
    index = 0
    for session_date in sessions:
        start = datetime.combine(session_date, time(9, 15), tzinfo=IST)
        for offset in range(75):
            close += pattern[index % len(pattern)]
            interval_start = start + timedelta(minutes=5 * offset)
            candles.append(
                HistoricalCompletedCandle(
                    instrument_id=INSTRUMENT,
                    interval=CandleInterval(
                        interval_start,
                        interval_start + timedelta(minutes=5),
                    ),
                    quality=CandleQuality.VALID,
                    open=Price(close),
                    high=Price(Decimal("200") + Decimal(index) / Decimal("10")),
                    low=Price(Decimal("50") + Decimal(index) / Decimal("20")),
                    close=Price(close),
                    volume=10_000 + index,
                    source="openalgo:/api/v1/history",
                )
            )
            index += 1
    return tuple(candles)


def _prepared(strategy: IntradayMomentumV1Strategy):
    return build_prepared_checkpoint(
        instrument_id=INSTRUMENT,
        requirements=strategy.indicator_requirements,
        calculation_version="engine-v1",
        target_trading_date=TARGET_DATE,
        requested_from=datetime(2026, 9, 28).date(),
        requested_to=datetime(2026, 10, 1).date(),
        candles=_historical_candles(),
        prepared_at=datetime(2026, 10, 5, 8, 0, tzinfo=IST),
        minimum_warmup_candles=strategy.config.minimum_warmup_candles,
    )


def _persist_prepared(engine: Engine, checkpoint) -> None:
    with Session(engine) as session:
        with session.begin():
            PostgresPreparedIndicatorCheckpointRepository(session).add(checkpoint)


def _adapter(
    connector: FakeConnector,
    *,
    wall_clock: datetime,
) -> OpenAlgoMarketDataAdapter:
    return OpenAlgoMarketDataAdapter(
        config=REST_CONFIG,
        market_data_config=MD_CONFIG,
        instrument_id=INSTRUMENT,
        subscription=SUBSCRIPTION,
        connector=connector,
        wall_clock=lambda: wall_clock,
        monotonic_clock=lambda: 100.0,
        sleep=lambda _seconds: None,
    )


def _bootstrap_runtime(
    *,
    engine: Engine,
    adapter: OpenAlgoMarketDataAdapter,
    strategy: IntradayMomentumV1Strategy,
    checkpoint,
    suffix: str,
) -> tuple[LiveRuntime, RuntimeFacts, RunIdentity]:
    run = _run(strategy, suffix)
    facts = RuntimeFacts()
    runtime = LiveRuntime.bootstrap(
        feed=adapter,
        run=run,
        instrument_id=INSTRUMENT,
        tick_schedule=_tick_schedule(),
        quantity=Quantity(10),
        strategy=strategy,
        session_factory=lambda: Session(engine),
        decision_projector=project_v1_decision,
        evaluation_context_factory=facts,
        initial_prepared_checkpoint=checkpoint,
    )
    facts.runtime = runtime
    return runtime, facts, run


def test_golden_live_like_session_reaches_closed_from_prepared_state(
    postgres_engine: Engine,
) -> None:
    strategy = _strategy()
    checkpoint = _prepared(strategy)
    assert checkpoint.state.completed_candle_count == 300
    _persist_prepared(postgres_engine, checkpoint)

    start = datetime(2026, 10, 5, 9, 15, tzinfo=IST)
    connection = FakeConnection(
        [
            _auth_success(),
            _subscribe_success(),
            _quote(at=start, price="124.0", volume=100),
            _quote(at=start + timedelta(seconds=10), price="124.1", volume=101),
            _quote(
                at=start + timedelta(minutes=4, seconds=50),
                price="124.4",
                volume=102,
            ),
            _quote(at=start + timedelta(minutes=5), price="124.5", volume=103),
            _quote(at=start + timedelta(minutes=6), price="125.0", volume=104),
            _quote(at=start + timedelta(minutes=7), price="127.0", volume=105),
        ]
    )
    adapter = _adapter(FakeConnector([connection]), wall_clock=start)
    runtime, _, run = _bootstrap_runtime(
        engine=postgres_engine,
        adapter=adapter,
        strategy=strategy,
        checkpoint=checkpoint,
        suffix="golden",
    )

    assert runtime.poll_once().market_event is None
    assert adapter.state is MarketDataFeedState.HEALTHY
    runtime.poll_once()
    runtime.poll_once()
    signal_step = runtime.poll_once()
    assert signal_step.completed_candle is not None
    assert signal_step.evaluation is not None
    assert signal_step.evaluation.qualified is True
    assert signal_step.evaluation.actionable is True
    assert runtime.lifecycle.state.value == "armed"

    runtime.poll_once()
    assert runtime.lifecycle.state.value == "open"
    runtime.poll_once()
    assert runtime.lifecycle.state.value == "closed"

    with Session(postgres_engine) as session:
        assert (
            PostgresRunPreparedIndicatorCheckpointRepository(session).get_for_run(
                run.run_id
            )
            == checkpoint
        )
        run_indicator = PostgresIndicatorCheckpointRepository(session).get(
            run.run_id,
            INSTRUMENT,
        )
        assert run_indicator is not None
        assert run_indicator.completed_candle_count == 301

        signals = PostgresSignalRepository(session).find_for_run_instrument(
            run.run_id,
            INSTRUMENT,
        )
        setups = PostgresArmedSetupRepository(session).find_for_run_instrument(
            run.run_id,
            INSTRUMENT,
        )
        triggers = PostgresTriggerEventRepository(session).find_for_run_instrument(
            run.run_id,
            INSTRUMENT,
        )
        intents = PostgresEntryIntentRepository(session).find_for_run_instrument(
            run.run_id,
            INSTRUMENT,
        )
        fills = PostgresFillRepository(session).find_for_run_instrument(
            run.run_id,
            INSTRUMENT,
        )
        trades = PostgresTradeRepository(session).find_for_run_instrument(
            run.run_id,
            INSTRUMENT,
        )
        positions = PostgresPositionRepository(session).find_for_run_instrument(
            run.run_id,
            INSTRUMENT,
        )
        exits = PostgresExitRepository(session).find_for_run_instrument(
            run.run_id,
            INSTRUMENT,
        )
        transitions = PostgresStateTransitionRepository(session).find_for_run(
            run.run_id
        )

        assert len(signals) == 1
        assert len(setups) == 1
        assert len(triggers) == 1
        assert len(intents) == 1
        assert len(fills) == 1
        assert len(trades) == 1
        assert len(positions) == 1
        assert len(exits) == 1
        assert trades[0].state.value == "closed"
        assert positions[0].state.value == "closed"
        assert len(transitions) == 6
        assert (
            PostgresStrategyDecisionRepository(session).get(
                run.run_id,
                INSTRUMENT,
                signals[0].interval,
            )
            is not None
        )
        assert (
            PostgresMarketInputCheckpointRepository(session).get(
                run.run_id,
                INSTRUMENT,
            )
            is None
        )

    assert checkpoint.state.completed_candle_count == 300
    assert not {
        "place_order",
        "modify_order",
        "cancel_order",
    } & {name for name in dir(adapter) if not name.startswith("_")}


def test_adapter_recovery_does_not_restore_runtime_chronology(
    postgres_engine: Engine,
) -> None:
    strategy = _strategy()
    checkpoint = _prepared(strategy)
    _persist_prepared(postgres_engine, checkpoint)
    start = datetime(2026, 10, 5, 9, 15, tzinfo=IST)
    first = FakeConnection(
        [
            _auth_success(),
            _subscribe_success(),
            _quote(at=start, price="124.0", volume=100),
            OpenAlgoWebSocketUnavailable("deterministic disconnect"),
        ]
    )
    second = FakeConnection(
        [
            _auth_success(),
            _subscribe_success(),
            _quote(
                at=start + timedelta(minutes=1),
                price="124.5",
                volume=150,
            ),
            _quote(
                at=start + timedelta(minutes=1, seconds=1),
                price="124.6",
                volume=151,
            ),
        ]
    )
    adapter = _adapter(FakeConnector([first, second]), wall_clock=start)
    runtime, _, _ = _bootstrap_runtime(
        engine=postgres_engine,
        adapter=adapter,
        strategy=strategy,
        checkpoint=checkpoint,
        suffix="gap",
    )

    assert runtime.poll_once().market_event is None
    with pytest.raises(OpenAlgoMarketDataDisconnected):
        runtime.poll_once()
    assert runtime.continuity is LiveRuntimeContinuity.RECONCILIATION_REQUIRED

    adapter.recover()
    assert adapter.state is MarketDataFeedState.RECOVERING
    assert adapter.receive_once() is None
    assert adapter.state is MarketDataFeedState.HEALTHY

    with pytest.raises(LiveRuntimeReconciliationRequired):
        runtime.poll_once()
    assert runtime.continuity is LiveRuntimeContinuity.RECONCILIATION_REQUIRED
