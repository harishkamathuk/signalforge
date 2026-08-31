from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from signalforge.domain.ids import InstrumentId
from signalforge.domain.market import MarketEvent
from signalforge.domain.money import Price
from signalforge.domain.time import IST
from signalforge.runtime.replay import InMemoryReplaySource, ReplayInput, ReplaySource

INSTRUMENT = InstrumentId("NSE:RELIANCE")


def _event(
    minute: int,
    *,
    event_id: str,
    instrument_id: InstrumentId = INSTRUMENT,
    price: str = "100.00",
) -> MarketEvent:
    exchange_timestamp = datetime(2026, 8, 31, 9, minute, tzinfo=IST)
    return MarketEvent(
        instrument_id=instrument_id,
        exchange_timestamp=exchange_timestamp,
        received_timestamp=exchange_timestamp + timedelta(milliseconds=1),
        price=Price(Decimal(price)),
        quantity=1,
        source="fixture",
        source_event_id=event_id,
    )


def _consume(source: ReplaySource) -> list[ReplayInput]:
    return list(source)


def test_orders_by_exchange_timestamp_and_preserves_stable_ties() -> None:
    late = _event(17, event_id="late")
    tied_first = _event(16, event_id="tie-first")
    tied_second = _event(16, event_id="tie-second")
    early = _event(15, event_id="early")

    source = InMemoryReplaySource(
        instrument_id=INSTRUMENT,
        events=(late, tied_first, tied_second, early),
    )

    inputs = _consume(source)
    assert [item.event.source_event_id for item in inputs] == [
        "early",
        "tie-first",
        "tie-second",
        "late",
    ]
    assert [item.sequence for item in inputs] == [0, 1, 2, 3]


def test_replay_source_identity_is_deterministic_for_same_normalized_stream() -> None:
    events = (
        _event(17, event_id="late", price="100.20"),
        _event(15, event_id="early", price="99.90"),
    )

    first = InMemoryReplaySource(instrument_id=INSTRUMENT, events=events)
    second = InMemoryReplaySource(instrument_id=INSTRUMENT, events=tuple(reversed(events)))

    assert first.identity == second.identity
    assert first.identity.event_count == 2
    assert all(item.source_id == first.identity.source_id for item in first)


def test_source_identity_changes_when_event_provenance_or_payload_changes() -> None:
    first = InMemoryReplaySource(
        instrument_id=INSTRUMENT,
        events=(_event(15, event_id="evt-1", price="100.00"),),
    )
    changed = InMemoryReplaySource(
        instrument_id=INSTRUMENT,
        events=(_event(15, event_id="evt-2", price="100.00"),),
    )

    assert first.identity.source_id != changed.identity.source_id


def test_rejects_cross_instrument_input() -> None:
    other = InstrumentId("NSE:TCS")

    with pytest.raises(ValueError, match="instrument does not match"):
        InMemoryReplaySource(
            instrument_id=INSTRUMENT,
            events=(
                _event(15, event_id="ok"),
                _event(16, event_id="bad", instrument_id=other),
            ),
        )


def test_empty_source_is_valid_and_deterministic() -> None:
    first = InMemoryReplaySource(instrument_id=INSTRUMENT, events=())
    second = InMemoryReplaySource(instrument_id=INSTRUMENT, events=())

    assert list(first) == []
    assert first.identity == second.identity
    assert first.identity.event_count == 0


def test_iterator_exposes_events_incrementally_without_peek_api() -> None:
    source = InMemoryReplaySource(
        instrument_id=INSTRUMENT,
        events=(
            _event(15, event_id="first"),
            _event(16, event_id="second"),
        ),
    )

    stream = iter(source)
    first = next(stream)
    assert first.event.source_event_id == "first"
    assert not hasattr(stream, "peek")
    second = next(stream)
    assert second.event.source_event_id == "second"
    with pytest.raises(StopIteration):
        next(stream)
