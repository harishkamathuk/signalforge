"""Broker-neutral instrument metadata and effective-dated tick-size rules."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from signalforge.domain.ids import InstrumentId
from signalforge.domain.money import Price


@dataclass(frozen=True, slots=True)
class Instrument:
    """Broker-independent identity and market symbol metadata."""

    instrument_id: InstrumentId
    exchange: str
    symbol: str

    def __post_init__(self) -> None:
        if not self.exchange or not self.exchange.strip():
            raise ValueError("Instrument exchange must not be empty")
        if not self.symbol or not self.symbol.strip():
            raise ValueError("Instrument symbol must not be empty")


@dataclass(frozen=True, slots=True)
class TickSizeRule:
    """Tick size effective for an inclusive trading-date range."""

    tick_size: Price
    effective_from: date
    effective_to: date | None = None

    def __post_init__(self) -> None:
        if self.tick_size.value <= 0:
            raise ValueError("Tick size must be strictly positive")
        if self.effective_to is not None and self.effective_to < self.effective_from:
            raise ValueError("Tick-size effective_to must not precede effective_from")

    def applies_on(self, trading_date: date) -> bool:
        """Return whether this rule applies on *trading_date*."""

        if trading_date < self.effective_from:
            return False
        return self.effective_to is None or trading_date <= self.effective_to


@dataclass(frozen=True, slots=True)
class TickSizeSchedule:
    """Deterministic effective-dated tick rules for one instrument."""

    instrument_id: InstrumentId
    rules: tuple[TickSizeRule, ...]

    def __post_init__(self) -> None:
        if not self.rules:
            raise ValueError("TickSizeSchedule requires at least one rule")

        ordered = tuple(sorted(self.rules, key=lambda rule: rule.effective_from))
        for previous, current in zip(ordered, ordered[1:], strict=False):
            if previous.effective_to is None or current.effective_from <= previous.effective_to:
                raise ValueError("Tick-size rules must not overlap")

        object.__setattr__(self, "rules", ordered)

    def tick_size_on(self, trading_date: date) -> Price:
        """Resolve the tick size applicable on *trading_date*."""

        for rule in self.rules:
            if rule.applies_on(trading_date):
                return rule.tick_size
        raise LookupError(f"No tick-size rule for {self.instrument_id} on {trading_date.isoformat()}")
