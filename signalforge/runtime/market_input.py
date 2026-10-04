"""Restart-safe canonical market-input identity, ordering, and checkpoint state."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from hashlib import sha256
from json import dumps

from signalforge.domain.ids import InstrumentId
from signalforge.domain.market import MarketEvent
from signalforge.domain.provenance import RunIdentity
from signalforge.domain.time import require_aware
from signalforge.runtime.candles import CandleEngineState
from signalforge.runtime.replay import ReplayInput


class MarketInputError(RuntimeError):
    """Base failure for restart-safe canonical market-input processing."""


class MarketInputOrderError(MarketInputError):
    """Raised when input order or identity cannot be proven safely."""


class MarketInputDisposition(StrEnum):
    ACCEPT = "accept"
    DUPLICATE = "duplicate"


@dataclass(frozen=True, slots=True)
class CanonicalMarketInput:
    """Stable source/order identity bound to one immutable market-event payload."""

    source_id: str
    sequence: int
    source_event_id: str
    payload_fingerprint: str

    def __post_init__(self) -> None:
        if not self.source_id.strip():
            raise ValueError("Canonical market-input source_id must not be empty")
        if isinstance(self.sequence, bool) or not isinstance(self.sequence, int):
            raise TypeError("Canonical market-input sequence must be an integer")
        if self.sequence < 0:
            raise ValueError("Canonical market-input sequence must not be negative")
        if not self.source_event_id.strip():
            raise ValueError("Canonical market-input source_event_id must not be empty")
        if not self.payload_fingerprint.strip():
            raise ValueError("Canonical market-input fingerprint must not be empty")

    @classmethod
    def from_replay_input(cls, replay_input: ReplayInput) -> CanonicalMarketInput:
        event = replay_input.event
        if event.source_event_id is None:
            raise MarketInputOrderError(
                "restart-safe market input requires stable source_event_id"
            )
        return cls(
            source_id=replay_input.source_id,
            sequence=replay_input.sequence,
            source_event_id=event.source_event_id,
            payload_fingerprint=market_event_fingerprint(event),
        )


@dataclass(frozen=True, slots=True)
class MarketInputCheckpoint:
    """Authoritative current input progress plus exact forming-candle state."""

    run: RunIdentity
    instrument_id: InstrumentId
    last_input: CanonicalMarketInput
    candle_state: CandleEngineState
    updated_at: datetime

    def __post_init__(self) -> None:
        require_aware(self.updated_at)
        if self.candle_state.instrument_id != self.instrument_id:
            raise ValueError(
                "MarketInputCheckpoint candle state instrument does not match checkpoint"
            )


def market_event_fingerprint(event: MarketEvent) -> str:
    """Return a deterministic hash over the immutable normalized event payload."""

    payload = {
        "instrument_id": str(event.instrument_id),
        "exchange_timestamp": event.exchange_timestamp.isoformat(),
        "received_timestamp": event.received_timestamp.isoformat(),
        "price": str(event.price.value),
        "quantity": event.quantity,
        "source": event.source,
        "source_event_id": event.source_event_id,
    }
    encoded = dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256(encoded).hexdigest()


class MarketInputGuard:
    """Classify one canonical input before any lifecycle or candle mutation."""

    def __init__(
        self,
        *,
        source_id: str,
        checkpoint: MarketInputCheckpoint | None = None,
    ) -> None:
        if not source_id.strip():
            raise ValueError("MarketInputGuard source_id must not be empty")
        if checkpoint is not None and checkpoint.last_input.source_id != source_id:
            raise MarketInputOrderError(
                "persisted market-input source contradicts configured source"
            )
        self._source_id = source_id
        self._checkpoint = checkpoint

    @property
    def checkpoint(self) -> MarketInputCheckpoint | None:
        return self._checkpoint

    def classify(self, item: CanonicalMarketInput) -> MarketInputDisposition:
        if item.source_id != self._source_id:
            raise MarketInputOrderError("market-input source identity changed unexpectedly")
        checkpoint = self._checkpoint
        if checkpoint is None:
            if item.sequence != 0:
                raise MarketInputOrderError(
                    "restart-safe market input must begin at sequence zero"
                )
            return MarketInputDisposition.ACCEPT

        last = checkpoint.last_input
        if item.sequence == last.sequence:
            if (
                item.source_event_id == last.source_event_id
                and item.payload_fingerprint == last.payload_fingerprint
            ):
                return MarketInputDisposition.DUPLICATE
            raise MarketInputOrderError(
                "same market-input sequence contradicts persisted identity or payload"
            )
        if item.sequence < last.sequence:
            raise MarketInputOrderError("market-input sequence regressed")
        if item.sequence != last.sequence + 1:
            raise MarketInputOrderError("market-input sequence gap cannot be proven safe")
        return MarketInputDisposition.ACCEPT

    def accept(self, checkpoint: MarketInputCheckpoint) -> None:
        if checkpoint.last_input.source_id != self._source_id:
            raise MarketInputOrderError("accepted checkpoint source identity changed")
        self._checkpoint = checkpoint
