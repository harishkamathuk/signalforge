"""Synthetic-only tests of SF-097 possible-world state propagation."""

from decimal import Decimal as D

import pytest

from signalforge.research.historical_possible_worlds import (
    Lifecycle,
    Position,
    PropagationPolicy,
    PropagationResult,
    SupportedTransition,
    TransitionKind,
    World,
    propagate,
)


def _setup() -> Position:
    return Position("first", D("98"), D("100.1"))


def _open() -> Position:
    return Position("first", D("98"), D("100.1"), D("103.3"), D("100.2"))


def _arm_first() -> PropagationResult:
    return propagate(
        PropagationResult((World(),), 0), "2025-11-24T02:25Z",
        lambda _: (SupportedTransition(TransitionKind.ARM, "qualified", _setup()),),
        PropagationPolicy(),
    )


def _ambiguous() -> PropagationResult:
    return propagate(
        _arm_first(), "2025-11-24T02:30Z",
        lambda _: (
            SupportedTransition(TransitionKind.EXPIRE, "invalidation_before_entry"),
            SupportedTransition(
                TransitionKind.ENTER, "entry_before_invalidation_possible", _open()
            ),
        ),
        PropagationPolicy(),
    )


def test_sf096_expired_or_open_possible_histories_are_distinct() -> None:
    first = _ambiguous()
    assert first.complete
    assert {w.lifecycle for w in first.worlds} == {Lifecycle.FLAT, Lifecycle.OPEN}
    assert first == _ambiguous()
    assert len({w.identity for w in first.worlds}) == 2
    assert all(w.events[-1].minute_key == "2025-11-24T02:30Z" for w in first.worlds)


def test_later_completed_signal_can_arm_only_flat_branch() -> None:
    new_setup = Position("second", D("101"), D("102"))

    def resolve(w: World) -> tuple[SupportedTransition, ...]:
        if w.lifecycle is Lifecycle.FLAT:
            return (SupportedTransition(TransitionKind.ARM, "next_completed_signal", new_setup),)
        return (SupportedTransition(TransitionKind.BLOCK, "already_open"),)

    later = propagate(_ambiguous(), "2025-11-24T02:35Z", resolve, PropagationPolicy())
    assert {w.lifecycle for w in later.worlds} == {Lifecycle.ARMED, Lifecycle.OPEN}
    assert {w.position.signal_id for w in later.worlds if w.position} == {
        "first", "second"
    }
    assert later == propagate(_ambiguous(), "2025-11-24T02:35Z", resolve, PropagationPolicy())


def test_converging_flat_states_preserve_different_economic_histories() -> None:
    closed = propagate(
        _ambiguous(), "2025-11-24T02:36Z",
        lambda w: (
            (SupportedTransition(TransitionKind.EXIT, "stop_reached", outcome_r=D("-1")),)
            if w.lifecycle is Lifecycle.OPEN else
            (SupportedTransition(TransitionKind.NOOP, "no_position"),)
        ),
        PropagationPolicy(),
    )
    assert all(w.lifecycle is Lifecycle.FLAT for w in closed.worlds)
    assert len({w.identity for w in closed.worlds}) == 2
    assert sum(any(e.outcome_r == D("-1") for e in w.events) for w in closed.worlds) == 1


def test_second_ambiguity_keeps_stop_target_alternatives() -> None:
    result = propagate(
        _ambiguous(), "2025-11-24T02:36Z",
        lambda w: (
            (SupportedTransition(TransitionKind.EXIT, "stop_possible", outcome_r=D("-1")),
             SupportedTransition(TransitionKind.EXIT, "target_possible", outcome_r=D("1.5")))
            if w.lifecycle is Lifecycle.OPEN else
            (SupportedTransition(TransitionKind.NOOP, "flat"),)
        ),
        PropagationPolicy(),
    )
    assert len(result.worlds) == 3
    assert {e.outcome_r for w in result.worlds for e in w.events
            if e.outcome_r is not None} == {D("-1"), D("1.5")}


def test_budget_exhaustion_produces_only_unresolved_not_pruned_worlds() -> None:
    result = propagate(
        _ambiguous(), "2025-11-24T02:36Z",
        lambda w: (
            (SupportedTransition(TransitionKind.EXIT, "stop", outcome_r=D("-1")),
             SupportedTransition(TransitionKind.EXIT, "target", outcome_r=D("1.5")))
            if w.lifecycle is Lifecycle.OPEN else
            (SupportedTransition(TransitionKind.NOOP, "flat"),)
        ),
        PropagationPolicy(max_worlds=2),
    )
    assert not result.complete
    assert result.worlds == ()
    assert result.unresolved_at == "2025-11-24T02:36Z"
    assert result.unresolved_reason == "world_budget_exhausted"
    with pytest.raises(ValueError, match="cannot resume"):
        propagate(result, "2025-11-24T02:37Z", lambda _: (), PropagationPolicy())


def test_transition_budget_invalid_armless_entry_and_second_position() -> None:
    exhausted = propagate(
        _ambiguous(), "2025-11-24T02:36Z",
        lambda _: (SupportedTransition(TransitionKind.KEEP, "unchanged"),),
        PropagationPolicy(max_total_transitions=2),
    )
    assert exhausted.unresolved_reason == "transition_budget_exhausted"
    with pytest.raises(ValueError, match="unsupported"):
        propagate(
            _ambiguous(), "2025-11-24T02:36Z",
            lambda _: (SupportedTransition(TransitionKind.ARM, "illegal", _setup()),),
            PropagationPolicy(),
        )
    with pytest.raises(ValueError, match="positive risk"):
        Position("bad", D("99"), D("100"), D("101"), D("98"))


def test_utc_midnight_is_not_automatic_lifecycle_reset() -> None:
    def resolve(w: World) -> tuple[SupportedTransition, ...]:
        return (SupportedTransition(
            TransitionKind.NOOP if w.lifecycle is Lifecycle.FLAT else TransitionKind.KEEP,
            "normal_utc_boundary",
        ),)

    midnight = propagate(_ambiguous(), "2025-11-25T00:00Z", resolve, PropagationPolicy())
    assert {w.lifecycle for w in midnight.worlds} == {Lifecycle.FLAT, Lifecycle.OPEN}
    assert midnight == propagate(_ambiguous(), "2025-11-25T00:00Z", resolve,
                                 PropagationPolicy())
    assert any(w.lifecycle is Lifecycle.OPEN for w in midnight.worlds)


def test_unknown_reordered_and_contradictory_state_rejected() -> None:
    with pytest.raises(ValueError, match="increase strictly"):
        propagate(_ambiguous(), "2025-11-24T02:30Z", lambda _: (), PropagationPolicy())
    with pytest.raises(ValueError, match="all supported"):
        propagate(_ambiguous(), "2025-11-24T02:36Z", lambda _: (), PropagationPolicy())
    with pytest.raises(ValueError, match="exactly one"):
        World(Lifecycle.OPEN)
