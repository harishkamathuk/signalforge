"""Position exposure lifecycle distinct from Trade economics."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from signalforge.domain.ids import InstrumentId, PositionId, TradeId, deterministic_id
from signalforge.domain.money import Price, Quantity
from signalforge.domain.provenance import RunIdentity
from signalforge.domain.states import InvalidStateTransition
from signalforge.domain.time import require_aware
from signalforge.domain.trades import Trade, TradeState


class PositionState(StrEnum):
    OPEN = "open"
    CLOSED = "closed"


@dataclass(frozen=True, eq=False, slots=True)
class Position:
    """Controlled exposure lifecycle for the MVP's one-trade/one-position model."""

    position_id: PositionId
    trade_id: TradeId
    instrument_id: InstrumentId
    quantity: Quantity
    average_entry_price: Price
    opened_at: datetime
    run: RunIdentity
    state: PositionState = PositionState.OPEN
    closed_at: datetime | None = None

    def __post_init__(self) -> None:
        require_aware(self.opened_at)
        if self.average_entry_price.value <= 0:
            raise ValueError("Position average_entry_price must be strictly positive")
        if self.position_id != self.expected_id():
            raise ValueError("Position ID does not match deterministic logical identity")
        self._validate_state_metadata()

    @classmethod
    def open_from_trade(cls, *, trade: Trade) -> Position:
        """Open the single MVP Position corresponding to an OPEN Trade."""

        if trade.state is not TradeState.OPEN:
            raise InvalidStateTransition("Cannot open Position from a non-OPEN Trade")
        position_id = deterministic_id(
            PositionId,
            str(trade.run.run_id),
            str(trade.trade_id),
        )
        return cls(
            position_id=position_id,
            trade_id=trade.trade_id,
            instrument_id=trade.instrument_id,
            quantity=trade.quantity,
            average_entry_price=trade.entry_price,
            opened_at=trade.opened_at,
            run=trade.run,
        )

    def close(self, *, at: datetime) -> None:
        """Close an OPEN Position exactly once."""

        if self.state is not PositionState.OPEN:
            raise InvalidStateTransition(f"Cannot close Position from state {self.state.value}")
        require_aware(at)
        if at < self.opened_at:
            raise ValueError("Position close timestamp must not precede open timestamp")
        object.__setattr__(self, "state", PositionState.CLOSED)
        object.__setattr__(self, "closed_at", at)

    def expected_id(self) -> PositionId:
        return deterministic_id(
            PositionId,
            str(self.run.run_id),
            str(self.trade_id),
        )

    def _validate_state_metadata(self) -> None:
        if self.closed_at is not None:
            require_aware(self.closed_at)
            if self.closed_at < self.opened_at:
                raise ValueError("Position close timestamp must not precede open timestamp")
        if self.state is PositionState.OPEN:
            if self.closed_at is not None:
                raise ValueError("OPEN Position cannot have closed_at")
        elif self.state is PositionState.CLOSED:
            if self.closed_at is None:
                raise ValueError("CLOSED Position requires closed_at")
