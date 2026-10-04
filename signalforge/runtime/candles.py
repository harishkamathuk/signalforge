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


@dataclass(frozen=True, slots=True)
class CandleEngineState:
    """Lossless immutable state required to resume five-minute aggregation."""

    instrument_id: InstrumentId
    active_interval: CandleInterval | None = None
    source: str | None = None
    open: Price | None = None
    high: Price | None = None
    low: Price | None = None
    close: Price | None = None
    volume: int | None = None
    source_event_count: int = 0
    last_emitted_end: datetime | None = None

    def __post_init__(self) -> None:
        active_values = (
            self.active_interval,
            self.source,
            self.open,
            self.high,
            self.low,
            self.close,
            self.volume,
        )
        has_active = self.active_interval is not None
        if has_active != all(item is not None for item in active_values):
            raise ValueError("CandleEngineState active candle must be complete or absent")
        if not has_active:
            if self.source_event_count != 0:
                raise ValueError("Inactive CandleEngineState must have zero source-event count")
            return

        assert self.active_interval is not None
        assert self.source is not None
        assert self.open is not None
        assert self.high is not None
        assert self.low is not None
        assert self.close is not None
        assert self.volume is not None
        if not self.source.strip():
            raise ValueError("Active CandleEngineState source must not be empty")
        if self.volume < 0:
            raise ValueError("Active CandleEngineState volume must not be negative")
        if self.source_event_count <= 0:
            raise ValueError("Active CandleEngineState requires source events")
        if self.high.value < max(
            self.open.value, self.close.value, self.low.value
        ):
            raise ValueError("Active CandleEngineState high is inconsistent")
        if self.low.value > min(
            self.open.value, self.close.value, self.high.value
        ):
            raise ValueError("Active CandleEngineState low is inconsistent")
        if (
            self.last_emitted_end is not None
            and self.last_emitted_end > self.active_interval.start
        ):
            raise ValueError("CandleEngineState emitted boundary overlaps active interval")


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

    def __init__(
        self,
        *,
        instrument_id: InstrumentId,
        state: CandleEngineState | None = None,
    ) -> None:
        self._instrument_id = instrument_id
        self._active: _ActiveCandle | None = None
        self._last_emitted_end: datetime | None = None
        if state is not None:
            self._restore(state)

    @property
    def instrument_id(self) -> InstrumentId:
        return self._instrument_id

    @property
    def active_interval(self) -> CandleInterval | None:
        return self._active.interval if self._active is not None else None

    @property
    def state(self) -> CandleEngineState:
        active = self._active
        if active is None:
            return CandleEngineState(
                instrument_id=self._instrument_id,
                last_emitted_end=self._last_emitted_end,
            )
        return CandleEngineState(
            instrument_id=self._instrument_id,
            active_interval=active.interval,
            source=active.source,
            open=active.open,
            high=active.high,
            low=active.low,
            close=active.close,
            volume=active.volume,
            source_event_count=active.source_event_count,
            last_emitted_end=self._last_emitted_end,
        )

    def _restore(self, state: CandleEngineState) -> None:
        if state.instrument_id != self._instrument_id:
            raise ValueError("CandleEngineState instrument does not match engine")
        self._last_emitted_end = state.last_emitted_end
        if state.active_interval is None:
            self._active = None
            return
        assert state.source is not None
        assert state.open is not None
        assert state.high is not None
        assert state.low is not None
        assert state.close is not None
        assert state.volume is not None
        self._active = _ActiveCandle(
            interval=state.active_interval,
            source=state.source,
            open=state.open,
            high=state.high,
            low=state.low,
            close=state.close,
            volume=state.volume,
            source_event_count=state.source_event_count,
        )

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
