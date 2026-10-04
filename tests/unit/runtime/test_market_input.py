from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from signalforge.domain.ids import ConfigId, InstrumentId, RunId
from signalforge.domain.market import MarketEvent
from signalforge.domain.money import Price
from signalforge.domain.provenance import RunIdentity, StrategyIdentity
from signalforge.domain.time import IST
from signalforge.runtime.candles import CandleEngine
from signalforge.runtime.market_input import (
    CanonicalMarketInput,
    MarketInputCheckpoint,
    MarketInputDisposition,
    MarketInputGuard,
    MarketInputOrderError,
)
from signalforge.runtime.replay import InMemoryReplaySource

INSTRUMENT = InstrumentId("NSE:SF067")


def _run() -> RunIdentity:
    return RunIdentity(
        run_id=RunId("sf067-market-input-unit"),
        strategy=StrategyIdentity("intraday_momentum_v1", "1.0.0"),
        config_id=ConfigId("sf067-config"),
        config_hash="sf067-hash",
        engine_calculation_version="engine-v1",
    )


def _event(
    sequence: int,
    price: str = "100",
    *,
    source_event_id: str | None = None,
) -> MarketEvent:
    at = datetime(2026, 10, 4, 9, 15, tzinfo=IST) + timedelta(seconds=sequence)
    return MarketEvent(
        instrument_id=INSTRUMENT,
        exchange_timestamp=at,
        received_timestamp=at + timedelta(milliseconds=1),
        price=Price(Decimal(price)),
        quantity=1,
        source="sf067-feed",
        source_event_id=source_event_id,
    )


def _inputs(*events: MarketEvent):
    return tuple(InMemoryReplaySource(instrument_id=INSTRUMENT, events=events))


def _checkpoint(item, state) -> MarketInputCheckpoint:
    canonical = CanonicalMarketInput.from_replay_input(item)
    return MarketInputCheckpoint(
        run=_run(),
        instrument_id=INSTRUMENT,
        last_input=canonical,
        candle_state=state,
        updated_at=item.event.received_timestamp,
    )


def test_guard_accepts_contiguous_input_and_suppresses_exact_latest_duplicate() -> None:
    event0 = _event(0, source_event_id="evt-0")
    event1 = _event(1, source_event_id="evt-1")
    inputs = _inputs(event0, event1)
    engine = CandleEngine(instrument_id=INSTRUMENT)
    engine.process(event0)
    checkpoint = _checkpoint(inputs[0], engine.state)
    guard = MarketInputGuard(
        source_id=inputs[0].source_id,
        checkpoint=checkpoint,
    )

    assert (
        guard.classify(CanonicalMarketInput.from_replay_input(inputs[0]))
        is MarketInputDisposition.DUPLICATE
    )
    assert (
        guard.classify(CanonicalMarketInput.from_replay_input(inputs[1]))
        is MarketInputDisposition.ACCEPT
    )


def test_guard_rejects_regression_gap_and_conflicting_same_sequence() -> None:
    events = tuple(
        _event(index, source_event_id=f"evt-{index}")
        for index in range(4)
    )
    inputs = _inputs(*events)
    engine = CandleEngine(instrument_id=INSTRUMENT)
    for event in events[:2]:
        engine.process(event)
    checkpoint = _checkpoint(inputs[1], engine.state)
    guard = MarketInputGuard(source_id=inputs[0].source_id, checkpoint=checkpoint)

    with pytest.raises(MarketInputOrderError, match="regressed"):
        guard.classify(CanonicalMarketInput.from_replay_input(inputs[0]))

    with pytest.raises(MarketInputOrderError, match="gap"):
        guard.classify(CanonicalMarketInput.from_replay_input(inputs[3]))

    contradictory = CanonicalMarketInput(
        source_id=inputs[1].source_id,
        sequence=inputs[1].sequence,
        source_event_id=inputs[1].event.source_event_id or "",
        payload_fingerprint="different",
    )
    with pytest.raises(MarketInputOrderError, match="contradicts"):
        guard.classify(contradictory)


def test_restart_safe_identity_requires_source_event_id() -> None:
    item = _inputs(_event(0, source_event_id=None))[0]
    with pytest.raises(MarketInputOrderError, match="source_event_id"):
        CanonicalMarketInput.from_replay_input(item)


def test_guard_accepts_source_defined_initial_cursor_without_checkpoint() -> None:
    inputs = _inputs(
        _event(0, source_event_id="evt-0"),
        _event(1, source_event_id="evt-1"),
    )
    guard = MarketInputGuard(source_id=inputs[0].source_id)

    assert (
        guard.classify(CanonicalMarketInput.from_replay_input(inputs[1]))
        is MarketInputDisposition.ACCEPT
    )


@pytest.mark.parametrize(
    ("kwargs", "error_type", "match"),
    (
        (
            {
                "source_id": "",
                "sequence": 0,
                "source_event_id": "evt",
                "payload_fingerprint": "fp",
            },
            ValueError,
            "source_id",
        ),
        (
            {
                "source_id": "source",
                "sequence": True,
                "source_event_id": "evt",
                "payload_fingerprint": "fp",
            },
            TypeError,
            "sequence",
        ),
        (
            {
                "source_id": "source",
                "sequence": -1,
                "source_event_id": "evt",
                "payload_fingerprint": "fp",
            },
            ValueError,
            "negative",
        ),
        (
            {
                "source_id": "source",
                "sequence": 0,
                "source_event_id": "",
                "payload_fingerprint": "fp",
            },
            ValueError,
            "source_event_id",
        ),
        (
            {
                "source_id": "source",
                "sequence": 0,
                "source_event_id": "evt",
                "payload_fingerprint": "",
            },
            ValueError,
            "fingerprint",
        ),
    ),
)
def test_canonical_input_rejects_invalid_identity(
    kwargs: dict[str, object],
    error_type: type[Exception],
    match: str,
) -> None:
    with pytest.raises(error_type, match=match):
        CanonicalMarketInput(**kwargs)  # type: ignore[arg-type]


def test_checkpoint_and_guard_reject_instrument_and_source_mismatches() -> None:
    item = _inputs(_event(0, source_event_id="evt-0"))[0]
    engine = CandleEngine(instrument_id=INSTRUMENT)
    engine.process(item.event)
    canonical = CanonicalMarketInput.from_replay_input(item)

    with pytest.raises(ValueError, match="candle state instrument"):
        MarketInputCheckpoint(
            run=_run(),
            instrument_id=INSTRUMENT,
            last_input=canonical,
            candle_state=CandleEngine(
                instrument_id=InstrumentId("NSE:OTHER")
            ).state,
            updated_at=item.event.received_timestamp,
        )

    checkpoint = _checkpoint(item, engine.state)
    with pytest.raises(MarketInputOrderError, match="persisted market-input source"):
        MarketInputGuard(source_id="other-source", checkpoint=checkpoint)
    with pytest.raises(ValueError, match="source_id"):
        MarketInputGuard(source_id="")

    guard = MarketInputGuard(source_id=item.source_id, checkpoint=checkpoint)
    foreign = CanonicalMarketInput(
        source_id="foreign-source",
        sequence=1,
        source_event_id="evt-1",
        payload_fingerprint="fp",
    )
    with pytest.raises(MarketInputOrderError, match="source identity changed"):
        guard.classify(foreign)

    foreign_checkpoint = MarketInputCheckpoint(
        run=_run(),
        instrument_id=INSTRUMENT,
        last_input=foreign,
        candle_state=engine.state,
        updated_at=item.event.received_timestamp,
    )
    with pytest.raises(MarketInputOrderError, match="accepted checkpoint source"):
        guard.accept(foreign_checkpoint)
