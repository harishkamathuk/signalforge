"""Deterministic single-security replay input boundary."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from hashlib import sha256
from json import dumps
from typing import Protocol

from signalforge.domain.ids import InstrumentId
from signalforge.domain.market import MarketEvent


@dataclass(frozen=True, slots=True)
class ReplaySourceIdentity:
    """Deterministic identity and provenance for one normalized replay source."""

    source_id: str
    instrument_id: InstrumentId
    event_count: int


@dataclass(frozen=True, slots=True)
class ReplayInput:
    """One canonical replay input exposed to the runtime in deterministic order."""

    event: MarketEvent
    sequence: int
    source_id: str


class ReplaySource(Protocol):
    """Iterator-only contract for consuming canonical historical market inputs."""

    @property
    def identity(self) -> ReplaySourceIdentity: ...

    def __iter__(self) -> Iterator[ReplayInput]: ...


class InMemoryReplaySource:
    """Normalize an in-memory event collection into a deterministic replay stream."""

    def __init__(
        self,
        *,
        instrument_id: InstrumentId,
        events: Iterable[MarketEvent],
    ) -> None:
        indexed_events = tuple(enumerate(events))
        self._validate_instruments(instrument_id, indexed_events)

        ordered_events = tuple(
            event
            for _, event in sorted(
                indexed_events,
                key=lambda item: (item[1].exchange_timestamp, item[0]),
            )
        )
        source_id = _source_id(instrument_id, ordered_events)
        self._identity = ReplaySourceIdentity(
            source_id=source_id,
            instrument_id=instrument_id,
            event_count=len(ordered_events),
        )
        self._inputs = tuple(
            ReplayInput(event=event, sequence=sequence, source_id=source_id)
            for sequence, event in enumerate(ordered_events)
        )

    @property
    def identity(self) -> ReplaySourceIdentity:
        return self._identity

    def __iter__(self) -> Iterator[ReplayInput]:
        return iter(self._inputs)

    @staticmethod
    def _validate_instruments(
        instrument_id: InstrumentId,
        indexed_events: tuple[tuple[int, MarketEvent], ...],
    ) -> None:
        for _, event in indexed_events:
            if event.instrument_id != instrument_id:
                raise ValueError(
                    "Replay source instrument does not match MarketEvent instrument: "
                    f"expected {instrument_id}, got {event.instrument_id}"
                )


def _source_id(instrument_id: InstrumentId, events: tuple[MarketEvent, ...]) -> str:
    payload = {
        "instrument_id": str(instrument_id),
        "events": [
            {
                "exchange_timestamp": event.exchange_timestamp.isoformat(),
                "received_timestamp": event.received_timestamp.isoformat(),
                "price": str(event.price.value),
                "quantity": event.quantity,
                "source": event.source,
                "source_event_id": event.source_event_id,
            }
            for event in events
        ],
    }
    encoded = dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256(encoded).hexdigest()
