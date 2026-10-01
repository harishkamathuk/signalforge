from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from signalforge.domain.ids import InstrumentId
from signalforge.domain.indicators import (
    AdxRequirement,
    EmaRequirement,
    IndicatorReading,
    IndicatorRequirements,
    IndicatorSnapshot,
    MacdRequirement,
    RsiRequirement,
)
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
        snapshot.calculation_version = "other"  # type: ignore[misc]


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


def test_legacy_readiness_override_is_preserved_during_migration() -> None:
    snapshot = _ready_snapshot(ready=False)

    assert snapshot.ready is False
    assert snapshot.adx14 is not None


def test_indicator_values_must_be_decimal_when_present() -> None:
    with pytest.raises(TypeError, match="Indicator reading value must be a Decimal"):
        _ready_snapshot(rsi14=61.5)


def test_indicator_values_must_be_finite() -> None:
    with pytest.raises(ValueError, match="Indicator reading value must be finite"):
        _ready_snapshot(macd_line=Decimal("Infinity"))


def test_calculation_version_must_be_non_empty() -> None:
    with pytest.raises(ValueError, match="calculation_version"):
        _ready_snapshot(calculation_version=" ")


def test_ready_must_be_boolean() -> None:
    with pytest.raises(TypeError, match="ready must be a boolean"):
        _ready_snapshot(ready=1)



def test_requirements_are_canonical_and_duplicate_independent() -> None:
    left = IndicatorRequirements.of(
        RsiRequirement(14),
        EmaRequirement(20),
        EmaRequirement(9),
        EmaRequirement(20),
    )
    right = IndicatorRequirements.of(
        EmaRequirement(9),
        EmaRequirement(20),
        RsiRequirement(14),
    )

    assert left == right
    assert left.keys == ("ema:20", "ema:9", "rsi:14")


@pytest.mark.parametrize(
    "factory",
    (
        lambda: RsiRequirement(10),
        lambda: AdxRequirement(10),
        lambda: MacdRequirement(10, 20, 5),
    ),
)
def test_unsupported_canonical_indicator_parameters_fail_fast(factory) -> None:
    with pytest.raises(ValueError):
        factory()


def test_missing_required_reading_fails_explicitly() -> None:
    snapshot = IndicatorSnapshot(
        instrument_id=InstrumentId("NSE:RELIANCE"),
        interval=_interval(),
        calculation_version="indicators-v1",
        readings=(IndicatorReading(RsiRequirement(14), Decimal("61.5")),),
    )

    with pytest.raises(KeyError, match="ema:9"):
        snapshot.ema(9)
