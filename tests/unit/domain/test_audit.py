from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from signalforge.domain.audit import StateTransition, TransitionEntityType
from signalforge.domain.ids import ConfigId, RunId, StateTransitionId
from signalforge.domain.provenance import RunIdentity, StrategyIdentity

IST = ZoneInfo("Asia/Kolkata")


def _run() -> RunIdentity:
    return RunIdentity(
        run_id=RunId("run-001"),
        strategy=StrategyIdentity("intraday_momentum_v1", "1.0.0"),
        config_id=ConfigId("config-001"),
        config_hash="abc123",
        engine_calculation_version="engine-v1",
    )


def _transition() -> StateTransition:
    return StateTransition.create(
        entity_type=TransitionEntityType.ARMED_SETUP,
        entity_id="setup-001",
        from_state="armed",
        to_state="triggered",
        cause_type="trigger_event",
        cause_id="trigger-001",
        occurred_at=datetime(2026, 8, 28, 10, 7, 1, tzinfo=IST),
        run=_run(),
    )


def test_state_transition_is_immutable_and_retains_cause_and_provenance() -> None:
    transition = _transition()

    assert transition.entity_type is TransitionEntityType.ARMED_SETUP
    assert transition.entity_id == "setup-001"
    assert transition.from_state == "armed"
    assert transition.to_state == "triggered"
    assert transition.cause_type == "trigger_event"
    assert transition.cause_id == "trigger-001"
    assert transition.run == _run()

    with pytest.raises(FrozenInstanceError):
        transition.to_state = "expired"  # type: ignore[misc]


def test_transition_identity_is_deterministic_for_same_logical_change() -> None:
    first = _transition()
    second = _transition()

    assert first.transition_id == second.transition_id
    assert isinstance(first.transition_id, StateTransitionId)


def test_transition_identity_is_timezone_representation_independent() -> None:
    ist_transition = _transition()
    utc_transition = StateTransition.create(
        entity_type=ist_transition.entity_type,
        entity_id=ist_transition.entity_id,
        from_state=ist_transition.from_state,
        to_state=ist_transition.to_state,
        cause_type=ist_transition.cause_type,
        cause_id=ist_transition.cause_id,
        occurred_at=ist_transition.occurred_at.astimezone(UTC),
        run=ist_transition.run,
    )

    assert utc_transition.occurred_at != ist_transition.occurred_at
    assert utc_transition.occurred_at.timestamp() == ist_transition.occurred_at.timestamp()
    assert utc_transition.transition_id == ist_transition.transition_id


def test_transition_identity_changes_for_different_cause_or_timestamp() -> None:
    base = _transition()
    different_cause = StateTransition.create(
        entity_type=base.entity_type,
        entity_id=base.entity_id,
        from_state=base.from_state,
        to_state=base.to_state,
        cause_type="session_boundary",
        cause_id="15:05",
        occurred_at=base.occurred_at,
        run=base.run,
    )
    different_time = StateTransition.create(
        entity_type=base.entity_type,
        entity_id=base.entity_id,
        from_state=base.from_state,
        to_state=base.to_state,
        cause_type=base.cause_type,
        cause_id=base.cause_id,
        occurred_at=datetime(2026, 8, 28, 10, 7, 2, tzinfo=IST),
        run=base.run,
    )

    assert different_cause.transition_id != base.transition_id
    assert different_time.transition_id != base.transition_id


def test_all_mvp_mutable_entity_types_are_representable() -> None:
    for entity_type in (
        TransitionEntityType.ARMED_SETUP,
        TransitionEntityType.TRADE,
        TransitionEntityType.POSITION,
    ):
        is_setup = entity_type is TransitionEntityType.ARMED_SETUP
        transition = StateTransition.create(
            entity_type=entity_type,
            entity_id=f"{entity_type.value}-001",
            from_state="armed" if is_setup else "open",
            to_state="expired" if is_setup else "closed",
            cause_type="market_event" if is_setup else "exit",
            cause_id="cause-001",
            occurred_at=datetime(2026, 8, 28, 11, 0, tzinfo=IST),
            run=_run(),
        )

        assert transition.entity_type is entity_type


def test_transition_requires_aware_exchange_timestamp() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        StateTransition.create(
            entity_type=TransitionEntityType.TRADE,
            entity_id="trade-001",
            from_state="open",
            to_state="closed",
            cause_type="exit",
            cause_id="exit-001",
            occurred_at=datetime(2026, 8, 28, 11, 0),
            run=_run(),
        )


def test_transition_requires_non_empty_fields_and_actual_state_change() -> None:
    with pytest.raises(ValueError, match="entity_id"):
        StateTransition.create(
            entity_type=TransitionEntityType.POSITION,
            entity_id=" ",
            from_state="open",
            to_state="closed",
            cause_type="exit",
            cause_id="exit-001",
            occurred_at=datetime(2026, 8, 28, 11, 0, tzinfo=IST),
            run=_run(),
        )

    with pytest.raises(ValueError, match="must change state"):
        StateTransition.create(
            entity_type=TransitionEntityType.TRADE,
            entity_id="trade-001",
            from_state="open",
            to_state="open",
            cause_type="exit",
            cause_id="exit-001",
            occurred_at=datetime(2026, 8, 28, 11, 0, tzinfo=IST),
            run=_run(),
        )


def test_reconstruction_rejects_non_deterministic_transition_id() -> None:
    valid = _transition()

    with pytest.raises(ValueError, match="deterministic logical identity"):
        StateTransition(
            transition_id=StateTransitionId("wrong-id"),
            entity_type=valid.entity_type,
            entity_id=valid.entity_id,
            from_state=valid.from_state,
            to_state=valid.to_state,
            cause_type=valid.cause_type,
            cause_id=valid.cause_id,
            occurred_at=valid.occurred_at,
            run=valid.run,
        )
