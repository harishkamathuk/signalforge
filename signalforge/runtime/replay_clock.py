"""Deterministic replay-time boundary dispatch without wall-clock dependence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from signalforge.domain.armed import ArmedSetupState
from signalforge.runtime.lifecycle import LifecycleSnapshot
from signalforge.runtime.replay import ReplayInput
from signalforge.runtime.replay_runtime import ReplayRuntime, ReplayRuntimeStep


@dataclass(frozen=True, slots=True)
class ReplayTimeDispatch:
    """One lifecycle transition caused by historical time progression alone."""

    boundary_at: datetime
    lifecycle: LifecycleSnapshot


@dataclass(frozen=True, slots=True)
class ReplayClockStep:
    """Observable result of advancing time and then processing one replay input."""

    replay_input: ReplayInput
    time_dispatch: ReplayTimeDispatch | None
    runtime_step: ReplayRuntimeStep


class ReplaySessionClock:
    """Advance replay chronology from current historical input only."""

    def __init__(self, *, runtime: ReplayRuntime) -> None:
        self.runtime = runtime
        self._last_event_at: datetime | None = None

    @property
    def last_event_at(self) -> datetime | None:
        return self._last_event_at

    def process_input(self, replay_input: ReplayInput) -> ReplayClockStep:
        """Dispatch crossed time boundaries before applying the current market event."""

        event_at = replay_input.event.exchange_timestamp
        if self._last_event_at is not None and event_at < self._last_event_at:
            raise ValueError("Replay clock input timestamps must be non-decreasing")

        time_dispatch = self._dispatch_time(event_at)
        runtime_step = self.runtime.process_input(replay_input)
        self._last_event_at = event_at
        return ReplayClockStep(
            replay_input=replay_input,
            time_dispatch=time_dispatch,
            runtime_step=runtime_step,
        )

    def run_all(self) -> tuple[ReplayClockStep, ...]:
        """Consume the configured replay source serially through replay time."""

        return tuple(self.process_input(replay_input) for replay_input in self.runtime.source)

    def _dispatch_time(self, event_at: datetime) -> ReplayTimeDispatch | None:
        active = self.runtime.lifecycle.signal_lifecycle.active
        if active is None or active.armed_setup.state is not ArmedSetupState.ARMED:
            return None

        setup = active.armed_setup
        self.runtime.process_time(event_at)
        if setup.state is ArmedSetupState.ARMED:
            return None
        if setup.terminal_at is None:
            raise RuntimeError("Terminal ARMED setup is missing terminal_at")
        return ReplayTimeDispatch(
            boundary_at=setup.terminal_at,
            lifecycle=self.runtime.lifecycle.snapshot(),
        )
