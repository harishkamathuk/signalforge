from datetime import UTC, date, datetime
from decimal import Decimal

from signalforge.domain.ids import InstrumentId
from signalforge.domain.indicators import IndicatorRequirements, RsiRequirement
from signalforge.domain.market import CandleQuality, CompletedCandle
from signalforge.domain.money import Price
from signalforge.domain.prepared_indicators import (
    PreparedIndicatorCheckpoint,
    prepared_checkpoint_id,
)
from signalforge.domain.time import CandleInterval
from signalforge.persistence.mappers import (
    prepared_indicator_checkpoint_from_record,
    prepared_indicator_checkpoint_record_from_domain,
)
from signalforge.runtime.indicators import IndicatorEngine


def test_prepared_checkpoint_mapping_round_trips_canonical_indicator_state() -> None:
    instrument_id = InstrumentId("NSE:TEST")
    requirements = IndicatorRequirements.of(RsiRequirement(14))
    engine = IndicatorEngine(
        instrument_id,
        "engine-v1",
        requirements=requirements,
    )
    interval = CandleInterval.five_minutes(
        datetime(2026, 10, 1, 10, 0, tzinfo=UTC)
    )
    engine.update(
        CompletedCandle(
            instrument_id=instrument_id,
            interval=interval,
            quality=CandleQuality.VALID,
            open=Price(Decimal("100")),
            high=Price(Decimal("101")),
            low=Price(Decimal("99")),
            close=Price(Decimal("100.5")),
            volume=100,
            source="sf073-mapper-test",
            source_event_count=1,
        )
    )
    checkpoint = PreparedIndicatorCheckpoint(
        checkpoint_id=prepared_checkpoint_id(
            instrument_id=instrument_id,
            requirements=requirements,
            calculation_version="engine-v1",
            boundary=interval,
        ),
        state=engine.state,
        exchange="NSE",
        target_trading_date=date(2026, 10, 2),
        historical_source="openalgo:/api/v1/history",
        requested_from=date(2026, 10, 1),
        requested_to=date(2026, 10, 1),
        first_accepted_interval=interval,
        final_accepted_interval=interval,
        accepted_candle_count=1,
        candle_sequence_digest="b" * 64,
        prepared_at=datetime(2026, 10, 2, 2, 30, tzinfo=UTC),
    )

    record = prepared_indicator_checkpoint_record_from_domain(checkpoint)
    restored = prepared_indicator_checkpoint_from_record(record)

    assert restored == checkpoint
