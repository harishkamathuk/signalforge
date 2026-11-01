"""Provider-independent immutable local storage for canonical historical datasets.

Legacy fixture/small-sample datasets retain the existing canonical JSON representation.
Year-scale datasets use a provider-neutral Parquet representation behind the same save/load
boundary. Neither representation contacts a provider.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import fields
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

from signalforge.domain.ids import DatasetId
from signalforge.research.historical_bars import (
    HistoricalBarDataset,
    parse_historical_bar_fixture_json,
    parse_historical_bar_storage_payload,
)

_PARQUET_MIN_ROWS = 100_000
_PARQUET_REPRESENTATION = "historical-bars-parquet-v1"
_PARQUET_SCHEMA_VERSION = "historical-bars-schema-v1"


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


def _manifest_payload(dataset: HistoricalBarDataset) -> dict[str, object]:
    manifest = {
        field.name: _serialize(getattr(dataset.manifest, field.name))
        for field in fields(dataset.manifest)
        if field.name not in {"grid", "price_basis"}
    }
    if dataset.manifest.grid is not None:
        manifest["grid"] = dataset.manifest.grid.semantic_mapping()
    if dataset.manifest.price_basis is not None:
        manifest["price_basis"] = dataset.manifest.price_basis.value
    return manifest


def _bar_payloads(dataset: HistoricalBarDataset) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for bar in dataset.bars:
        rows.append(
            {
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
                    if bar.provider_timestamp_interpreted is not None
                    else None
                ),
                "canonicalisation_version": bar.canonicalisation_version,
            }
        )
    return rows


def _payload(dataset: HistoricalBarDataset) -> bytes:
    return (
        json.dumps(
            {"manifest": _manifest_payload(dataset), "bars": _bar_payloads(dataset)},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )
        + "\n"
    ).encode()


def _decimal_type(values: list[Decimal]) -> pa.DataType:
    max_scale = 0
    max_integer_digits = 1
    for value in values:
        if not value.is_finite():
            raise HistoricalDatasetStoreError("Parquet price must be finite")
        exponent = value.as_tuple().exponent
        if not isinstance(exponent, int):
            raise HistoricalDatasetStoreError("Parquet price exponent must be integral")
        scale = max(0, -exponent)
        integer_digits = max(1, value.adjusted() + 1) if value != 0 else 1
        max_scale = max(max_scale, scale)
        max_integer_digits = max(max_integer_digits, integer_digits)
    precision = max_integer_digits + max_scale
    if precision > 38:
        raise HistoricalDatasetStoreError(
            "Parquet decimal128 cannot losslessly represent historical price precision"
        )
    return pa.decimal128(precision, max_scale)


def _parquet_table(dataset: HistoricalBarDataset) -> pa.Table:
    opens = [bar.open.value for bar in dataset.bars]
    highs = [bar.high.value for bar in dataset.bars]
    lows = [bar.low.value for bar in dataset.bars]
    closes = [bar.close.value for bar in dataset.bars]
    decimal_type = _decimal_type(opens + highs + lows + closes)

    arrays = [
        pa.array([bar.interval.start for bar in dataset.bars], type=pa.timestamp("us", tz="UTC")),
        pa.array(opens, type=decimal_type),
        pa.array(highs, type=decimal_type),
        pa.array(lows, type=decimal_type),
        pa.array(closes, type=decimal_type),
        pa.array([bar.volume for bar in dataset.bars], type=pa.int64()),
        pa.array([bar.quality.value for bar in dataset.bars], type=pa.string()),
        pa.array([bar.source_provider for bar in dataset.bars], type=pa.string()),
        pa.array([bar.source_record_count for bar in dataset.bars], type=pa.int32()),
        pa.array([bar.provider_timestamp_raw for bar in dataset.bars], type=pa.string()),
        pa.array(
            [bar.provider_timestamp_interpreted for bar in dataset.bars],
            type=pa.timestamp("us", tz="UTC"),
        ),
        pa.array([bar.canonicalisation_version for bar in dataset.bars], type=pa.string()),
    ]
    names = [
        "bucket_start",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "quality",
        "source_provider",
        "source_record_count",
        "provider_timestamp_raw",
        "provider_timestamp_interpreted",
        "canonicalisation_version",
    ]
    return pa.Table.from_arrays(arrays, names=names)


def _schema_fingerprint(schema: pa.Schema) -> str:
    material = json.dumps(
        {
            "schema_version": _PARQUET_SCHEMA_VERSION,
            "fields": [
                {
                    "name": field.name,
                    "type": str(field.type),
                    "nullable": field.nullable,
                }
                for field in schema
            ],
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")
    return hashlib.sha256(material).hexdigest()


def _parquet_bytes(dataset: HistoricalBarDataset) -> tuple[bytes, str]:
    table = _parquet_table(dataset)
    sink = pa.BufferOutputStream()
    pq.write_table(
        table,
        sink,
        compression="zstd",
        version="2.6",
        use_dictionary=True,
        write_statistics=True,
    )
    return sink.getvalue().to_pybytes(), _schema_fingerprint(table.schema)


def _component_record(content: bytes) -> dict[str, object]:
    return {
        "sha256": hashlib.sha256(content).hexdigest(),
        "size_bytes": len(content),
    }


def _write_exclusive(path: Path, content: bytes) -> None:
    with path.open("xb") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())


def _fsync_directory(path: Path) -> None:
    if hasattr(os, "O_DIRECTORY"):
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


class LocalHistoricalDatasetStore:
    """Content-addressed local store; no implicit acquisition or mutation."""

    def __init__(self, root: Path, *, parquet_min_rows: int = _PARQUET_MIN_ROWS) -> None:
        if parquet_min_rows <= 0:
            raise ValueError("parquet_min_rows must be positive")
        self.root = Path(root)
        self.parquet_min_rows = parquet_min_rows

    def _legacy_path(self, dataset_id: DatasetId) -> Path:
        value = str(dataset_id)
        if len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
            raise HistoricalDatasetStoreError("invalid canonical dataset identifier")
        return self.root / (value + ".json")

    def _parquet_path(self, dataset_id: DatasetId) -> Path:
        value = str(dataset_id)
        if len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
            raise HistoricalDatasetStoreError("invalid canonical dataset identifier")
        return self.root / value

    def load(self, dataset_id: DatasetId) -> HistoricalBarDataset:
        legacy_path = self._legacy_path(dataset_id)
        parquet_path = self._parquet_path(dataset_id)
        if legacy_path.exists() or legacy_path.with_suffix(".sha256").exists():
            if parquet_path.exists():
                raise HistoricalDatasetStoreError(
                    "dataset identity exists in conflicting storage representations"
                )
            return self._load_legacy(dataset_id)
        if parquet_path.exists():
            return self._load_parquet(dataset_id)
        raise HistoricalDatasetStoreError(
            f"frozen dataset unavailable or invalid: {dataset_id}"
        )

    def _load_legacy(self, dataset_id: DatasetId) -> HistoricalBarDataset:
        path = self._legacy_path(dataset_id)
        try:
            blob = path.read_bytes()
            digest = path.with_suffix(".sha256").read_text(encoding="ascii")
            if digest != hashlib.sha256(blob).hexdigest() + "\n":
                raise HistoricalDatasetStoreError("stored bytes disagree with frozen digest")
            dataset = parse_historical_bar_fixture_json(
                blob.decode("utf-8"), canonical_storage=True
            )
            if dataset.dataset_id != dataset_id:
                raise HistoricalDatasetStoreError("dataset semantic identity mismatch")
            return dataset
        except HistoricalDatasetStoreError:
            raise
        except (OSError, ValueError, TypeError, ArithmeticError) as exc:
            raise HistoricalDatasetStoreError(
                f"frozen dataset unavailable or invalid: {dataset_id}"
            ) from exc

    def _load_parquet(self, dataset_id: DatasetId) -> HistoricalBarDataset:
        directory = self._parquet_path(dataset_id)
        try:
            content_manifest_path = directory / "content-manifest.json"
            content_manifest_blob = content_manifest_path.read_bytes()
            manifest_digest = (directory / "content-manifest.sha256").read_text(
                encoding="ascii"
            )
            if manifest_digest != hashlib.sha256(content_manifest_blob).hexdigest() + "\n":
                raise HistoricalDatasetStoreError(
                    "stored Parquet content manifest disagrees with frozen digest"
                )
            content_manifest = json.loads(content_manifest_blob.decode("utf-8"))
            if not isinstance(content_manifest, dict):
                raise HistoricalDatasetStoreError("Parquet content manifest must be an object")
            if content_manifest.get("representation") != _PARQUET_REPRESENTATION:
                raise HistoricalDatasetStoreError("unsupported Parquet representation version")
            if content_manifest.get("dataset_id") != str(dataset_id):
                raise HistoricalDatasetStoreError("Parquet content manifest dataset mismatch")
            if content_manifest.get("schema_version") != _PARQUET_SCHEMA_VERSION:
                raise HistoricalDatasetStoreError("unsupported Parquet schema version")
            components = content_manifest.get("components")
            if not isinstance(components, dict):
                raise HistoricalDatasetStoreError("Parquet component manifest must be an object")

            manifest_blob = (directory / "manifest.json").read_bytes()
            parquet_blob = (directory / "bars.parquet").read_bytes()
            self._verify_component(components, "manifest.json", manifest_blob)
            self._verify_component(components, "bars.parquet", parquet_blob)

            try:
                table = pq.read_table(pa.BufferReader(parquet_blob))
            except Exception as exc:
                raise HistoricalDatasetStoreError("stored Parquet bytes are unreadable") from exc
            expected_schema = content_manifest.get("schema_sha256")
            if not isinstance(expected_schema, str) or (
                _schema_fingerprint(table.schema) != expected_schema
            ):
                raise HistoricalDatasetStoreError("Parquet schema fingerprint mismatch")

            manifest = json.loads(manifest_blob.decode("utf-8"))
            if not isinstance(manifest, dict):
                raise HistoricalDatasetStoreError("stored historical manifest must be an object")
            rows = self._rows_from_parquet(table)
            dataset = parse_historical_bar_storage_payload(
                {"manifest": manifest, "bars": rows},
                canonical_storage=True,
            )
            if dataset.dataset_id != dataset_id:
                raise HistoricalDatasetStoreError("dataset semantic identity mismatch")
            return dataset
        except HistoricalDatasetStoreError:
            raise
        except (OSError, ValueError, TypeError, ArithmeticError) as exc:
            raise HistoricalDatasetStoreError(
                f"frozen dataset unavailable or invalid: {dataset_id}"
            ) from exc

    @staticmethod
    def _verify_component(
        components: dict[str, Any],
        name: str,
        content: bytes,
    ) -> None:
        record = components.get(name)
        if not isinstance(record, dict):
            raise HistoricalDatasetStoreError(f"missing frozen component record: {name}")
        expected_sha = record.get("sha256")
        expected_size = record.get("size_bytes")
        if expected_sha != hashlib.sha256(content).hexdigest():
            raise HistoricalDatasetStoreError(f"stored component digest mismatch: {name}")
        if expected_size != len(content):
            raise HistoricalDatasetStoreError(f"stored component size mismatch: {name}")

    @staticmethod
    def _rows_from_parquet(table: pa.Table) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        for row in table.to_pylist():
            bucket_start = row["bucket_start"]
            provider_time = row["provider_timestamp_interpreted"]
            if not isinstance(bucket_start, datetime):
                raise HistoricalDatasetStoreError("Parquet bucket_start must be datetime")
            if provider_time is not None and not isinstance(provider_time, datetime):
                raise HistoricalDatasetStoreError(
                    "Parquet provider_timestamp_interpreted must be datetime or null"
                )
            rows.append(
                {
                    "bucket_start": bucket_start.isoformat(),
                    "open": str(row["open"]),
                    "high": str(row["high"]),
                    "low": str(row["low"]),
                    "close": str(row["close"]),
                    "volume": row["volume"],
                    "quality": row["quality"],
                    "source_provider": row["source_provider"],
                    "source_record_count": row["source_record_count"],
                    "provider_timestamp_raw": row["provider_timestamp_raw"],
                    "provider_timestamp_interpreted": (
                        provider_time.isoformat() if provider_time is not None else None
                    ),
                    "canonicalisation_version": row["canonicalisation_version"],
                }
            )
        return rows

    def save(self, dataset: HistoricalBarDataset) -> DatasetId:
        dataset_id = dataset.dataset_id
        legacy_path = self._legacy_path(dataset_id)
        parquet_path = self._parquet_path(dataset_id)
        if (
            legacy_path.exists()
            or legacy_path.with_suffix(".sha256").exists()
            or parquet_path.exists()
        ):
            loaded = self.load(dataset_id)
            if loaded.manifest != dataset.manifest or loaded.bars != dataset.bars:
                raise HistoricalDatasetStoreError("existing frozen dataset differs")
            return dataset_id
        if len(dataset.bars) >= self.parquet_min_rows:
            return self._save_parquet(dataset)
        return self._save_legacy(dataset)

    def _save_legacy(self, dataset: HistoricalBarDataset) -> DatasetId:
        dataset_id = dataset.dataset_id
        path = self._legacy_path(dataset_id)
        blob = _payload(dataset)
        digest_path = path.with_suffix(".sha256")
        self._preflight_payload(dataset, blob)
        self.root.mkdir(parents=True, exist_ok=True)
        try:
            _write_exclusive(path, blob)
            with digest_path.open("x", encoding="ascii") as handle:
                handle.write(hashlib.sha256(blob).hexdigest() + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            _fsync_directory(self.root)
        except FileExistsError as exc:
            raise HistoricalDatasetStoreError("concurrent/conflicting dataset write") from exc
        return dataset_id

    def _save_parquet(self, dataset: HistoricalBarDataset) -> DatasetId:
        dataset_id = dataset.dataset_id
        directory = self._parquet_path(dataset_id)
        manifest_blob = (
            json.dumps(
                _manifest_payload(dataset),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            )
            + "\n"
        ).encode("utf-8")
        parquet_blob, schema_sha256 = _parquet_bytes(dataset)
        self.root.mkdir(parents=True, exist_ok=True)
        try:
            directory.mkdir(exist_ok=False)
            _write_exclusive(directory / "manifest.json", manifest_blob)
            _write_exclusive(directory / "bars.parquet", parquet_blob)
            content_manifest = {
                "representation": _PARQUET_REPRESENTATION,
                "schema_version": _PARQUET_SCHEMA_VERSION,
                "dataset_id": str(dataset_id),
                "schema_sha256": schema_sha256,
                "components": {
                    "manifest.json": _component_record(manifest_blob),
                    "bars.parquet": _component_record(parquet_blob),
                },
            }
            content_manifest_blob = (
                json.dumps(
                    content_manifest,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=True,
                )
                + "\n"
            ).encode("utf-8")
            _write_exclusive(directory / "content-manifest.json", content_manifest_blob)
            _write_exclusive(
                directory / "content-manifest.sha256",
                (hashlib.sha256(content_manifest_blob).hexdigest() + "\n").encode(
                    "ascii"
                ),
            )
            _fsync_directory(directory)
            _fsync_directory(self.root)
        except FileExistsError as exc:
            raise HistoricalDatasetStoreError("concurrent/conflicting dataset write") from exc

        restored = self._load_parquet(dataset_id)
        if restored.manifest != dataset.manifest or restored.bars != dataset.bars:
            raise HistoricalDatasetStoreError("serialized Parquet dataset round-trip differs")
        return dataset_id

    @staticmethod
    def _preflight_payload(dataset: HistoricalBarDataset, blob: bytes) -> None:
        try:
            verified = parse_historical_bar_fixture_json(
                blob.decode("utf-8"), canonical_storage=True
            )
            if verified != dataset or verified.dataset_id != dataset.dataset_id:
                raise HistoricalDatasetStoreError("serialized dataset round-trip differs")
        except HistoricalDatasetStoreError:
            raise
        except (ValueError, TypeError, ArithmeticError) as exc:
            raise HistoricalDatasetStoreError(
                "dataset is not serializable for offline reuse"
            ) from exc
