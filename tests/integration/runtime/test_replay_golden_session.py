from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from signalforge.cli import replay_command
from signalforge.domain.time import IST

CONFIG = Path("examples/replay/golden-config.json")
SESSION_DATES = (
    date(2026, 8, 26),
    date(2026, 8, 27),
    date(2026, 8, 28),
    date(2026, 8, 31),
)
_PATTERN = (
    Decimal("0.6"),
    Decimal("-0.4"),
    Decimal("0.6"),
    Decimal("-0.4"),
    Decimal("0.2"),
)


def _golden_closes() -> list[Decimal]:
    closes = [Decimal("100.0")]
    switch = 271
    for index in range(1, 300):
        delta = (
            Decimal("0.2")
            if index < switch
            else _PATTERN[(index - switch + 1) % len(_PATTERN)]
        )
        closes.append(closes[-1] + delta)

    # The accepted V1 rules first qualify on the final session's 14:55-15:00 candle.
    # Subsequent observed prices trigger the setup, stay inside stop/target, then provide
    # the first real trade/LTP at 15:15 for the forced-session exit.
    closes[294:] = [
        Decimal("156.3"),
        Decimal("156.6"),
        Decimal("156.6"),
        Decimal("156.7"),
        Decimal("156.7"),
        Decimal("156.7"),
    ]
    return closes


def _event_payload(at: datetime, price: Decimal, source_event_id: str) -> dict[str, object]:
    return {
        "exchange_timestamp": at.isoformat(),
        "received_timestamp": (at + timedelta(milliseconds=1)).isoformat(),
        "price": format(price, "f"),
        "quantity": 1,
        "source": "golden-fixture",
        "source_event_id": source_event_id,
    }


def _golden_events() -> list[dict[str, object]]:
    closes = _golden_closes()
    events: list[dict[str, object]] = []
    index = 0

    for session_date in SESSION_DATES:
        start = datetime.combine(session_date, datetime.min.time(), tzinfo=IST).replace(
            hour=9,
            minute=15,
        )
        for candle_index in range(75):
            at = start + timedelta(minutes=5 * candle_index)
            events.append(_event_payload(at, closes[index], f"g{index:03d}"))
            if index == 294:
                events.append(
                    _event_payload(
                        at + timedelta(seconds=1),
                        Decimal("156.5"),
                        "g-trigger",
                    )
                )
            index += 1

    # Completes the final 15:25-15:30 regular-session candle. The newly active
    # 15:30 interval is never emitted, so no post-session candle is invented.
    final_boundary = datetime(2026, 8, 31, 15, 30, tzinfo=IST)
    events.append(
        _event_payload(final_boundary, Decimal("156.7"), "g-final-boundary")
    )
    return events


def _write_events(tmp_path: Path, events: list[dict[str, object]]) -> Path:
    path = tmp_path / "golden-events.json"
    path.write_text(json.dumps(events, indent=2), encoding="utf-8")
    return path


def test_complete_session_replay_produces_one_closed_trade_deterministically(
    tmp_path: Path,
) -> None:
    events_path = _write_events(tmp_path, _golden_events())

    first = replay_command(CONFIG, events_path)
    second = replay_command(CONFIG, events_path)

    assert first == second
    assert first["events"] == 302
    assert first["evaluations"] == 300
    assert first["signals"] == 1
    assert first["trades"] == 1
    assert first["exits"] == 1
    assert first["open_rejections"] == 0
    assert first["qualified"] == 1
    assert first["actionable"] == 1
    assert first["final_lifecycle_state"] == "closed"
    assert first["run_id"] == second["run_id"]
    assert first["source_id"] == second["source_id"]


def test_overnight_gaps_do_not_create_synthetic_completed_candles(tmp_path: Path) -> None:
    events_path = _write_events(tmp_path, _golden_events())

    summary = replay_command(CONFIG, events_path)

    # Four complete regular sessions x 75 five-minute candles.
    assert summary["evaluations"] == 300
    assert summary["events"] == 302


def test_golden_fixture_has_no_pre_signal_actionable_decisions(tmp_path: Path) -> None:
    events_path = _write_events(tmp_path, _golden_events())

    summary = replay_command(CONFIG, events_path)

    assert summary["qualified"] == 1
    assert summary["actionable"] == 1
    assert summary["signals"] == 1


def test_malformed_replay_input_fails_explicitly(tmp_path: Path) -> None:
    malformed = tmp_path / "malformed.json"
    malformed.write_text(
        json.dumps(
            [
                {
                    "exchange_timestamp": "not-a-timestamp",
                    "received_timestamp": "2026-08-31T10:00:00.001+05:30",
                    "price": "100.00",
                    "quantity": 1,
                    "source": "malformed",
                }
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(Exception):
        replay_command(CONFIG, malformed)
