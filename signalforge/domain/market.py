"""Broker-neutral market events and completed candle domain models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from signalforge.domain.ids import InstrumentId
from signalforge.domain.money import Price
from signalforge.domain.time import CandleInterval, require_aware


class CandleQuality(StrEnum):
    """Quality classification for canonical candle data."""

    VALID = "valid"
    INCOMPLETE = "incomplete"
    MISSING = "missing"
    STALE = "stale"
    CORRUPT = "corrupt"


@dataclass(frozen=True, slots=True)
class MarketEvent:
    """Normalized broker-independent observed market trade event."""

    instrument_id: InstrumentId
    exchange_timestamp: datetime
    received_timestamp: datetime
    price: Price
    quantity: int
    source: str
    source_event_id: str | None = None

    def __post_init__(self) -> None:
        require_aware(self.exchange_timestamp)
        require_aware(self.received_timestamp)
        if self.price.value <= 0:
            raise ValueError("MarketEvent price must be strictly positive")
        if isinstance(self.quantity, bool) or not isinstance(self.quantity, int):
            raise TypeError("MarketEvent quantity must be an integer")
        if self.quantity <= 0:
            raise ValueError("MarketEvent quantity must be strictly positive")
        if not self.source or not self.source.strip():
            raise ValueError("MarketEvent source must not be empty")
        if self.source_event_id is not None and not self.source_event_id.strip():
            raise ValueError("MarketEvent source_event_id must not be empty when provided")


@dataclass(frozen=True, slots=True)
class CompletedCandle:
    """Immutable canonical candle fact for one closed interval."""

    instrument_id: InstrumentId
    interval: CandleInterval
    quality: CandleQuality
    open: Price | None
    high: Price | None
    low: Price | None
    close: Price | None
    volume: int | None
    source: str
    source_event_count: int

    def __post_init__(self) -> None:
        if not self.source or not self.source.strip():
            raise ValueError("CompletedCandle source must not be empty")
        if isinstance(self.source_event_count, bool) or not isinstance(self.source_event_count, int):
            raise TypeError("CompletedCandle source_event_count must be an integer")
        if self.source_event_count < 0:
            raise ValueError("CompletedCandle source_event_count must not be negative")

        prices = (self.open, self.high, self.low, self.close)
        if self.quality is CandleQuality.MISSING:
            if any(price is not None for price in prices) or self.volume is not None:
                raise ValueError("MISSING candle must not fabricate OHLCV values")
            if self.source_event_count != 0:
                raise ValueError("MISSING candle must have zero source events")
            return

        if any(price is None for price in prices) or self.volume is None:
            raise ValueError("Non-missing candle requires complete OHLCV values")

        assert self.open is not None
        assert self.high is not None
        assert self.low is not None
        assert self.close is not None
        assert self.volume is not None

        if any(price.value <= 0 for price in (self.open, self.high, self.low, self.close)):
            raise ValueError("Candle prices must be strictly positive")
        if isinstance(self.volume, bool) or not isinstance(self.volume, int):
            raise TypeError("Candle volume must be an integer")
        if self.volume < 0:
            raise ValueError("Candle volume must not be negative")
        if self.high.value < max(self.open.value, self.close.value, self.low.value):
            raise ValueError("Candle high must be at least open, close, and low")
        if self.low.value > min(self.open.value, self.close.value, self.high.value):
            raise ValueError("Candle low must be at most open, close, and high")
