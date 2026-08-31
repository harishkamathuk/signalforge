from __future__ import annotations

import json
from pathlib import Path

from signalforge.cli import main, replay_command


def _write(path: Path, payload: object) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _config(tmp_path: Path) -> Path:
    return _write(
        tmp_path / "config.json",
        {
            "instrument_id": "NSE:RELIANCE",
            "quantity": 10,
            "engine_calculation_version": "engine-v1",
            "tick_rules": [
                {
                    "tick_size": "0.10",
                    "effective_from": "2026-01-01",
                }
            ],
            "strategy": {},
        },
    )


def _input(tmp_path: Path) -> Path:
    return _write(
        tmp_path / "events.json",
        [
            {
                "exchange_timestamp": "2026-08-31T10:00:00+05:30",
                "received_timestamp": "2026-08-31T10:00:00.001+05:30",
                "price": "100.00",
                "quantity": 1,
                "source": "fixture",
                "source_event_id": "e1",
            },
            {
                "exchange_timestamp": "2026-08-31T10:05:00+05:30",
                "received_timestamp": "2026-08-31T10:05:00.001+05:30",
                "price": "101.00",
                "quantity": 1,
                "source": "fixture",
                "source_event_id": "e2",
            },
        ],
    )


def test_replay_command_returns_deterministic_summary(tmp_path: Path) -> None:
    config = _config(tmp_path)
    input_path = _input(tmp_path)

    first = replay_command(config, input_path)
    second = replay_command(config, input_path)

    assert first == second
    assert first["instrument_id"] == "NSE:RELIANCE"
    assert first["events"] == 2
    assert first["evaluations"] == 1
    assert first["signals"] == 0
    assert first["trades"] == 0
    assert first["exits"] == 0
    assert first["final_lifecycle_state"] == "idle"


def test_main_prints_json_summary_and_returns_zero(tmp_path: Path, capsys) -> None:
    exit_code = main(
        [
            "replay",
            "--config",
            str(_config(tmp_path)),
            "--input",
            str(_input(tmp_path)),
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 0
    assert captured.err == ""
    assert payload["events"] == 2


def test_main_returns_nonzero_for_invalid_input(tmp_path: Path, capsys) -> None:
    invalid_input = _write(tmp_path / "events.json", {"not": "an array"})

    exit_code = main(
        [
            "replay",
            "--config",
            str(_config(tmp_path)),
            "--input",
            str(invalid_input),
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.out == ""
    assert "Replay input must be a JSON array" in captured.err
