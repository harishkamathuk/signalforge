from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from signalforge.config.strategy_registry import UnknownStrategyError
from signalforge.domain.ids import InstrumentId
from signalforge.research.command import (
    _decimal_string,
    _load_source,
    research_run_command,
)

GOLDEN = Path("examples/research/golden-experiment.json")


def _golden_payload() -> dict[str, object]:
    return json.loads(GOLDEN.read_text(encoding="utf-8"))


def _write_with_absolute_sources(
    tmp_path: Path,
    payload: dict[str, object],
) -> Path:
    instruments = payload["instruments"]
    assert isinstance(instruments, list)
    for raw in instruments:
        assert isinstance(raw, dict)
        input_file = raw["input_file"]
        assert isinstance(input_file, str)
        raw["input_file"] = str((GOLDEN.parent / input_file).resolve())
    path = tmp_path / "experiment.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_golden_research_command_returns_full_deterministic_result() -> None:
    first = research_run_command(GOLDEN)
    second = research_run_command(GOLDEN)

    assert first == second
    assert first["schema_version"] == "research-result-v1"

    experiment = first["experiment"]
    assert isinstance(experiment, dict)
    assert len(str(experiment["experiment_id"])) == 64
    assert len(str(experiment["universe_id"])) == 64
    assert len(str(experiment["dataset_id"])) == 64

    instruments = first["instrument_results"]
    assert isinstance(instruments, list)
    assert [item["instrument_id"] for item in instruments] == ["NSE:AAA", "NSE:BBB"]
    assert all(item["events"] == 302 for item in instruments)
    assert all(item["evaluations"] == 300 for item in instruments)
    assert all(item["qualified"] == 1 for item in instruments)
    assert all(item["actionable"] == 1 for item in instruments)
    assert all(item["signals"] == 1 for item in instruments)
    assert all(item["trades"] == 1 for item in instruments)
    assert all(item["exits"] == 1 for item in instruments)
    assert all(item["final_lifecycle_state"] == "closed" for item in instruments)

    trades = first["trade_dataset"]
    assert isinstance(trades, list)
    assert len(trades) == 2
    assert [trade["instrument_id"] for trade in trades] == ["NSE:AAA", "NSE:BBB"]
    assert all(trade["entry_price"] == "156.5" for trade in trades)
    assert all(trade["stop_price"] == "156.2" for trade in trades)
    assert all(trade["tradable_target_price"] == "157" for trade in trades)
    assert all(trade["exit_price"] == "156.7" for trade in trades)
    assert all(trade["realised_pnl"] == "2" for trade in trades)

    analytics = first["analytics"]
    assert isinstance(analytics, dict)
    assert analytics["economics_basis"] == "gross"
    assert analytics["trade_count"] == 2
    assert analytics["wins"] == 2
    assert analytics["gross_pnl"] == "4"
    assert analytics["profit_factor"] is None


def test_material_execution_change_changes_experiment_and_research_run_identity(
    tmp_path: Path,
) -> None:
    baseline = research_run_command(GOLDEN)
    changed_payload = _golden_payload()
    instruments = changed_payload["instruments"]
    assert isinstance(instruments, list)
    first_instrument = instruments[0]
    assert isinstance(first_instrument, dict)
    first_instrument["quantity"] = 11

    changed = research_run_command(
        _write_with_absolute_sources(tmp_path, changed_payload)
    )

    baseline_experiment = baseline["experiment"]
    changed_experiment = changed["experiment"]
    assert isinstance(baseline_experiment, dict)
    assert isinstance(changed_experiment, dict)
    assert changed_experiment["experiment_id"] != baseline_experiment["experiment_id"]
    assert changed_experiment["dataset_id"] == baseline_experiment["dataset_id"]

    baseline_results = baseline["instrument_results"]
    changed_results = changed["instrument_results"]
    assert isinstance(baseline_results, list)
    assert isinstance(changed_results, list)
    assert changed_results[0]["backtest_run_id"] != baseline_results[0]["backtest_run_id"]
    assert changed_results[0]["runtime_run_id"] == baseline_results[0]["runtime_run_id"]


def test_invalid_strategy_fails_before_historical_source_is_read(tmp_path: Path) -> None:
    payload = _golden_payload()
    payload["strategy"] = {
        "id": "not_registered",
        "version": "1.0.0",
        "parameters": {},
    }
    instruments = payload["instruments"]
    assert isinstance(instruments, list)
    first = instruments[0]
    assert isinstance(first, dict)
    first["input_file"] = "does-not-exist.json"
    path = tmp_path / "invalid-strategy.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(UnknownStrategyError):
        research_run_command(path)


def test_invalid_later_source_fails_before_orchestrator_runs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _golden_payload()
    path = _write_with_absolute_sources(tmp_path, payload)
    instruments = payload["instruments"]
    assert isinstance(instruments, list)
    second = instruments[1]
    assert isinstance(second, dict)
    second["input_file"] = str(tmp_path / "missing-second-source.json")
    path.write_text(json.dumps(payload), encoding="utf-8")

    called = False

    def fail_if_called(*args: object, **kwargs: object) -> object:
        nonlocal called
        called = True
        raise AssertionError("orchestrator must not run")

    monkeypatch.setattr(
        "signalforge.research.command.ResearchOrchestrator.run",
        fail_if_called,
    )

    with pytest.raises(FileNotFoundError):
        research_run_command(path)
    assert called is False


def test_rsi_reference_strategy_uses_same_research_command_boundary(
    tmp_path: Path,
) -> None:
    payload = _golden_payload()
    payload["strategy"] = {
        "id": "rsi_mean_reversion_v1",
        "version": "1.0.0",
        "parameters": {},
    }
    result = research_run_command(_write_with_absolute_sources(tmp_path, payload))

    experiment = result["experiment"]
    assert isinstance(experiment, dict)
    assert experiment["strategy_id"] == "rsi_mean_reversion_v1"
    instruments = result["instrument_results"]
    assert isinstance(instruments, list)
    assert [item["instrument_id"] for item in instruments] == ["NSE:AAA", "NSE:BBB"]


def test_research_config_rejects_extra_fields_before_sources_are_read(
    tmp_path: Path,
) -> None:
    payload = _golden_payload()
    payload["unsupported"] = True
    instruments = payload["instruments"]
    assert isinstance(instruments, list)
    first = instruments[0]
    assert isinstance(first, dict)
    first["input_file"] = "does-not-exist.json"
    path = tmp_path / "invalid-shape.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValidationError):
        research_run_command(path)


def test_research_json_numeric_prices_preserve_precision_in_source_identity(
    tmp_path: Path,
) -> None:
    first_path = tmp_path / "first.json"
    second_path = tmp_path / "second.json"
    template = """[
  {
    "exchange_timestamp": "2026-08-26T09:15:00+05:30",
    "received_timestamp": "2026-08-26T09:15:00.001+05:30",
    "price": %s,
    "quantity": 1,
    "source": "precision-regression",
    "source_event_id": "event-1"
  }
]"""
    first_path.write_text(template % "100.000000000000001", encoding="utf-8")
    second_path.write_text(template % "100.000000000000002", encoding="utf-8")

    first = _load_source(instrument_id=InstrumentId("NSE:AAA"), path=first_path)
    second = _load_source(instrument_id=InstrumentId("NSE:AAA"), path=second_path)

    first_event = next(iter(first)).event
    second_event = next(iter(second)).event

    assert first_event.price.value == Decimal("100.000000000000001")
    assert second_event.price.value == Decimal("100.000000000000002")
    assert first.identity.source_id != second.identity.source_id


def test_decimal_string_preserves_values_beyond_default_context_precision() -> None:
    value = Decimal("1.00000000000000000000000000001")

    rendered = _decimal_string(value)

    assert rendered == "1.00000000000000000000000000001"
    assert Decimal(rendered) == value
