from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from signalforge.domain.ids import InstrumentId
from signalforge.domain.indicators import IndicatorSnapshot
from signalforge.domain.time import CandleInterval

IST = ZoneInfo("Asia/Kolkata")


def _interval() -> CandleInterval:
    return CandleInterval.five_minutes(datetime(2026, 8, 28, 9, 20, tzinfo=IST))


def _ready_snapshot(**overrides: object) -> IndicatorSnapshot:
    values: dict[str, object] = {
        "instrument_id": InstrumentId("NSE:RELIANCE"),
        "interval": _interval(),
        "ready": True,
        "calculation_version": "indicators-v1",
        "ema9": Decimal("1380.10"),
        "ema20": Decimal("1378.20"),
        "ema50": Decimal("1370.00"),
        "rsi14": Decimal("61.5"),
        "adx14": Decimal("25.2"),
        "macd_line": Decimal("2.4"),
        "macd_signal": Decimal("1.8"),
        "macd_histogram": Decimal("0.6"),
    }
    values.update(overrides)
    return IndicatorSnapshot(**values)  # type: ignore[arg-type]


def test_ready_snapshot_is_immutable_and_retains_version() -> None:
    snapshot = _ready_snapshot()

    assert snapshot.ready is True
    assert snapshot.calculation_version == "indicators-v1"
    assert snapshot.rsi14 == Decimal("61.5")

    with pytest.raises(FrozenInstanceError):
        snapshot.ready = False  # type: ignore[misc]


def test_unready_snapshot_may_contain_partial_seeded_values() -> None:
    snapshot = IndicatorSnapshot(
        instrument_id=InstrumentId("NSE:RELIANCE"),
        interval=_interval(),
        ready=False,
        calculation_version="indicators-v1",
        ema9=Decimal("1380.10"),
        ema20=Decimal("1378.20"),
    )

    assert snapshot.ready is False
    assert snapshot.ema9 == Decimal("1380.10")
    assert snapshot.adx14 is None


def test_ready_snapshot_requires_complete_indicator_set() -> None:
    with pytest.raises(ValueError, match="requires all indicator values"):
        _ready_snapshot(adx14=None)


def test_readiness_is_not_inferred_from_non_null_values() -> None:
    snapshot = _ready_snapshot(ready=False)

    assert snapshot.ready is False
    assert snapshot.adx14 is not None


def test_indicator_values_must_be_decimal_when_present() -> None:
    with pytest.raises(TypeError, match="rsi14 must be a Decimal"):
        _ready_snapshot(rsi14=61.5)


def test_indicator_values_must_be_finite() -> None:
    with pytest.raises(ValueError, match="macd_line must be finite"):
        _ready_snapshot(macd_line=Decimal("Infinity"))


def test_calculation_version_must_be_non_empty() -> None:
    with pytest.raises(ValueError, match="calculation_version"):
        _ready_snapshot(calculation_version=" ")


def test_ready_must_be_boolean() -> None:
    with pytest.raises(TypeError, match="ready must be a boolean"):
        _ready_snapshot(ready=1)
