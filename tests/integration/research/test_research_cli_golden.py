from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

GOLDEN = Path("examples/research/golden-experiment.json")


def _run_clean_process() -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "signalforge.cli",
            "research",
            "run",
            "--experiment",
            str(GOLDEN),
        ],
        check=False,
        capture_output=True,
        text=True,
    )


def test_golden_research_cli_is_reproducible_across_clean_processes() -> None:
    first = _run_clean_process()
    second = _run_clean_process()

    assert first.returncode == 0
    assert second.returncode == 0
    assert first.stderr == ""
    assert second.stderr == ""
    assert first.stdout == second.stdout

    result = json.loads(first.stdout)
    experiment = result["experiment"]
    assert len(experiment["experiment_id"]) == 64
    assert len(experiment["universe_id"]) == 64
    assert len(experiment["dataset_id"]) == 64

    instrument_results = result["instrument_results"]
    assert [item["instrument_id"] for item in instrument_results] == [
        "NSE:AAA",
        "NSE:BBB",
    ]
    assert all(len(item["backtest_run_id"]) == 64 for item in instrument_results)
    assert all(len(item["runtime_run_id"]) == 64 for item in instrument_results)
    assert all(len(item["source_id"]) == 64 for item in instrument_results)

    trades = result["trade_dataset"]
    assert len(trades) == 2
    assert all(len(item["backtest_trade_id"]) == 64 for item in trades)
    assert result["analytics"]["gross_pnl"] == "4.0"
    assert result["analytics"]["expectancy_r"] == (
        "0.6666666666666666666666666667"
    )
