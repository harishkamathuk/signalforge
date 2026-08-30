from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from signalforge.domain.ids import InstrumentId
from signalforge.domain.market import CandleQuality, CompletedCandle, MarketEvent
from signalforge.domain.money import Price
from signalforge.domain.time import CandleInterval

IST = ZoneInfo("Asia/Kolkata")


def _interval() -> CandleInterval:
    return CandleInterval.five_minutes(datetime(2026, 8, 28, 9, 15, tzinfo=IST))


def _candle(**overrides: object) -> CompletedCandle:
    values: dict[str, object] = {
        "instrument_id": InstrumentId("NSE:RELIANCE"),
        "interval": _interval(),
        "quality": CandleQuality.VALID,
        "open": Price(Decimal("1380.00")),
        "high": Price(Decimal("1382.50")),
        "low": Price(Decimal("1379.50")),
        "close": Price(Decimal("1381.75")),
        "volume": 1250,
        "source": "normalized-feed",
        "source_event_count": 24,
    }
    values.update(overrides)
    return CompletedCandle(**values)  # type: ignore[arg-type]


def test_market_event_is_broker_neutral_and_immutable() -> None:
    event = MarketEvent(
        instrument_id=InstrumentId("NSE:RELIANCE"),
        exchange_timestamp=datetime(2026, 8, 28, 9, 16, tzinfo=IST),
        received_timestamp=datetime(2026, 8, 28, 9, 16, 0, 1000, tzinfo=IST),
        price=Price(Decimal("1381.20")),
        quantity=10,
        source="normalized-feed",
        source_event_id="trade-123",
    )

    assert event.quantity == 10
    assert event.source == "normalized-feed"
    with pytest.raises(FrozenInstanceError):
        event.quantity = 11  # type: ignore[misc]


def test_market_event_rejects_naive_timestamps() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        MarketEvent(
            instrument_id=InstrumentId("NSE:RELIANCE"),
            exchange_timestamp=datetime(2026, 8, 28, 9, 16),
            received_timestamp=datetime(2026, 8, 28, 9, 16, tzinfo=IST),
            price=Price(Decimal("1381.20")),
            quantity=10,
            source="normalized-feed",
        )


def test_market_event_requires_positive_price_and_quantity() -> None:
    with pytest.raises(ValueError, match="price must be strictly positive"):
        MarketEvent(
            InstrumentId("NSE:RELIANCE"),
            datetime(2026, 8, 28, 9, 16, tzinfo=IST),
            datetime(2026, 8, 28, 9, 16, tzinfo=IST),
            Price(Decimal("0")),
            10,
            "normalized-feed",
        )

    with pytest.raises(ValueError, match="quantity must be strictly positive"):
        MarketEvent(
            InstrumentId("NSE:RELIANCE"),
            datetime(2026, 8, 28, 9, 16, tzinfo=IST),
            datetime(2026, 8, 28, 9, 16, tzinfo=IST),
            Price(Decimal("1381.20")),
            0,
            "normalized-feed",
        )


def test_completed_candle_is_immutable() -> None:
    candle = _candle()

    with pytest.raises(FrozenInstanceError):
        candle.volume = 1300  # type: ignore[misc]


def test_candle_quality_contains_required_states() -> None:
    assert {quality.value for quality in CandleQuality} == {
        "valid",
        "incomplete",
        "missing",
        "stale",
        "corrupt",
    }


def test_valid_candle_enforces_ohlc_invariants() -> None:
    with pytest.raises(ValueError, match="Candle high"):
        _candle(high=Price(Decimal("1381.00")))

    with pytest.raises(ValueError, match="Candle low"):
        _candle(low=Price(Decimal("1381.90")))


def test_non_missing_candle_requires_complete_ohlcv() -> None:
    with pytest.raises(ValueError, match="complete OHLCV"):
        _candle(close=None)

    with pytest.raises(ValueError, match="complete OHLCV"):
        _candle(volume=None)


def test_candle_volume_must_be_non_negative_integer() -> None:
    with pytest.raises(ValueError, match="must not be negative"):
        _candle(volume=-1)

    with pytest.raises(TypeError, match="must be an integer"):
        _candle(volume=True)


def test_missing_candle_has_no_fabricated_ohlcv() -> None:
    missing = _candle(
        quality=CandleQuality.MISSING,
        open=None,
        high=None,
        low=None,
        close=None,
        volume=None,
        source_event_count=0,
    )

    assert missing.quality is CandleQuality.MISSING
    assert missing.open is None
    assert missing.volume is None


def test_missing_candle_rejects_fabricated_values_or_events() -> None:
    with pytest.raises(ValueError, match="must not fabricate"):
        _candle(quality=CandleQuality.MISSING, source_event_count=0)

    with pytest.raises(ValueError, match="zero source events"):
        _candle(
            quality=CandleQuality.MISSING,
            open=None,
            high=None,
            low=None,
            close=None,
            volume=None,
            source_event_count=1,
        )
