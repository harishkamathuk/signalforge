from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal

import pytest

from signalforge.adapters.openalgo.history import HistoricalCompletedCandle
from signalforge.config.strategy_v1 import StrategyV1EvaluationConfig
from signalforge.domain.ids import InstrumentId
from signalforge.domain.market import CandleQuality
from signalforge.domain.money import Price
from signalforge.domain.time import CandleInterval, IST
from signalforge.runtime.indicators import IndicatorContinuity
from signalforge.runtime.prepared_indicators import (
    PreparedStateError,
    PreparedStateFailureCode,
    build_prepared_checkpoint,
    require_suitable_prepared_checkpoint,
)
from signalforge.runtime.strategy_v1 import IntradayMomentumV1Strategy


INSTRUMENT = InstrumentId("NSE:RELIANCE")
STRATEGY = IntradayMomentumV1Strategy(StrategyV1EvaluationConfig())


def _session_rows(session_date: date) -> list[HistoricalCompletedCandle]:
    start = datetime.combine(session_date, time(9, 15), tzinfo=IST)
    rows: list[HistoricalCompletedCandle] = []
    for offset in range(75):
        close = Decimal("100") + Decimal(offset) / Decimal("100")
        interval_start = start + timedelta(minutes=5 * offset)
        rows.append(
            HistoricalCompletedCandle(
                instrument_id=INSTRUMENT,
                interval=CandleInterval(
                    interval_start,
                    interval_start + timedelta(minutes=5),
                ),
                quality=CandleQuality.VALID,
                open=Price(close),
                high=Price(close + Decimal("1")),
                low=Price(close - Decimal("1")),
                close=Price(close),
                volume=100 + offset,
                source="openalgo:/api/v1/history",
            )
        )
    return rows


def _valid_history() -> tuple[HistoricalCompletedCandle, ...]:
    rows: list[HistoricalCompletedCandle] = []
    for session_date in (
        date(2026, 9, 28),
        date(2026, 9, 29),
        date(2026, 9, 30),
        date(2026, 10, 1),
    ):
        rows.extend(_session_rows(session_date))
    return tuple(rows)


def _checkpoint():
    return build_prepared_checkpoint(
        instrument_id=INSTRUMENT,
        requirements=STRATEGY.indicator_requirements,
        calculation_version="engine-v1",
        target_trading_date=date(2026, 10, 5),
        requested_from=date(2026, 9, 28),
        requested_to=date(2026, 10, 1),
        candles=_valid_history(),
        prepared_at=datetime(2026, 10, 5, 8, 0, tzinfo=IST),
    )


def test_bootstrap_uses_real_indicator_updates_and_is_suitable() -> None:
    checkpoint = _checkpoint()

    assert checkpoint.state.completed_candle_count == 300
    assert checkpoint.state.continuity is IndicatorContinuity.HEALTHY
    assert checkpoint.final_accepted_interval.end == datetime(
        2026, 10, 1, 15, 30, tzinfo=IST
    )
    assert (
        require_suitable_prepared_checkpoint(
            checkpoint,
            target_trading_date=date(2026, 10, 5),
            instrument_id=INSTRUMENT,
            requirements=STRATEGY.indicator_requirements,
            calculation_version="engine-v1",
        )
        is checkpoint
    )


def test_missing_expected_regular_session_bar_fails_closed() -> None:
    rows = list(_valid_history())
    del rows[100]

    with pytest.raises(ValueError, match="continuity"):
        build_prepared_checkpoint(
            instrument_id=INSTRUMENT,
            requirements=STRATEGY.indicator_requirements,
            calculation_version="engine-v1",
            target_trading_date=date(2026, 10, 5),
            requested_from=date(2026, 9, 28),
            requested_to=date(2026, 10, 1),
            candles=rows,
            prepared_at=datetime(2026, 10, 5, 8, 0, tzinfo=IST),
        )


def test_insufficient_history_cannot_create_consumable_checkpoint() -> None:
    rows = tuple(_session_rows(date(2026, 10, 1)))

    with pytest.raises(ValueError, match="fewer than 250"):
        build_prepared_checkpoint(
            instrument_id=INSTRUMENT,
            requirements=STRATEGY.indicator_requirements,
            calculation_version="engine-v1",
            target_trading_date=date(2026, 10, 5),
            requested_from=date(2026, 10, 1),
            requested_to=date(2026, 10, 1),
            candles=rows,
            prepared_at=datetime(2026, 10, 5, 8, 0, tzinfo=IST),
        )


def test_stale_session_checkpoint_has_explicit_failure_code() -> None:
    checkpoint = _checkpoint()

    with pytest.raises(PreparedStateError) as error:
        require_suitable_prepared_checkpoint(
            checkpoint,
            target_trading_date=date(2026, 10, 6),
            instrument_id=INSTRUMENT,
            requirements=STRATEGY.indicator_requirements,
            calculation_version="engine-v1",
        )

    assert error.value.code is PreparedStateFailureCode.PREPARED_STATE_STALE_SESSION
