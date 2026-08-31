"""Entry-fill to OPEN Trade/Position transition for the MVP lifecycle."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from signalforge.domain.execution import Fill
from signalforge.domain.ids import FillId
from signalforge.domain.instruments import TickSizeSchedule
from signalforge.domain.positions import Position
from signalforge.domain.signals import Signal
from signalforge.domain.time import IST
from signalforge.domain.trades import Trade


class PositionOpenRejection(StrEnum):
    """Deterministic reasons an accepted Fill cannot open a position."""

    NON_POSITIVE_RISK = "non_positive_risk"


@dataclass(frozen=True, slots=True)
class PositionOpenResult:
    """Immutable result of processing one logical entry Fill."""

    trade: Trade | None
    position: Position | None
    rejection: PositionOpenRejection | None = None

    def __post_init__(self) -> None:
        opened = self.trade is not None or self.position is not None
        if opened:
            if self.trade is None or self.position is None:
                raise ValueError("Opened result requires both Trade and Position")
            if self.rejection is not None:
                raise ValueError("Opened result cannot include a rejection")
            if self.position.trade_id != self.trade.trade_id:
                raise ValueError("Position must belong to the produced Trade")
        elif self.rejection is None:
            raise ValueError("Rejected result requires an explicit rejection reason")

    @property
    def opened(self) -> bool:
        return self.trade is not None


class PositionManager:
    """Open one Trade/Position pair from accepted entry-fill evidence."""

    def __init__(self, *, tick_schedule: TickSizeSchedule) -> None:
        self.tick_schedule = tick_schedule
        self._results: dict[FillId, PositionOpenResult] = {}
        self._signals: dict[FillId, str] = {}

    def open_from_fill(self, fill: Fill, signal: Signal) -> PositionOpenResult:
        """Process one Fill idempotently using the signal-candle low as stop."""

        self._validate_contract(fill, signal)
        prior = self._results.get(fill.fill_id)
        if prior is not None:
            if self._signals[fill.fill_id] != str(signal.signal_id):
                raise ValueError("Fill was already processed against a different Signal")
            return prior

        risk_value = fill.fill_price.value - signal.signal_low.value
        if risk_value <= 0:
            result = PositionOpenResult(
                trade=None,
                position=None,
                rejection=PositionOpenRejection.NON_POSITIVE_RISK,
            )
            self._remember(fill, signal, result)
            return result

        trading_date = fill.filled_at.astimezone(IST).date()
        tick_size = self.tick_schedule.tick_size_on(trading_date)
        trade = Trade.open_from_fill(
            entry_fill=fill,
            stop_price=signal.signal_low,
            target_tick_size=tick_size,
        )
        position = Position.open_from_trade(trade=trade)
        result = PositionOpenResult(trade=trade, position=position)
        self._remember(fill, signal, result)
        return result

    def _validate_contract(self, fill: Fill, signal: Signal) -> None:
        if fill.signal_id != signal.signal_id:
            raise ValueError("Fill and Signal identities must match")
        if fill.instrument_id != signal.instrument_id:
            raise ValueError("Fill and Signal instruments must match")
        if fill.run != signal.run:
            raise ValueError("Fill and Signal run provenance must match")
        if self.tick_schedule.instrument_id != fill.instrument_id:
            raise ValueError("TickSizeSchedule instrument must match the Fill")

    def _remember(self, fill: Fill, signal: Signal, result: PositionOpenResult) -> None:
        self._results[fill.fill_id] = result
        self._signals[fill.fill_id] = str(signal.signal_id)
