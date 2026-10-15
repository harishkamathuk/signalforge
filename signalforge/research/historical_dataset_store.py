"""Provider-independent immutable local storage for canonical historical datasets.

The store never contacts a provider. JSON is deliberate: the existing strict
historical fixture loader defines its complete on-disk wire format.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import fields
from datetime import date, datetime
from pathlib import Path

from signalforge.domain.ids import DatasetId
from signalforge.research.historical_bars import (
    HistoricalBarDataset,
    load_historical_bar_fixture,
)


class HistoricalDatasetStoreError(ValueError):
    """A requested frozen dataset is unavailable or invalid."""


def _serialize(value: object) -> object:
    if isinstance(value, datetime | date):
        return value.isoformat()
    if hasattr(value, "value"):
        return str(value.value)
    if isinstance(value, tuple):
        return [_serialize(item) for item in value]
    return value


def _payload(dataset: HistoricalBarDataset) -> bytes:
    manifest = {
        field.name: _serialize(getattr(dataset.manifest, field.name))
        for field in fields(dataset.manifest)
    }
    bars = []
    for bar in dataset.bars:
        row = {
            "bucket_start": bar.interval.start.isoformat(),
            "open": str(bar.open.value),
            "high": str(bar.high.value),
            "low": str(bar.low.value),
            "close": str(bar.close.value),
            "volume": bar.volume,
            "quality": bar.quality.value,
            "source_provider": bar.source_provider,
            "source_record_count": bar.source_record_count,
            "provider_timestamp_raw": bar.provider_timestamp_raw,
            "provider_timestamp_interpreted": (
                bar.provider_timestamp_interpreted.isoformat()
                if bar.provider_timestamp_interpreted is not None else None
            ),
            "canonicalisation_version": bar.canonicalisation_version,
        }
        bars.append(row)
    return (json.dumps({"manifest": manifest, "bars": bars},
                       sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n").encode()


class LocalHistoricalDatasetStore:
    """Content-addressed local store; no implicit acquisition or mutation."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def _path(self, dataset_id: DatasetId) -> Path:
        value = str(dataset_id)
        if len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
            raise HistoricalDatasetStoreError("invalid canonical dataset identifier")
        return self.root / (value + ".json")

    def load(self, dataset_id: DatasetId) -> HistoricalBarDataset:
        path = self._path(dataset_id)
        try:
            blob = path.read_bytes()
            digest = (path.with_suffix(".sha256")).read_text(encoding="ascii")
            if digest != hashlib.sha256(blob).hexdigest() + "\n":
                raise HistoricalDatasetStoreError("stored bytes disagree with frozen digest")
            dataset = load_historical_bar_fixture(path)
            if dataset.dataset_id != dataset_id:
                raise HistoricalDatasetStoreError("dataset semantic identity mismatch")
            return dataset
        except HistoricalDatasetStoreError:
            raise
        except (OSError, ValueError, TypeError, ArithmeticError) as exc:
            raise HistoricalDatasetStoreError(
                f"frozen dataset unavailable or invalid: {dataset_id}"
            ) from exc

    def save(self, dataset: HistoricalBarDataset) -> DatasetId:
        dataset_id = dataset.dataset_id
        path = self._path(dataset_id)
        blob = _payload(dataset)
        digest_path = path.with_suffix(".sha256")
        self.root.mkdir(parents=True, exist_ok=True)
        if path.exists() or digest_path.exists():
            loaded = self.load(dataset_id)
            if loaded.manifest != dataset.manifest or loaded.bars != dataset.bars:
                raise HistoricalDatasetStoreError("existing frozen dataset differs")
            if path.read_bytes() != blob:
                raise HistoricalDatasetStoreError("existing immutable bytes differ")
            return dataset_id
        # Exclusive creation prevents replacing an existing frozen dataset.
        # A partially written pair fails closed on load and is never auto-repaired.
        try:
            with path.open("xb") as handle:
                handle.write(blob)
                handle.flush()
                os.fsync(handle.fileno())
            with digest_path.open("x", encoding="ascii") as handle:
                handle.write(hashlib.sha256(blob).hexdigest() + "\n")
                handle.flush()
                os.fsync(handle.fileno())
        except FileExistsError as exc:
            raise HistoricalDatasetStoreError("concurrent/conflicting dataset write") from exc
        return dataset_id
