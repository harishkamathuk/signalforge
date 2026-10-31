"""Three market-neutral canonical coverage proofs, including store round-trip."""
from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from signalforge.domain.time import CandleInterval
from signalforge.research.historical_bars import (
    HistoricalBarDataset,
    aggregate_one_minute_to_five_minute,
    load_historical_bar_fixture,
)
from signalforge.research.historical_dataset_store import LocalHistoricalDatasetStore
from signalforge.research.historical_grid import HistoricalBarGrid

_FIXTURE = (
    Path(__file__).resolve().parents[3]
    / "examples/research/historical-bars-one-session.json"
)


@pytest.mark.parametrize(
    ("start", "minutes", "five_minute_count"),
    [
        (datetime(2026, 10, 9, 3, 45, tzinfo=UTC), 375, 75),
        (datetime(2026, 10, 9, 0, 0, tzinfo=UTC), 1440, 288),
        (datetime(2026, 10, 9, 0, 2, tzinfo=UTC), 15, 3),
    ],
)
def test_grid_expected_intervals_and_anchor(start, minutes, five_minute_count):
    end = start + timedelta(minutes=minutes)
    grid = HistoricalBarGrid(
        grid_id="proof-coverage", version="1",
        coverage=(CandleInterval(start, end),),
    )
    expected_minutes = tuple(grid.minute_starts())
    buckets = tuple(grid.five_minute_intervals())
    assert len(expected_minutes) == minutes
    assert len(buckets) == five_minute_count
    assert expected_minutes[0] == start
    assert expected_minutes[-1] == end - timedelta(minutes=1)
    assert [bucket.start for bucket in buckets[:3]] == [
        start + timedelta(minutes=5 * i) for i in range(3)
    ]


def test_continuous_out_of_nse_hours_canonical_dataset_round_trip(tmp_path):
    legacy = load_historical_bar_fixture(_FIXTURE)
    start = datetime(2026, 10, 9, 0, 2, tzinfo=UTC)
    grid = HistoricalBarGrid(
        grid_id="utc-offset-test", version="1",
        coverage=(CandleInterval(start, start + timedelta(minutes=15)),),
    )
    bar = replace(
        legacy.bars[0],
        interval=CandleInterval(start, start + timedelta(minutes=1)),
    )
    manifest = replace(
        legacy.manifest,
        expected_session_dates=(),
        grid=grid,
        requested_start=start,
        requested_end=start + timedelta(minutes=15),
        returned_start=start,
        returned_end=start + timedelta(minutes=1),
        raw_row_count=1,
        canonical_row_count=1,
        missing_interval_count=14,
        duplicate_observation_count=0,
        corrupt_rejected_count=0,
    )
    dataset = HistoricalBarDataset(manifest=manifest, bars=(bar,))
    candles = aggregate_one_minute_to_five_minute(dataset)
    assert len(candles) == 3
    assert candles[0].interval.start == start
    assert candles[0].source_event_count == 1
    assert LocalHistoricalDatasetStore(tmp_path).save(dataset) == dataset.dataset_id
    assert LocalHistoricalDatasetStore(tmp_path).load(dataset.dataset_id) == dataset


def test_legacy_dataset_identity_and_nse_candles_unchanged():
    dataset = load_historical_bar_fixture(_FIXTURE)
    assert dataset.manifest.grid is None
    assert dataset.manifest.effective_grid.expected_minute_count == 375
    assert len(tuple(dataset.manifest.effective_grid.five_minute_intervals())) == 75
    assert len(aggregate_one_minute_to_five_minute(dataset)) == 75


def test_grid_rejects_non_aligned_and_overlapping_coverage():
    start = datetime(2026, 10, 9, 0, 2, tzinfo=UTC)
    with pytest.raises(ValueError, match="five-minute"):
        HistoricalBarGrid(
            "bad", "1", (CandleInterval(start, start + timedelta(minutes=6)),),
        )
    with pytest.raises(ValueError, match="non-overlapping"):
        HistoricalBarGrid(
            "bad", "1", (
                CandleInterval(start, start + timedelta(minutes=10)),
                CandleInterval(start + timedelta(minutes=5), start + timedelta(minutes=15)),
            ),
        )


def test_distinct_coverage_segments_do_not_invent_intervening_minutes():
    start = datetime(2026, 10, 9, 0, 2, tzinfo=UTC)
    grid = HistoricalBarGrid(
        "split-utc", "1",
        (
            CandleInterval(start, start + timedelta(minutes=5)),
            CandleInterval(start + timedelta(minutes=60), start + timedelta(minutes=70)),
        ),
    )
    assert grid.expected_minute_count == 15
    assert len(tuple(grid.five_minute_intervals())) == 3
    assert not grid.contains_minute(start + timedelta(minutes=20))


def test_grid_version_changes_semantic_identity(tmp_path):
    legacy = load_historical_bar_fixture(_FIXTURE)
    start = datetime(2026, 10, 9, 0, 2, tzinfo=UTC)
    bar = replace(
        legacy.bars[0],
        interval=CandleInterval(start, start + timedelta(minutes=1)),
    )
    coverage = (CandleInterval(start, start + timedelta(minutes=15)),)
    manifest = replace(
        legacy.manifest,
        expected_session_dates=(),
        grid=HistoricalBarGrid("bounded", "1", coverage),
        requested_start=start,
        requested_end=start + timedelta(minutes=15),
        returned_start=start,
        returned_end=start + timedelta(minutes=1),
        raw_row_count=1,
        canonical_row_count=1,
        missing_interval_count=14,
        duplicate_observation_count=0,
        corrupt_rejected_count=0,
    )
    first = HistoricalBarDataset(manifest, (bar,))
    second = HistoricalBarDataset(
        replace(manifest, grid=HistoricalBarGrid("bounded", "2", coverage)), (bar,)
    )
    assert first.dataset_id != second.dataset_id
