from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from signalforge.config.strategy_v1 import StrategyV1EvaluationConfig
from signalforge.domain.armed import ArmedSetupState
from signalforge.domain.audit import TransitionEntityType
from signalforge.domain.exits import ExitReason
from signalforge.domain.ids import InstrumentId
from signalforge.domain.instruments import TickSizeRule, TickSizeSchedule
from signalforge.domain.market import CandleQuality, CompletedCandle, MarketEvent
from signalforge.domain.money import Price, Quantity
from signalforge.domain.position_outcomes import PositionOpenOutcome, PositionOpenOutcomeType
from signalforge.domain.positions import PositionState
from signalforge.domain.time import IST, CandleInterval
from signalforge.domain.trades import TradeState
from signalforge.persistence.coordinator import PersistenceCoordinator
from signalforge.persistence.errors import ContradictoryFactError
from signalforge.persistence.repositories import (
    PostgresArmedSetupRepository,
    PostgresExitRepository,
    PostgresFillRepository,
    PostgresIndicatorCheckpointRepository,
    PostgresPositionRepository,
    PostgresRunProvenanceRepository,
    PostgresStateTransitionRepository,
    PostgresTradeRepository,
    PostgresTriggerEventRepository,
)
from signalforge.runtime.indicator_recovery import IndicatorRecoveryReconciler, RecoveryCandle
from signalforge.runtime.indicators import IndicatorEngine, V1_INDICATOR_REQUIREMENTS
from signalforge.runtime.lifecycle import LifecycleCoordinator, LifecycleState
from signalforge.runtime.lifecycle_recovery import LifecycleRecoveryHydrator
from signalforge.runtime.recovery import RecoveryBootstrap
from signalforge.runtime.strategy_v1 import IntradayMomentumV1Strategy
from tests.integration.persistence.test_crash_consistency_between_groups import (
    _persist_trigger_group,
)
from tests.integration.persistence.test_recovery_postgres import (
    _persist_armed_graph,
    _persist_open_graph,
)
from tests.integration.persistence.test_repository_adapters_postgres import (
    _transition,
    facts,
)

INSTRUMENT = InstrumentId("NSE:SF045B")


@pytest.fixture(scope="module")
def postgres_engine() -> Iterator[Engine]:
    database_url = os.environ.get("DATABASE_URL")
    if database_url is None:
        pytest.fail("DATABASE_URL is required")
    engine = sa.create_engine(database_url)
    try:
        yield engine
    finally:
        engine.dispose()


def _strategy() -> IntradayMomentumV1Strategy:
    return IntradayMomentumV1Strategy(StrategyV1EvaluationConfig())


def _schedule() -> TickSizeSchedule:
    return TickSizeSchedule(
        instrument_id=INSTRUMENT,
        rules=(TickSizeRule(Price(Decimal("0.05")), date(2026, 1, 1)),),
    )


def _indicator_candles(count: int) -> tuple[CompletedCandle, ...]:
    start = datetime(2026, 9, 1, 9, 15, tzinfo=IST)
    result = []
    for index in range(count):
        close = Decimal("100") + Decimal(index) / Decimal("10")
        result.append(
            CompletedCandle(
                instrument_id=INSTRUMENT,
                interval=CandleInterval.five_minutes(start + timedelta(minutes=5 * index)),
                quality=CandleQuality.VALID,
                open=Price(close - Decimal("0.05")),
                high=Price(close + Decimal("0.10")),
                low=Price(close - Decimal("0.10")),
                close=Price(close),
                volume=100 + index,
                source="sf053-golden",
                source_event_count=1,
            )
        )
    return tuple(result)


def _recover_coordinator(postgres_engine: Engine, value):
    strategy = _strategy()
    with Session(postgres_engine) as session:
        recovered = RecoveryBootstrap().inspect(
            session=session,
            requested_run=value.run,
            instrument_id=INSTRUMENT,
            indicator_requirements=strategy.indicator_requirements,
        )

    if recovered.indicator_state is None:
        checkpoint = IndicatorEngine(
            INSTRUMENT,
            value.run.engine_calculation_version,
            requirements=strategy.indicator_requirements,
        ).state
    else:
        checkpoint = recovered.indicator_state
    indicator_result = IndicatorRecoveryReconciler(checkpoint).reconcile(())
    coordinator = LifecycleCoordinator(
        run=value.run,
        tick_schedule=_schedule(),
        quantity=Quantity(10),
        strategy=strategy,
    )
    hydrated = LifecycleRecoveryHydrator().hydrate(
        indicator_result=indicator_result,
        recovered=recovered.lifecycle,
        coordinator=coordinator,
    )
    return recovered, hydrated.coordinator


def test_indicator_warmup_restart_converges_to_full_recursive_state(
    postgres_engine: Engine,
) -> None:
    value = facts(f"sf053-warmup-{uuid4().hex[:8]}")
    candles = _indicator_candles(40)

    reference = IndicatorEngine(
        INSTRUMENT,
        value.run.engine_calculation_version,
        requirements=V1_INDICATOR_REQUIREMENTS,
    )
    for candle in candles:
        reference.update(candle)

    interrupted = IndicatorEngine(
        INSTRUMENT,
        value.run.engine_calculation_version,
        requirements=V1_INDICATOR_REQUIREMENTS,
    )
    for candle in candles[:20]:
        interrupted.update(candle)

    with Session(postgres_engine) as session:
        PostgresRunProvenanceRepository(session).add(value.run)
        PostgresIndicatorCheckpointRepository(session).upsert(value.run, interrupted.state)
        session.commit()

    with Session(postgres_engine) as session:
        recovered = RecoveryBootstrap().inspect(
            session=session,
            requested_run=value.run,
            instrument_id=INSTRUMENT,
            indicator_requirements=V1_INDICATOR_REQUIREMENTS,
        )
    assert recovered.indicator_state == interrupted.state

    reconciled = IndicatorRecoveryReconciler(recovered.indicator_state).reconcile(
        RecoveryCandle(candle, continuity_ok=True) for candle in candles[20:]
    )

    assert reconciled.engine.state == reference.state


def test_armed_restart_triggers_opens_and_persists_deterministic_graph(
    postgres_engine: Engine,
) -> None:
    value = facts(f"sf053-armed-open-{uuid4().hex[:8]}")
    _persist_armed_graph(postgres_engine, value)

    recovered, coordinator = _recover_coordinator(postgres_engine, value)
    assert coordinator.state is LifecycleState.ARMED
    assert recovered.lifecycle.setup is not None

    snapshot = coordinator.process_market_event(
        MarketEvent(
            instrument_id=INSTRUMENT,
            exchange_timestamp=value.trigger.observed_at,
            received_timestamp=value.trigger.observed_at + timedelta(milliseconds=1),
            price=value.trigger.observed_price,
            quantity=1,
            source="sf053-golden",
            source_event_id="sf053-trigger",
        )
    )
    assert snapshot.state is LifecycleState.OPEN
    assert snapshot.arming is not None
    assert snapshot.execution is not None
    assert snapshot.open_result is not None
    assert snapshot.open_result.trade is not None
    assert snapshot.open_result.position is not None

    transitions = coordinator.audit_transitions
    trigger_transition = next(
        item
        for item in transitions
        if item.entity_type is TransitionEntityType.ARMED_SETUP
        and item.from_state == "armed"
        and item.to_state == "triggered"
    )
    trade_transition = next(
        item
        for item in transitions
        if item.entity_type is TransitionEntityType.TRADE and item.to_state == "open"
    )
    position_transition = next(
        item
        for item in transitions
        if item.entity_type is TransitionEntityType.POSITION and item.to_state == "open"
    )
    trigger = coordinator.signal_lifecycle.trigger_event
    assert trigger is not None
    outcome = PositionOpenOutcome.create(
        fill_id=snapshot.execution.fill.fill_id,
        signal_id=snapshot.execution.fill.signal_id,
        outcome=PositionOpenOutcomeType.OPENED,
        decided_at=snapshot.execution.fill.filled_at,
        run=value.run,
    )

    with Session(postgres_engine) as session:
        persistence = PersistenceCoordinator(session)
        persistence.persist_trigger_intent(
            trigger=trigger,
            intent=snapshot.execution.entry_intent,
            setup=snapshot.arming.armed_setup,
            setup_transition=trigger_transition,
        )
        persistence.persist_opened_entry(
            fill=snapshot.execution.fill,
            outcome=outcome,
            trade=snapshot.open_result.trade,
            position=snapshot.open_result.position,
            trade_transition=trade_transition,
            position_transition=position_transition,
        )

    with Session(postgres_engine) as session:
        final = RecoveryBootstrap().inspect(
            session=session,
            requested_run=value.run,
            instrument_id=INSTRUMENT,
            indicator_requirements=V1_INDICATOR_REQUIREMENTS,
        )
    assert final.lifecycle.trade is not None
    assert final.lifecycle.position is not None
    assert final.lifecycle.trade.state is TradeState.OPEN
    assert final.lifecycle.position.state is PositionState.OPEN
    assert final.lifecycle.trade.entry_price == snapshot.execution.fill.fill_price
    assert final.lifecycle.trade.risk_per_share == snapshot.open_result.trade.risk_per_share
    assert final.lifecycle.trade.tradable_target_price == snapshot.open_result.trade.tradable_target_price


def test_armed_restart_expires_and_terminal_history_does_not_rearm(
    postgres_engine: Engine,
) -> None:
    value = facts(f"sf053-expiry-{uuid4().hex[:8]}")
    _persist_armed_graph(postgres_engine, value)

    _, coordinator = _recover_coordinator(postgres_engine, value)
    snapshot = coordinator.process_time(value.setup.valid_until)
    assert snapshot.state is LifecycleState.EXPIRED
    assert snapshot.arming is not None

    expiry_transition = next(
        item
        for item in coordinator.audit_transitions
        if item.entity_type is TransitionEntityType.ARMED_SETUP
        and item.to_state == ArmedSetupState.EXPIRED.value
    )
    with Session(postgres_engine) as session:
        PersistenceCoordinator(session).persist_expiry(
            setup=snapshot.arming.armed_setup,
            run_id=value.run.run_id,
            setup_transition=expiry_transition,
        )

    recovered, fresh = _recover_coordinator(postgres_engine, value)
    assert recovered.lifecycle.setup is None
    assert fresh.state is LifecycleState.IDLE
    still_idle = fresh.process_market_event(
        MarketEvent(
            instrument_id=INSTRUMENT,
            exchange_timestamp=value.setup.valid_until + timedelta(minutes=1),
            received_timestamp=value.setup.valid_until + timedelta(minutes=1, milliseconds=1),
            price=Price(Decimal("999")),
            quantity=1,
            source="sf053-golden",
            source_event_id="sf053-after-expiry",
        )
    )
    assert still_idle.state is LifecycleState.IDLE


@pytest.mark.parametrize(
    ("price", "forced", "reason"),
    (
        ("103.10", False, ExitReason.TARGET),
        ("99.90", False, ExitReason.STOP),
        ("101.50", True, ExitReason.FORCED_SESSION_EXIT),
    ),
)
def test_open_restart_exits_persist_and_remain_terminal(
    postgres_engine: Engine,
    price: str,
    forced: bool,
    reason: ExitReason,
) -> None:
    value = facts(f"sf053-exit-{reason.value}-{uuid4().hex[:8]}")
    _persist_open_graph(postgres_engine, value)
    _, coordinator = _recover_coordinator(postgres_engine, value)
    assert coordinator.state is LifecycleState.OPEN

    event_at = (
        value.fill.filled_at.replace(hour=15, minute=15, second=0, microsecond=0)
        if forced
        else value.fill.filled_at + timedelta(minutes=1)
    )
    snapshot = coordinator.process_market_event(
        MarketEvent(
            instrument_id=INSTRUMENT,
            exchange_timestamp=event_at,
            received_timestamp=event_at + timedelta(milliseconds=1),
            price=Price(Decimal(price)),
            quantity=1,
            source="sf053-golden",
            source_event_id=f"sf053-exit-{reason.value}",
        )
    )
    assert snapshot.state is LifecycleState.CLOSED
    assert snapshot.exit is not None
    assert snapshot.exit.reason is reason
    assert snapshot.open_result is not None
    assert snapshot.open_result.trade is not None
    assert snapshot.open_result.position is not None

    trade_transition = next(
        item
        for item in coordinator.audit_transitions
        if item.entity_type is TransitionEntityType.TRADE and item.to_state == "closed"
    )
    position_transition = next(
        item
        for item in coordinator.audit_transitions
        if item.entity_type is TransitionEntityType.POSITION and item.to_state == "closed"
    )
    with Session(postgres_engine) as session:
        PersistenceCoordinator(session).persist_exit(
            exit_fact=snapshot.exit,
            trade=snapshot.open_result.trade,
            position=snapshot.open_result.position,
            trade_transition=trade_transition,
            position_transition=position_transition,
        )

    with Session(postgres_engine) as session:
        final = RecoveryBootstrap().inspect(
            session=session,
            requested_run=value.run,
            instrument_id=INSTRUMENT,
            indicator_requirements=V1_INDICATOR_REQUIREMENTS,
        )
        exits = PostgresExitRepository(session).find_for_run_instrument(
            value.run.run_id, INSTRUMENT
        )
        trades = PostgresTradeRepository(session).find_for_run_instrument(
            value.run.run_id, INSTRUMENT
        )
        positions = PostgresPositionRepository(session).find_for_run_instrument(
            value.run.run_id, INSTRUMENT
        )

    assert len(exits) == len(trades) == len(positions) == 1
    assert exits[0].reason is reason
    assert exits[0].fill_price == Price(Decimal(price))
    assert trades[0].state is TradeState.CLOSED
    assert positions[0].state is PositionState.CLOSED
    assert final.lifecycle.exit_fact == exits[0]

    _, fresh = _recover_coordinator(postgres_engine, value)
    assert fresh.state is LifecycleState.IDLE


def test_pending_trigger_intent_without_fill_remains_fail_closed(
    postgres_engine: Engine,
) -> None:
    value = facts(f"sf053-pending-{uuid4().hex[:8]}")
    _persist_trigger_group(postgres_engine, value)

    with Session(postgres_engine) as session:
        with pytest.raises(
            ContradictoryFactError,
            match="pending triggered entry cannot be resumed safely",
        ):
            RecoveryBootstrap().inspect(
                session=session,
                requested_run=value.run,
                instrument_id=INSTRUMENT,
                indicator_requirements=V1_INDICATOR_REQUIREMENTS,
            )


def test_recovery_reads_are_non_mutating_for_active_graph(
    postgres_engine: Engine,
) -> None:
    value = facts(f"sf053-readonly-{uuid4().hex[:8]}")
    _persist_open_graph(postgres_engine, value)

    with Session(postgres_engine) as session:
        before = {
            "triggers": len(
                PostgresTriggerEventRepository(session).find_for_run_instrument(
                    value.run.run_id, INSTRUMENT
                )
            ),
            "fills": len(
                PostgresFillRepository(session).find_for_run_instrument(
                    value.run.run_id, INSTRUMENT
                )
            ),
            "transitions": len(
                PostgresStateTransitionRepository(session).find_for_run(value.run.run_id)
            ),
        }

    _recover_coordinator(postgres_engine, value)

    with Session(postgres_engine) as session:
        after = {
            "triggers": len(
                PostgresTriggerEventRepository(session).find_for_run_instrument(
                    value.run.run_id, INSTRUMENT
                )
            ),
            "fills": len(
                PostgresFillRepository(session).find_for_run_instrument(
                    value.run.run_id, INSTRUMENT
                )
            ),
            "transitions": len(
                PostgresStateTransitionRepository(session).find_for_run(value.run.run_id)
            ),
        }

    assert after == before
