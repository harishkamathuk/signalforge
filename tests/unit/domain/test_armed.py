from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from signalforge.domain.armed import ArmedSetup, ArmedSetupState, ExpiryReason
from signalforge.domain.ids import SignalId
from signalforge.domain.money import Price
from signalforge.domain.states import InvalidStateTransition

IST = ZoneInfo("Asia/Kolkata")


def _setup() -> ArmedSetup:
    armed_at = datetime(2026, 8, 28, 10, 5, tzinfo=IST)
    return ArmedSetup(
        signal_id=SignalId("signal-001"),
        raw_trigger=Price(Decimal("1383.13175")),
        tradable_trigger=Price(Decimal("1383.15")),
        signal_low=Price(Decimal("1379.50")),
        armed_at=armed_at,
        valid_until=armed_at + timedelta(minutes=5),
    )


def test_new_setup_starts_armed_with_immutable_anchors() -> None:
    setup = _setup()

    assert setup.state is ArmedSetupState.ARMED
    assert setup.terminal_at is None
    assert setup.expiry_reason is None

    with pytest.raises(FrozenInstanceError):
        setup.signal_low = Price(Decimal("1378.00"))  # type: ignore[misc]


def test_armed_setup_can_trigger_once() -> None:
    setup = _setup()
    triggered_at = setup.armed_at + timedelta(minutes=1)

    setup.trigger(at=triggered_at)

    assert setup.state is ArmedSetupState.TRIGGERED
    assert setup.terminal_at == triggered_at
    assert setup.expiry_reason is None

    with pytest.raises(InvalidStateTransition):
        setup.expire(at=triggered_at, reason=ExpiryReason.SIGNAL_LOW_BREACH)


def test_armed_setup_can_expire_with_stable_reason() -> None:
    setup = _setup()
    expired_at = setup.valid_until

    setup.expire(at=expired_at, reason=ExpiryReason.VALIDITY_WINDOW_END)

    assert setup.state is ArmedSetupState.EXPIRED
    assert setup.terminal_at == expired_at
    assert setup.expiry_reason is ExpiryReason.VALIDITY_WINDOW_END

    with pytest.raises(InvalidStateTransition):
        setup.trigger(at=expired_at)


def test_expiry_reasons_cover_frozen_v1_causes() -> None:
    assert {reason.value for reason in ExpiryReason} == {
        "signal_low_breach",
        "validity_window_end",
        "entry_cutoff_reached",
    }


def test_trigger_must_be_inside_validity_window() -> None:
    setup = _setup()

    with pytest.raises(ValueError, match="validity window"):
        setup.trigger(at=setup.valid_until)


def test_setup_validates_immutable_price_and_time_anchors() -> None:
    armed_at = datetime(2026, 8, 28, 10, 5, tzinfo=IST)

    with pytest.raises(ValueError, match="valid_until"):
        ArmedSetup(
            signal_id=SignalId("signal-001"),
            raw_trigger=Price(Decimal("100")),
            tradable_trigger=Price(Decimal("100")),
            signal_low=Price(Decimal("99")),
            armed_at=armed_at,
            valid_until=armed_at,
        )

    with pytest.raises(ValueError, match="tradable_trigger"):
        ArmedSetup(
            signal_id=SignalId("signal-001"),
            raw_trigger=Price(Decimal("100.02")),
            tradable_trigger=Price(Decimal("100.00")),
            signal_low=Price(Decimal("99")),
            armed_at=armed_at,
            valid_until=armed_at + timedelta(minutes=5),
        )


def test_setup_rejects_naive_timestamps() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        ArmedSetup(
            signal_id=SignalId("signal-001"),
            raw_trigger=Price(Decimal("100")),
            tradable_trigger=Price(Decimal("100")),
            signal_low=Price(Decimal("99")),
            armed_at=datetime(2026, 8, 28, 10, 5),
            valid_until=datetime(2026, 8, 28, 10, 10, tzinfo=IST),
        )
