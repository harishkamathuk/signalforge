"""SF-084: deterministic synthetic fixture storage; no provider/network dependency."""
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest

from signalforge.research.historical_bars import load_historical_bar_fixture
from signalforge.research.historical_dataset_store import (
    HistoricalDatasetStoreError,
    LocalHistoricalDatasetStore,
)

FIXTURE = (
    Path(__file__).resolve().parents[3]
    / "examples/research/historical-bars-one-session.json"
)


def test_save_reload_and_idempotent_offline(tmp_path, monkeypatch):
    dataset = load_historical_bar_fixture(FIXTURE)
    store = LocalHistoricalDatasetStore(tmp_path)
    identity = store.save(dataset)
    monkeypatch.setattr("socket.socket", lambda *args, **kwargs: pytest.fail("network called"))
    restored = store.load(identity)
    assert restored == dataset
    assert restored.dataset_id == identity
    assert restored.content_hash == dataset.content_hash
    assert store.save(dataset) == identity
    assert len(list(tmp_path.iterdir())) == 2


def test_distinct_versions_coexist(tmp_path):
    dataset = load_historical_bar_fixture(FIXTURE)
    other = replace(dataset, manifest=replace(
        dataset.manifest,
        limitations=dataset.manifest.limitations + ("second immutable interpretation",),
    ))
    store = LocalHistoricalDatasetStore(tmp_path)
    first = store.save(dataset)
    second = store.save(other)
    assert first != second
    assert store.load(first) == dataset
    assert store.load(second) == other


def test_byte_tamper_and_absent_manifest_fail_closed(tmp_path):
    dataset = load_historical_bar_fixture(FIXTURE)
    store = LocalHistoricalDatasetStore(tmp_path)
    identity = store.save(dataset)
    path = tmp_path / (str(identity) + ".json")
    path.write_bytes(path.read_bytes().replace(b'"volume":1000', b'"volume":1001', 1))
    with pytest.raises(HistoricalDatasetStoreError):
        store.load(identity)
    with pytest.raises(HistoricalDatasetStoreError):
        store.save(dataset)
    path.unlink()
    with pytest.raises(HistoricalDatasetStoreError):
        store.load(identity)


def test_semantic_hash_check_even_if_attacker_rewrites_byte_digest(tmp_path):
    dataset = load_historical_bar_fixture(FIXTURE)
    store = LocalHistoricalDatasetStore(tmp_path)
    identity = store.save(dataset)
    path = tmp_path / (str(identity) + ".json")
    import hashlib

    altered = path.read_bytes().replace(b'"volume":1000', b'"volume":1001', 1)
    path.write_bytes(altered)
    path.with_suffix(".sha256").write_text(
        hashlib.sha256(altered).hexdigest() + "\n", encoding="ascii"
    )
    with pytest.raises(HistoricalDatasetStoreError, match="semantic identity"):
        store.load(identity)


def test_metadata_not_in_semantic_id_cannot_silently_change(tmp_path):
    dataset = load_historical_bar_fixture(FIXTURE)
    store = LocalHistoricalDatasetStore(tmp_path)
    store.save(dataset)
    different_observation = replace(
        dataset, manifest=replace(
            dataset.manifest,
            acquired_at=dataset.manifest.acquired_at + timedelta(hours=1),
        )
    )
    assert different_observation.dataset_id == dataset.dataset_id
    with pytest.raises(HistoricalDatasetStoreError, match="differs"):
        store.save(different_observation)


def test_no_reacquisition_or_repair_on_missing_file(tmp_path):
    dataset = load_historical_bar_fixture(FIXTURE)
    store = LocalHistoricalDatasetStore(tmp_path)
    with pytest.raises(HistoricalDatasetStoreError):
        store.load(dataset.dataset_id)
    assert not list(tmp_path.iterdir())
