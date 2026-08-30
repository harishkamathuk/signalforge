"""Immutable exit facts for closing MVP trades and positions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from signalforge.domain.execution import ExecutionMode
from signalforge.domain.ids import (
    ExitId,
    FillId,
    InstrumentId,
    PositionId,
    TradeId,
    deterministic_id,
)
from signalforge.domain.money import Price, Quantity
from signalforge.domain.positions import Position, PositionState
from signalforge.domain.provenance import RunIdentity
from signalforge.domain.time import require_aware
from signalforge.domain.trades import Trade, TradeState


class ExitReason(StrEnum):
    STOP = "stop"
    TARGET = "target"
    FORCED_SESSION_EXIT = "forced_session_exit"


@dataclass(frozen=True, slots=True)
class Exit:
    """Immutable closure fact preserving actual execution separately from theoretical levels."""

    exit_id: ExitId
    exit_fill_id: FillId
    trade_id: TradeId
    position_id: PositionId
    instrument_id: InstrumentId
    reason: ExitReason
    reference_price: Price
    fill_price: Price
    quantity: Quantity
    execution_mode: ExecutionMode
    exited_at: datetime
    realised_pnl: Decimal
    realised_r: Decimal
    run: RunIdentity

    def __post_init__(self) -> None:
        require_aware(self.exited_at)
        if self.reference_price.value <= 0 or self.fill_price.value <= 0:
            raise ValueError("Exit prices must be strictly positive")
        if not self.realised_pnl.is_finite() or not self.realised_r.is_finite():
            raise ValueError("Exit realised values must be finite")
        if self.exit_id != self.expected_id():
            raise ValueError("Exit ID does not match deterministic logical identity")

    @classmethod
    def create(
        cls,
        *,
        trade: Trade,
        position: Position,
        exit_fill_id: FillId,
        reason: ExitReason,
        reference_price: Price,
        fill_price: Price,
        quantity: Quantity,
        execution_mode: ExecutionMode,
        exited_at: datetime,
    ) -> Exit:
        """Create one full-quantity immutable Exit from an OPEN Trade and Position."""

        if trade.state is not TradeState.OPEN:
            raise ValueError("Exit requires an OPEN Trade")
        if position.state is not PositionState.OPEN:
            raise ValueError("Exit requires an OPEN Position")
        if position.trade_id != trade.trade_id:
            raise ValueError("Exit Position must belong to the Trade being closed")
        if position.instrument_id != trade.instrument_id:
            raise ValueError("Exit Trade and Position instrument must match")
        if position.run != trade.run:
            raise ValueError("Exit Trade and Position run provenance must match")
        if quantity != trade.quantity or quantity != position.quantity:
            raise ValueError("Exit quantity must match the full open quantity")
        require_aware(exited_at)
        if exited_at < trade.opened_at or exited_at < position.opened_at:
            raise ValueError("Exit timestamp must not precede Trade/Position open timestamp")
        if reference_price.value <= 0 or fill_price.value <= 0:
            raise ValueError("Exit prices must be strictly positive")

        pnl_per_share = fill_price.value - trade.entry_price.value
        realised_pnl = pnl_per_share * Decimal(quantity.value)
        realised_r = pnl_per_share / trade.risk_per_share.value
        exit_id = deterministic_id(
            ExitId,
            str(trade.run.run_id),
            str(trade.trade_id),
        )
        return cls(
            exit_id=exit_id,
            exit_fill_id=exit_fill_id,
            trade_id=trade.trade_id,
            position_id=position.position_id,
            instrument_id=trade.instrument_id,
            reason=reason,
            reference_price=reference_price,
            fill_price=fill_price,
            quantity=quantity,
            execution_mode=execution_mode,
            exited_at=exited_at,
            realised_pnl=realised_pnl,
            realised_r=realised_r,
            run=trade.run,
        )

    def expected_id(self) -> ExitId:
        return deterministic_id(
            ExitId,
            str(self.run.run_id),
            str(self.trade_id),
        )
