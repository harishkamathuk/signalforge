"""Contract tests for unqualified, read-only SF-088 price exploration."""
from __future__ import annotations

from dataclasses import replace
from decimal import Decimal, getcontext
from pathlib import Path

import pytest

from signalforge.research import delta_provisional_research as provisional
from signalforge.research.delta_historical_qualification import DeltaCandle


def _candles(count: int = 100) -> list[DeltaCandle]:
    start = 1_761_782_400  # 2025-10-30T00:00:00Z
    return [
        DeltaCandle(
            time=start + 60 * n,
            open=Decimal("65000.1") if n == 0 else Decimal("65000"),
            high=Decimal("65100"),
            low=Decimal("65000"),
            close=Decimal("65000.1") if n == 0 else Decimal(65000 + n),
            volume=Decimal(1),
        )
        for n in range(count)
    ]


def test_exploratory_sma_is_completed_only_and_deterministic() -> None:
    values = _candles()
    before = getcontext().prec
    first = provisional.summarize_completed_five_minute_closes(values)
    getcontext().prec = 12
    try:
        second = provisional.summarize_completed_five_minute_closes(iter(values))
    finally:
        getcontext().prec = before

    assert first == second
    assert first["one_minute_candles"] == 100
    assert first["completed_five_minute_closes"] == 20
    assert first["sma20_completed_points"] == 1
    assert first["sma20_warmup_completed_bars"] == 19
    assert len(first["sma20_sha256"]) == 64
    # Price irregularities are not snapped to any assumed historical tick.
    changed = values.copy()
    changed[0] = replace(changed[0], close=Decimal("65000.0"))
    assert (
        provisional.summarize_completed_five_minute_closes(changed)[
            "five_minute_close_sha256"
        ] == first["five_minute_close_sha256"]
    )
    changed[4] = replace(changed[4], close=Decimal("65000.1"))
    assert (
        provisional.summarize_completed_five_minute_closes(changed)[
            "five_minute_close_sha256"
        ] != first["five_minute_close_sha256"]
    )


@pytest.mark.parametrize("mode", ["missing", "duplicate", "unaligned", "partial", "empty"])
def test_incomplete_or_ambiguous_minutes_fail(mode: str) -> None:
    candles = _candles(10)
    if mode == "missing":
        candles.pop(4)
    elif mode == "duplicate":
        candles[4] = replace(candles[4], time=candles[3].time)
    elif mode == "unaligned":
        candles[0] = replace(candles[0], time=candles[0].time + 1)
    elif mode == "partial":
        candles.pop()
    else:
        candles.clear()
    with pytest.raises(ValueError):
        provisional.summarize_completed_five_minute_closes(candles)


def test_audit_failure_blocks_all_provisional_reading(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "generation-0001"
    root.mkdir()

    def reject(_root: Path) -> dict[str, object]:
        return {
            "audit_status": "FAIL",
            "frozen_start": provisional.SF088_START.isoformat(),
            "frozen_end": provisional.SF088_END.isoformat(),
            "observed_unique_minutes_pass_1": provisional.SF088_EXPECTED_MINUTES,
            "two_pass_semantic_match_independently_recomputed": True,
        }

    monkeypatch.setattr(provisional, "audit_generation", reject)
    with pytest.raises(ValueError, match="complete, audited"):
        provisional.explore_generation(root)


def test_command_refuses_output_overwrite_and_immutable_source(
    tmp_path: Path,
) -> None:
    root = tmp_path / ".signalforge-data" / "generation-0001"
    root.mkdir(parents=True)
    output = tmp_path / ".signalforge-data" / "report.json"
    output.write_text("existing report", encoding="utf-8")
    with pytest.raises(SystemExit):
        provisional.main([
            "--generation-dir", str(root), "--output", str(output),
        ])
    assert output.read_text(encoding="utf-8") == "existing report"

    with pytest.raises(SystemExit):
        provisional.main([
            "--generation-dir", str(root),
            "--output", str(root / "diagnostics.json"),
        ])
    with pytest.raises(SystemExit):
        provisional.main([
            "--generation-dir", str(root),
            "--output", str(tmp_path / "public-report.json"),
        ])
