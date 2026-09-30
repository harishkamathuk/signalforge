"""Entry and exit management for the MVP Trade/Position lifecycle."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from enum import StrEnum

from signalforge.domain.execution import ExecutionMode, Fill
from signalforge.domain.exits import Exit, ExitReason
from signalforge.domain.identity import canonical_decimal, canonical_timestamp
from signalforge.domain.ids import FillId, TradeId, deterministic_id
from signalforge.domain.instruments import TickSizeSchedule
from signalforge.domain.market import MarketEvent
from signalforge.domain.money import Price, ceil_to_tick
from signalforge.domain.positions import Position, PositionState
from signalforge.domain.signals import Signal
from signalforge.domain.time import IST
from signalforge.domain.trades import Trade, TradeState
from signalforge.runtime.strategy import PositionEconomics

_FORCED_EXIT_TIME = time(15, 15)


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
    """Own deterministic OPEN and CLOSED Trade/Position transitions."""

    def __init__(self, *, tick_schedule: TickSizeSchedule) -> None:
        self.tick_schedule = tick_schedule
        self._results: dict[FillId, PositionOpenResult] = {}
        self._signals: dict[FillId, str] = {}
        self._economics: dict[FillId, PositionEconomics] = {}
        self._exits: dict[TradeId, Exit] = {}

    def open_from_fill(
        self,
        fill: Fill,
        signal: Signal,
        economics: PositionEconomics,
    ) -> PositionOpenResult:
        """Process one Fill idempotently using accepted strategy economics."""

        self._validate_contract(fill, signal)
        prior = self._results.get(fill.fill_id)
        if prior is not None:
            if self._signals[fill.fill_id] != str(signal.signal_id):
                raise ValueError("Fill was already processed against a different Signal")
            if self._economics[fill.fill_id] != economics:
                raise ValueError("Fill was already processed with different strategy economics")
            return prior

        risk_value = fill.fill_price.value - economics.stop_price.value
        if risk_value <= 0:
            result = PositionOpenResult(
                trade=None,
                position=None,
                rejection=PositionOpenRejection.NON_POSITIVE_RISK,
            )
            self._remember(fill, signal, economics, result)
            return result

        if economics.raw_target_price is None:
            raise ValueError("Positive-risk Fill requires raw target economics")
        trading_date = fill.filled_at.astimezone(IST).date()
        tick_size = self.tick_schedule.tick_size_on(trading_date)
        tradable_target_price = ceil_to_tick(economics.raw_target_price, tick_size)
        trade = Trade.open_from_fill(
            entry_fill=fill,
            stop_price=economics.stop_price,
            raw_target_price=economics.raw_target_price,
            tradable_target_price=tradable_target_price,
        )
        position = Position.open_from_trade(trade=trade)
        result = PositionOpenResult(trade=trade, position=position)
        self._remember(fill, signal, economics, result)
        return result

    def process_market_event(
        self,
        trade: Trade,
        position: Position,
        event: MarketEvent,
        *,
        execution_mode: ExecutionMode = ExecutionMode.PAPER,
    ) -> Exit | None:
        """Close an OPEN long position on the first qualifying ordered market event."""

        prior = self._exits.get(trade.trade_id)
        if prior is not None:
            return prior

        self._validate_exit_contract(trade, position, event)
        reason_reference = self._exit_reason_and_reference(trade, event)
        if reason_reference is None:
            return None
        reason, reference_price = reason_reference

        exit_fill_id = deterministic_id(
            FillId,
            str(trade.run.run_id),
            str(trade.trade_id),
            "exit",
            canonical_timestamp(event.exchange_timestamp),
            canonical_decimal(event.price.value),
            reason.value,
        )
        exit_fact = Exit.create(
            trade=trade,
            position=position,
            exit_fill_id=exit_fill_id,
            reason=reason,
            reference_price=reference_price,
            fill_price=event.price,
            quantity=trade.quantity,
            execution_mode=execution_mode,
            exited_at=event.exchange_timestamp,
        )
        trade.close(exit_id=exit_fact.exit_id, at=exit_fact.exited_at)
        position.close(at=exit_fact.exited_at)
        self._exits[trade.trade_id] = exit_fact
        return exit_fact

    def _exit_reason_and_reference(
        self,
        trade: Trade,
        event: MarketEvent,
    ) -> tuple[ExitReason, Price] | None:
        forced_at = self.forced_exit_at(event.exchange_timestamp)
        if event.exchange_timestamp >= forced_at:
            return ExitReason.FORCED_SESSION_EXIT, event.price
        if event.price.value <= trade.stop_price.value:
            return ExitReason.STOP, trade.stop_price
        if event.price.value >= trade.tradable_target_price.value:
            return ExitReason.TARGET, trade.tradable_target_price
        return None

    @staticmethod
    def forced_exit_at(at: datetime) -> datetime:
        local = at.astimezone(IST)
        return datetime.combine(local.date(), _FORCED_EXIT_TIME, tzinfo=IST)

    def _validate_contract(self, fill: Fill, signal: Signal) -> None:
        if fill.signal_id != signal.signal_id:
            raise ValueError("Fill and Signal identities must match")
        if fill.instrument_id != signal.instrument_id:
            raise ValueError("Fill and Signal instruments must match")
        if fill.run != signal.run:
            raise ValueError("Fill and Signal run provenance must match")
        if self.tick_schedule.instrument_id != fill.instrument_id:
            raise ValueError("TickSizeSchedule instrument must match the Fill")

    def _validate_exit_contract(
        self,
        trade: Trade,
        position: Position,
        event: MarketEvent,
    ) -> None:
        if trade.state is not TradeState.OPEN or position.state is not PositionState.OPEN:
            raise ValueError("Exit evaluation requires OPEN Trade and Position")
        if position.trade_id != trade.trade_id:
            raise ValueError("Position must belong to the Trade being evaluated")
        instruments_mismatch = (
            position.instrument_id != trade.instrument_id
            or event.instrument_id != trade.instrument_id
        )
        if instruments_mismatch:
            raise ValueError("Trade, Position, and MarketEvent instruments must match")
        if position.run != trade.run:
            raise ValueError("Trade and Position run provenance must match")
        if event.exchange_timestamp < trade.opened_at:
            raise ValueError("Exit market event must not precede Trade open timestamp")

    def _remember(
        self,
        fill: Fill,
        signal: Signal,
        economics: PositionEconomics,
        result: PositionOpenResult,
    ) -> None:
        self._results[fill.fill_id] = result
        self._signals[fill.fill_id] = str(signal.signal_id)
        self._economics[fill.fill_id] = economics
