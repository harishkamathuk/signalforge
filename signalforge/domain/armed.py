"""Armed setup lifecycle for qualifying Signal facts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from signalforge.domain.ids import SignalId
from signalforge.domain.money import Price
from signalforge.domain.states import InvalidStateTransition
from signalforge.domain.time import require_aware


class ArmedSetupState(StrEnum):
    ARMED = "armed"
    TRIGGERED = "triggered"
    EXPIRED = "expired"


class ExpiryReason(StrEnum):
    SIGNAL_LOW_BREACH = "signal_low_breach"
    VALIDITY_WINDOW_END = "validity_window_end"
    ENTRY_CUTOFF_REACHED = "entry_cutoff_reached"


@dataclass(frozen=True, slots=True)
class ArmedSetup:
    """Controlled state machine derived from one immutable Signal."""

    signal_id: SignalId
    raw_trigger: Price
    tradable_trigger: Price
    signal_low: Price
    armed_at: datetime
    valid_until: datetime
    state: ArmedSetupState = ArmedSetupState.ARMED
    terminal_at: datetime | None = None
    expiry_reason: ExpiryReason | None = None

    def __post_init__(self) -> None:
        require_aware(self.armed_at)
        require_aware(self.valid_until)
        if self.valid_until <= self.armed_at:
            raise ValueError("ArmedSetup valid_until must be after armed_at")
        if self.raw_trigger.value <= 0 or self.tradable_trigger.value <= 0:
            raise ValueError("ArmedSetup trigger prices must be strictly positive")
        if self.signal_low.value <= 0:
            raise ValueError("ArmedSetup signal_low must be strictly positive")
        if self.tradable_trigger.value < self.raw_trigger.value:
            raise ValueError("ArmedSetup tradable_trigger must not be below raw_trigger")
        self._validate_terminal_metadata()

    def trigger(self, *, at: datetime) -> None:
        self._require_armed()
        require_aware(at)
        if not self.armed_at <= at < self.valid_until:
            raise ValueError("Trigger timestamp must fall within the setup validity window")
        object.__setattr__(self, "state", ArmedSetupState.TRIGGERED)
        object.__setattr__(self, "terminal_at", at)

    def expire(self, *, at: datetime, reason: ExpiryReason) -> None:
        self._require_armed()
        require_aware(at)
        if at < self.armed_at:
            raise ValueError("Expiry timestamp must not precede arming")
        object.__setattr__(self, "state", ArmedSetupState.EXPIRED)
        object.__setattr__(self, "terminal_at", at)
        object.__setattr__(self, "expiry_reason", reason)

    def _require_armed(self) -> None:
        if self.state is not ArmedSetupState.ARMED:
            raise InvalidStateTransition(
                f"Cannot transition ArmedSetup from terminal state {self.state.value}"
            )

    def _validate_terminal_metadata(self) -> None:
        if self.terminal_at is not None:
            require_aware(self.terminal_at)
        if self.state is ArmedSetupState.ARMED:
            if self.terminal_at is not None or self.expiry_reason is not None:
                raise ValueError("ARMED setup cannot have terminal metadata")
        elif self.state is ArmedSetupState.TRIGGERED:
            if self.terminal_at is None or self.expiry_reason is not None:
                raise ValueError("TRIGGERED setup requires terminal_at and no expiry_reason")
        elif self.state is ArmedSetupState.EXPIRED:
            if self.terminal_at is None or self.expiry_reason is None:
                raise ValueError("EXPIRED setup requires terminal_at and expiry_reason")
