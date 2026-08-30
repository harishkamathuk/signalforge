from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from signalforge.domain.ids import InstrumentId
from signalforge.domain.market import MarketEvent
from signalforge.domain.money import Price
from signalforge.domain.time import IST
from signalforge.runtime.candles import CandleEngine, LateMarketEvent, five_minute_interval


def _event(
    *,
    at: datetime,
    price: str,
    quantity: int = 1,
    instrument_id: InstrumentId = InstrumentId("NSE:TEST"),
    source: str = "test-feed",
) -> MarketEvent:
    return MarketEvent(
        instrument_id=instrument_id,
        exchange_timestamp=at,
        received_timestamp=at,
        price=Price(Decimal(price)),
        quantity=quantity,
        source=source,
    )


def test_five_minute_interval_uses_half_open_nse_boundaries() -> None:
    before_boundary = five_minute_interval(
        datetime(2026, 8, 28, 9, 19, 59, 999999, tzinfo=IST)
    )
    on_boundary = five_minute_interval(datetime(2026, 8, 28, 9, 20, tzinfo=IST))

    assert before_boundary.start == datetime(2026, 8, 28, 9, 15, tzinfo=IST)
    assert before_boundary.end == datetime(2026, 8, 28, 9, 20, tzinfo=IST)
    assert on_boundary.start == datetime(2026, 8, 28, 9, 20, tzinfo=IST)
    assert on_boundary.end == datetime(2026, 8, 28, 9, 25, tzinfo=IST)


def test_equivalent_utc_and_ist_timestamps_map_to_same_interval() -> None:
    ist_at = datetime(2026, 8, 28, 9, 17, 30, tzinfo=IST)
    utc_at = ist_at.astimezone(UTC)

    assert five_minute_interval(ist_at) == five_minute_interval(utc_at)


def test_engine_builds_deterministic_ohlcv_and_emits_on_next_interval() -> None:
    instrument = InstrumentId("NSE:TEST")
    engine = CandleEngine(instrument_id=instrument)

    assert engine.process(_event(at=datetime(2026, 8, 28, 9, 15, tzinfo=IST), price="100", quantity=2)) is None
    assert engine.process(_event(at=datetime(2026, 8, 28, 9, 16, tzinfo=IST), price="102", quantity=3)) is None
    assert engine.process(_event(at=datetime(2026, 8, 28, 9, 18, tzinfo=IST), price="99", quantity=5)) is None
    assert engine.process(_event(at=datetime(2026, 8, 28, 9, 19, tzinfo=IST), price="101", quantity=7)) is None

    candle = engine.process(
        _event(at=datetime(2026, 8, 28, 9, 20, tzinfo=IST), price="103", quantity=11)
    )

    assert candle is not None
    assert candle.instrument_id == instrument
    assert candle.open == Price(Decimal("100"))
    assert candle.high == Price(Decimal("102"))
    assert candle.low == Price(Decimal("99"))
    assert candle.close == Price(Decimal("101"))
    assert candle.volume == 17
    assert candle.source_event_count == 4
    assert candle.source == "test-feed"


def test_gap_does_not_emit_synthetic_empty_candles() -> None:
    engine = CandleEngine(instrument_id=InstrumentId("NSE:TEST"))
    engine.process(_event(at=datetime(2026, 8, 28, 9, 15, tzinfo=IST), price="100"))

    first = engine.process(_event(at=datetime(2026, 8, 28, 9, 30, tzinfo=IST), price="105"))
    assert first is not None
    assert first.interval.start == datetime(2026, 8, 28, 9, 15, tzinfo=IST)
    assert engine.active_interval is not None
    assert engine.active_interval.start == datetime(2026, 8, 28, 9, 30, tzinfo=IST)

    second = engine.process(_event(at=datetime(2026, 8, 28, 9, 35, tzinfo=IST), price="106"))
    assert second is not None
    assert second.interval.start == datetime(2026, 8, 28, 9, 30, tzinfo=IST)


def test_engine_rejects_mixed_instruments() -> None:
    engine = CandleEngine(instrument_id=InstrumentId("NSE:TEST"))

    with pytest.raises(ValueError, match="different instrument"):
        engine.process(
            _event(
                at=datetime(2026, 8, 28, 9, 15, tzinfo=IST),
                price="100",
                instrument_id=InstrumentId("NSE:OTHER"),
            )
        )


def test_late_event_cannot_mutate_or_reemit_completed_candle() -> None:
    engine = CandleEngine(instrument_id=InstrumentId("NSE:TEST"))
    engine.process(_event(at=datetime(2026, 8, 28, 9, 15, tzinfo=IST), price="100"))
    completed = engine.process(
        _event(at=datetime(2026, 8, 28, 9, 20, tzinfo=IST), price="101")
    )
    assert completed is not None

    with pytest.raises(LateMarketEvent):
        engine.process(_event(at=datetime(2026, 8, 28, 9, 19, tzinfo=IST), price="999"))

    next_completed = engine.process(
        _event(at=datetime(2026, 8, 28, 9, 25, tzinfo=IST), price="102")
    )
    assert next_completed is not None
    assert next_completed.open == Price(Decimal("101"))
    assert next_completed.close == Price(Decimal("101"))


def test_engine_rejects_source_changes_within_one_candle() -> None:
    engine = CandleEngine(instrument_id=InstrumentId("NSE:TEST"))
    engine.process(_event(at=datetime(2026, 8, 28, 9, 15, tzinfo=IST), price="100"))

    with pytest.raises(ValueError, match="mix market-event sources"):
        engine.process(
            _event(
                at=datetime(2026, 8, 28, 9, 16, tzinfo=IST),
                price="101",
                source="other-feed",
            )
        )
