from datetime import UTC, datetime
from decimal import Decimal

import pytest

from signalforge.domain.ids import ConfigId, InstrumentId, RunId
from signalforge.domain.indicators import IndicatorRequirements, RsiRequirement
from signalforge.domain.market import CandleQuality, CompletedCandle
from signalforge.domain.money import Price
from signalforge.domain.provenance import RunIdentity, StrategyIdentity
from signalforge.domain.time import CandleInterval
from signalforge.persistence.mappers import (
    indicator_checkpoint_record_from_state,
    indicator_checkpoint_state_from_record,
)
from signalforge.runtime.indicators import IndicatorEngine


def _run() -> RunIdentity:
    return RunIdentity(
        run_id=RunId("run-sf063-mapper"),
        strategy=StrategyIdentity("test_strategy", "1.0.0"),
        config_id=ConfigId("a" * 64),
        config_hash="a" * 64,
        engine_calculation_version="engine-v1",
    )


def _state():
    instrument_id = InstrumentId("NSE:TEST")
    engine = IndicatorEngine(
        instrument_id,
        "engine-v1",
        requirements=IndicatorRequirements.of(RsiRequirement(14)),
    )
    interval = CandleInterval.five_minutes(datetime(2026, 9, 30, 3, 45, tzinfo=UTC))
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
            source="sf063-mapper-test",
            source_event_count=1,
        )
    )
    return engine.state


def test_generic_checkpoint_rejects_relational_count_payload_mismatch() -> None:
    """Reject disagreement between ordering metadata and recursive component state."""

    state = _state()
    record = indicator_checkpoint_record_from_state(_run(), state)
    record.completed_candle_count = state.completed_candle_count + 1

    with pytest.raises(
        ValueError,
        match="completed-candle count contradicts component state",
    ):
        indicator_checkpoint_state_from_record(record)
