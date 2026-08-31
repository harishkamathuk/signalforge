from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from signalforge.domain.ids import InstrumentId
from signalforge.domain.market import CandleQuality, CompletedCandle
from signalforge.domain.money import Price
from signalforge.domain.time import CandleInterval
from signalforge.runtime.indicators import (
    IndicatorContinuity,
    IndicatorContinuityBroken,
    IndicatorEngine,
)

_INSTRUMENT = InstrumentId("NSE:TEST")
_VERSION = "indicators-v1"
_START = datetime(2026, 8, 3, 3, 45, tzinfo=UTC)


def _candle(
    index: int,
    *,
    quality: CandleQuality = CandleQuality.VALID,
    start: datetime | None = None,
    instrument_id: InstrumentId = _INSTRUMENT,
) -> CompletedCandle:
    interval = CandleInterval.five_minutes(start or (_START + timedelta(minutes=5 * index)))
    if quality is CandleQuality.MISSING:
        return CompletedCandle(
            instrument_id=instrument_id,
            interval=interval,
            quality=quality,
            open=None,
            high=None,
            low=None,
            close=None,
            volume=None,
            source="test",
            source_event_count=0,
        )
    base = Decimal("100") + Decimal(index) / Decimal("10")
    return CompletedCandle(
        instrument_id=instrument_id,
        interval=interval,
        quality=quality,
        open=Price(base),
        high=Price(base + Decimal("1.25")),
        low=Price(base - Decimal("0.75")),
        close=Price(base + Decimal("0.4")),
        volume=1000 + index,
        source="test",
        source_event_count=5,
    )


def test_partial_and_full_readiness_boundaries() -> None:
    engine = IndicatorEngine(_INSTRUMENT, _VERSION)
    snapshots = [engine.update(_candle(i)) for i in range(50)]

    assert snapshots[24].macd_line is None
    assert snapshots[25].macd_line is not None
    assert snapshots[25].macd_signal is None
    assert snapshots[32].macd_signal is None
    assert snapshots[33].macd_signal is not None
    assert snapshots[33].macd_histogram is not None
    assert snapshots[27].adx14 is not None
    assert snapshots[48].ready is False
    assert snapshots[49].ready is True
    assert snapshots[49].instrument_id == _INSTRUMENT
    assert snapshots[49].interval == _candle(49).interval
    assert snapshots[49].calculation_version == _VERSION


def test_invalid_candle_breaks_continuity_without_advancing_components() -> None:
    engine = IndicatorEngine(_INSTRUMENT, _VERSION)
    engine.update(_candle(0))
    before = engine.state

    with pytest.raises(IndicatorContinuityBroken):
        engine.update(_candle(1, quality=CandleQuality.MISSING))

    after = engine.state
    assert after.continuity is IndicatorContinuity.BROKEN
    assert after.ema9.samples == before.ema9.samples
    assert after.rsi14.samples == before.rsi14.samples
    assert after.adx14.samples == before.adx14.samples
    assert after.macd.samples == before.macd.samples
    with pytest.raises(IndicatorContinuityBroken):
        engine.update(_candle(2))


def test_explicit_upstream_break_does_not_advance() -> None:
    engine = IndicatorEngine(_INSTRUMENT, _VERSION)
    engine.update(_candle(0))
    before = engine.state

    with pytest.raises(IndicatorContinuityBroken):
        engine.update(_candle(1), continuity_ok=False)

    assert engine.state.ema9.samples == before.ema9.samples
    assert engine.continuity is IndicatorContinuity.BROKEN


def test_out_of_order_interval_breaks_continuity() -> None:
    engine = IndicatorEngine(_INSTRUMENT, _VERSION)
    engine.update(_candle(1))

    with pytest.raises(IndicatorContinuityBroken):
        engine.update(_candle(0))

    assert engine.continuity is IndicatorContinuity.BROKEN


def test_legitimate_cross_session_gap_can_continue() -> None:
    engine = IndicatorEngine(_INSTRUMENT, _VERSION)
    first = _candle(0)
    engine.update(first)
    next_session = datetime(2026, 8, 4, 3, 45, tzinfo=UTC)

    snapshot = engine.update(_candle(1, start=next_session))

    assert engine.continuity is IndicatorContinuity.HEALTHY
    assert snapshot.interval.start == next_session
    assert engine.state.ema9.samples == 2


def test_cross_instrument_candle_is_rejected_without_breaking_state() -> None:
    engine = IndicatorEngine(_INSTRUMENT, _VERSION)

    with pytest.raises(ValueError, match="instrument"):
        engine.update(_candle(0, instrument_id=InstrumentId("NSE:OTHER")))

    assert engine.continuity is IndicatorContinuity.HEALTHY
    assert engine.state.ema9.samples == 0


def test_checkpoint_restore_matches_uninterrupted_before_and_after_readiness() -> None:
    candles = [_candle(i) for i in range(65)]
    uninterrupted = IndicatorEngine(_INSTRUMENT, _VERSION)
    expected = [uninterrupted.update(candle) for candle in candles]

    for split in (20, 55):
        first = IndicatorEngine(_INSTRUMENT, _VERSION)
        for candle in candles[:split]:
            first.update(candle)
        restored = IndicatorEngine(_INSTRUMENT, _VERSION, state=first.state)
        actual = [restored.update(candle) for candle in candles[split:]]
        assert actual == expected[split:]
        assert restored.state == uninterrupted.state


def test_batch_and_incremental_outputs_are_identical() -> None:
    candles = [_candle(i) for i in range(60)]
    engine_a = IndicatorEngine(_INSTRUMENT, _VERSION)
    engine_b = IndicatorEngine(_INSTRUMENT, _VERSION)

    outputs_a = [engine_a.update(candle) for candle in candles]
    outputs_b = []
    for candle in candles:
        outputs_b.append(engine_b.update(candle))

    assert outputs_a == outputs_b
    assert engine_a.state == engine_b.state


def test_checkpoint_rejects_mismatched_engine_identity() -> None:
    engine = IndicatorEngine(_INSTRUMENT, _VERSION)
    engine.update(_candle(0))

    with pytest.raises(ValueError, match="instrument"):
        IndicatorEngine(InstrumentId("NSE:OTHER"), _VERSION, state=engine.state)
    with pytest.raises(ValueError, match="version"):
        IndicatorEngine(_INSTRUMENT, "other-version", state=engine.state)
