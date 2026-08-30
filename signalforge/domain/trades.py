"""Trade economic lifecycle and immutable entry economics."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from signalforge.domain.execution import Fill
from signalforge.domain.ids import ExitId, FillId, InstrumentId, SignalId, TradeId, deterministic_id
from signalforge.domain.money import Price, Quantity, ceil_to_tick
from signalforge.domain.provenance import RunIdentity
from signalforge.domain.states import InvalidStateTransition
from signalforge.domain.time import require_aware


class TradeState(StrEnum):
    OPEN = "open"
    CLOSED = "closed"


@dataclass(frozen=True, eq=False, slots=True)
class Trade:
    """Controlled trade lifecycle with economics frozen from the accepted entry fill."""

    trade_id: TradeId
    entry_fill_id: FillId
    signal_id: SignalId
    instrument_id: InstrumentId
    entry_price: Price
    stop_price: Price
    raw_target_price: Price
    tradable_target_price: Price
    risk_per_share: Price
    quantity: Quantity
    opened_at: datetime
    run: RunIdentity
    state: TradeState = TradeState.OPEN
    closed_at: datetime | None = None
    exit_id: ExitId | None = None

    def __post_init__(self) -> None:
        require_aware(self.opened_at)
        if self.entry_price.value <= 0 or self.stop_price.value <= 0:
            raise ValueError("Trade entry and stop prices must be strictly positive")
        expected_risk = self.entry_price.value - self.stop_price.value
        if expected_risk <= 0:
            raise ValueError("Trade risk_per_share must be strictly positive before OPEN")
        if self.risk_per_share.value != expected_risk:
            raise ValueError("Trade risk_per_share must equal actual fill minus stop")
        expected_raw_target = self.entry_price.value + Decimal("1.5") * expected_risk
        if self.raw_target_price.value != expected_raw_target:
            raise ValueError("Trade raw target must equal entry plus 1.5R")
        if self.tradable_target_price.value < self.raw_target_price.value:
            raise ValueError("Trade tradable target must not be below raw target")
        if self.trade_id != self.expected_id():
            raise ValueError("Trade ID does not match deterministic logical identity")
        self._validate_state_metadata()

    @classmethod
    def open_from_fill(
        cls,
        *,
        entry_fill: Fill,
        stop_price: Price,
        target_tick_size: Price,
    ) -> Trade:
        """Open a trade from an accepted entry fill using actual-fill economics."""

        risk_value = entry_fill.fill_price.value - stop_price.value
        if risk_value <= 0:
            raise ValueError("Trade risk_per_share must be strictly positive before OPEN")
        risk = Price(risk_value)
        raw_target = Price(entry_fill.fill_price.value + Decimal("1.5") * risk_value)
        tradable_target = ceil_to_tick(raw_target, target_tick_size)
        trade_id = deterministic_id(
            TradeId,
            str(entry_fill.run.run_id),
            str(entry_fill.fill_id),
        )
        return cls(
            trade_id=trade_id,
            entry_fill_id=entry_fill.fill_id,
            signal_id=entry_fill.signal_id,
            instrument_id=entry_fill.instrument_id,
            entry_price=entry_fill.fill_price,
            stop_price=stop_price,
            raw_target_price=raw_target,
            tradable_target_price=tradable_target,
            risk_per_share=risk,
            quantity=entry_fill.quantity,
            opened_at=entry_fill.filled_at,
            run=entry_fill.run,
        )

    def close(self, *, exit_id: ExitId, at: datetime) -> None:
        """Close an OPEN trade exactly once using an immutable exit reference."""

        if self.state is not TradeState.OPEN:
            raise InvalidStateTransition(f"Cannot close Trade from state {self.state.value}")
        require_aware(at)
        if at < self.opened_at:
            raise ValueError("Trade close timestamp must not precede open timestamp")
        object.__setattr__(self, "state", TradeState.CLOSED)
        object.__setattr__(self, "closed_at", at)
        object.__setattr__(self, "exit_id", exit_id)

    def expected_id(self) -> TradeId:
        return deterministic_id(
            TradeId,
            str(self.run.run_id),
            str(self.entry_fill_id),
        )

    def _validate_state_metadata(self) -> None:
        if self.closed_at is not None:
            require_aware(self.closed_at)
            if self.closed_at < self.opened_at:
                raise ValueError("Trade close timestamp must not precede open timestamp")
        if self.state is TradeState.OPEN:
            if self.closed_at is not None or self.exit_id is not None:
                raise ValueError("OPEN trade cannot have close metadata")
        elif self.state is TradeState.CLOSED:
            if self.closed_at is None or self.exit_id is None:
                raise ValueError("CLOSED trade requires closed_at and exit_id")
