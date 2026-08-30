"""Deterministic five-minute candle aggregation from normalized market events."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from signalforge.domain.ids import InstrumentId
from signalforge.domain.market import CandleQuality, CompletedCandle, MarketEvent
from signalforge.domain.money import Price
from signalforge.domain.time import CandleInterval, to_ist


class LateMarketEvent(ValueError):
    """Raised when an event belongs to an interval older than the active candle."""


@dataclass(slots=True)
class _ActiveCandle:
    interval: CandleInterval
    source: str
    open: Price
    high: Price
    low: Price
    close: Price
    volume: int
    source_event_count: int

    @classmethod
    def from_event(cls, *, interval: CandleInterval, event: MarketEvent) -> _ActiveCandle:
        return cls(
            interval=interval,
            source=event.source,
            open=event.price,
            high=event.price,
            low=event.price,
            close=event.price,
            volume=event.quantity,
            source_event_count=1,
        )

    def add(self, event: MarketEvent) -> None:
        if event.source != self.source:
            raise ValueError("CandleEngine cannot mix market-event sources within one candle")
        if event.price.value > self.high.value:
            self.high = event.price
        if event.price.value < self.low.value:
            self.low = event.price
        self.close = event.price
        self.volume += event.quantity
        self.source_event_count += 1

    def complete(self, *, instrument_id: InstrumentId) -> CompletedCandle:
        return CompletedCandle(
            instrument_id=instrument_id,
            interval=self.interval,
            quality=CandleQuality.VALID,
            open=self.open,
            high=self.high,
            low=self.low,
            close=self.close,
            volume=self.volume,
            source=self.source,
            source_event_count=self.source_event_count,
        )


def five_minute_interval(exchange_timestamp: datetime) -> CandleInterval:
    """Return the canonical NSE five-minute interval containing an exchange timestamp."""

    local = to_ist(exchange_timestamp)
    start = local.replace(minute=(local.minute // 5) * 5, second=0, microsecond=0)
    return CandleInterval.five_minutes(start)


class CandleEngine:
    """Single-instrument deterministic candle engine for an ordered trade-event stream."""

    def __init__(self, *, instrument_id: InstrumentId) -> None:
        self._instrument_id = instrument_id
        self._active: _ActiveCandle | None = None
        self._last_emitted_end: datetime | None = None

    @property
    def instrument_id(self) -> InstrumentId:
        return self._instrument_id

    @property
    def active_interval(self) -> CandleInterval | None:
        return self._active.interval if self._active is not None else None

    def process(self, event: MarketEvent) -> CompletedCandle | None:
        """Apply one event and emit the prior candle if this event closes its interval."""

        if event.instrument_id != self._instrument_id:
            raise ValueError("CandleEngine received an event for a different instrument")

        interval = five_minute_interval(event.exchange_timestamp)

        if self._active is None:
            if self._last_emitted_end is not None and interval.start < self._last_emitted_end:
                raise LateMarketEvent("Market event belongs to an already-emitted interval")
            self._active = _ActiveCandle.from_event(interval=interval, event=event)
            return None

        if interval.start < self._active.interval.start:
            raise LateMarketEvent("Market event is older than the active candle interval")

        if interval.start == self._active.interval.start:
            self._active.add(event)
            return None

        completed = self._active.complete(instrument_id=self._instrument_id)
        self._last_emitted_end = self._active.interval.end
        self._active = _ActiveCandle.from_event(interval=interval, event=event)
        return completed
