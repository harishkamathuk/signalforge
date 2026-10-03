from __future__ import annotations

from signalforge.config.strategy_v1 import StrategyV1EvaluationConfig
from signalforge.runtime.lifecycle import LifecycleState
from signalforge.runtime.lifecycle_recovery import LifecycleRecoveryHydrator
from signalforge.runtime.recovery import RecoveredLifecycle
from signalforge.runtime.strategy_v1 import IntradayMomentumV1Strategy
from tests.unit.runtime.test_lifecycle_recovery import (
    _coordinator,
    _event,
    _indicator_result,
    _signal_setup,
)


def test_recovered_armed_duplicate_trigger_input_does_not_duplicate_entry() -> None:
    strategy = IntradayMomentumV1Strategy(StrategyV1EvaluationConfig())
    run, signal, setup, transition = _signal_setup(strategy, "sf052-duplicate-trigger")
    coordinator = _coordinator(strategy, run)

    LifecycleRecoveryHydrator().hydrate(
        indicator_result=_indicator_result(strategy),
        recovered=RecoveredLifecycle(
            setup,
            signal,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            (transition,),
        ),
        coordinator=coordinator,
    )

    event = _event("101.20")
    first = coordinator.process_market_event(event)
    second = coordinator.process_market_event(event)

    assert first.state is LifecycleState.OPEN
    assert second.state is LifecycleState.OPEN
    assert first.execution is not None
    assert second.execution is not None
    assert first.execution.entry_intent.entry_intent_id == second.execution.entry_intent.entry_intent_id
    assert first.execution.fill.fill_id == second.execution.fill.fill_id
    assert first.open_result is not None
    assert second.open_result is not None
    assert first.open_result.trade is not None
    assert second.open_result.trade is not None
    assert first.open_result.trade.trade_id == second.open_result.trade.trade_id
    assert first.open_result.position is not None
    assert second.open_result.position is not None
    assert first.open_result.position.position_id == second.open_result.position.position_id
