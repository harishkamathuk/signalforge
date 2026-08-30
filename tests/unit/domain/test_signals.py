from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from signalforge.domain.ids import ConfigId, InstrumentId, RunId, SignalId
from signalforge.domain.money import Price
from signalforge.domain.provenance import RunIdentity, StrategyIdentity
from signalforge.domain.signals import Signal
from signalforge.domain.time import CandleInterval

IST = ZoneInfo("Asia/Kolkata")


def _run() -> RunIdentity:
    return RunIdentity(
        run_id=RunId("run-001"),
        strategy=StrategyIdentity("intraday_momentum_v1", "1.0.0"),
        config_id=ConfigId("config-001"),
        config_hash="abc123",
        engine_calculation_version="engine-v1",
    )


def _interval() -> CandleInterval:
    return CandleInterval.five_minutes(datetime(2026, 8, 28, 10, 0, tzinfo=IST))


def _signal(**overrides: object) -> Signal:
    values: dict[str, object] = {
        "instrument_id": InstrumentId("NSE:RELIANCE"),
        "interval": _interval(),
        "signal_close": Price(Decimal("1381.75")),
        "signal_low": Price(Decimal("1379.50")),
        "run": _run(),
        "created_at": datetime(2026, 8, 28, 10, 5, tzinfo=IST),
    }
    values.update(overrides)
    return Signal.create(**values)  # type: ignore[arg-type]


def test_signal_is_immutable_and_retains_candle_anchors() -> None:
    signal = _signal()

    assert signal.signal_close == Price(Decimal("1381.75"))
    assert signal.signal_low == Price(Decimal("1379.50"))
    assert signal.run.strategy.strategy_version == "1.0.0"

    with pytest.raises(FrozenInstanceError):
        signal.signal_low = Price(Decimal("1378.00"))  # type: ignore[misc]


def test_signal_identity_is_deterministic_from_logical_facts() -> None:
    first = _signal(created_at=datetime(2026, 8, 28, 10, 5, tzinfo=IST))
    second = _signal(created_at=datetime(2026, 8, 28, 10, 5, 1, tzinfo=IST))

    assert first.signal_id == second.signal_id


def test_signal_identity_changes_when_logical_identity_changes() -> None:
    first = _signal()
    second = _signal(instrument_id=InstrumentId("NSE:TCS"))

    assert first.signal_id != second.signal_id


def test_signal_rejects_non_deterministic_id() -> None:
    valid = _signal()

    with pytest.raises(ValueError, match="deterministic logical identity"):
        Signal(
            signal_id=SignalId("wrong-id"),
            instrument_id=valid.instrument_id,
            interval=valid.interval,
            signal_close=valid.signal_close,
            signal_low=valid.signal_low,
            run=valid.run,
            created_at=valid.created_at,
        )


def test_signal_rejects_naive_creation_timestamp() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        _signal(created_at=datetime(2026, 8, 28, 10, 5))


def test_signal_prices_must_be_positive_and_low_not_above_close() -> None:
    with pytest.raises(ValueError, match="close must be strictly positive"):
        _signal(signal_close=Price(Decimal("0")))

    with pytest.raises(ValueError, match="low must be strictly positive"):
        _signal(signal_low=Price(Decimal("0")))

    with pytest.raises(ValueError, match="low must not exceed signal close"):
        _signal(signal_low=Price(Decimal("1382.00")))


def test_signal_contains_no_mutable_lifecycle_state() -> None:
    field_names = set(Signal.__dataclass_fields__)

    assert "state" not in field_names
    assert "status" not in field_names
    assert "armed" not in field_names
    assert "triggered" not in field_names
