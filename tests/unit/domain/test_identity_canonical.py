from datetime import datetime
from decimal import Decimal

from signalforge.domain.execution import TriggerEvent
from signalforge.domain.identity import canonical_decimal, canonical_timestamp
from signalforge.domain.ids import ConfigId, InstrumentId, RunId, SignalId
from signalforge.domain.money import Price
from signalforge.domain.provenance import RunIdentity, StrategyIdentity


def _run() -> RunIdentity:
    return RunIdentity(
        RunId("run"), StrategyIdentity("strategy", "1"), ConfigId("config"), "hash", "engine"
    )


def test_canonical_timestamp_uses_the_instant_not_its_offset() -> None:
    first = datetime.fromisoformat("2026-08-31T10:00:00+05:30")
    second = datetime.fromisoformat("2026-08-31T04:30:00+00:00")
    assert canonical_timestamp(first) == canonical_timestamp(second)
    assert canonical_decimal(Decimal("0")) == canonical_decimal(Decimal("-0.000")) == "0"
    precise = Decimal("1.1234567890123456789012345678901234567890123456789012345")
    assert canonical_decimal(precise) == format(precise, "f")


def test_canonical_decimal_removes_only_insignificant_zeros() -> None:
    assert canonical_decimal(Decimal("156.5")) == canonical_decimal(Decimal("156.5000"))
    assert canonical_decimal(Decimal("1.519480519480519480519480519")) == (
        "1.519480519480519480519480519"
    )


def test_trigger_identity_ignores_timestamp_and_decimal_representation() -> None:
    values = {
        "signal_id": SignalId("signal"),
        "instrument_id": InstrumentId("NSE:X"),
        "reference_price": Price(Decimal("10")),
        "run": _run(),
    }
    first = TriggerEvent.create(
        observed_price=Price(Decimal("156.5")),
        observed_at=datetime.fromisoformat("2026-08-31T10:00:00+05:30"),
        **values,
    )
    second = TriggerEvent.create(
        observed_price=Price(Decimal("156.5000")),
        observed_at=datetime.fromisoformat("2026-08-31T04:30:00+00:00"),
        **values,
    )
    assert first.trigger_event_id == second.trigger_event_id
