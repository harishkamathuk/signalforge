"""Offline SF-088 raw-evidence audit; never contacts provider or publishes canonical data."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import UTC, datetime
from hashlib import sha256
import json
from pathlib import Path

from signalforge.research.delta_historical_dataset_acquisition import (
    SF088_END, SF088_EXPECTED_MINUTES, SF088_START, SF088_SYMBOL, SF088_ACQUISITION_VERSION,
    _candle_semantic_sha256, _sha256_json, _verify_evidence_source_url,
    build_sf088_chunk_plan,
)
from signalforge.research.delta_historical_qualification import (
    DeltaRawCapture, parse_delta_candles_response, parse_delta_product_response,
)


def _load_capture(raw_path: Path, meta_path: Path) -> tuple[DeltaRawCapture, dict]:
    raw = raw_path.read_bytes()
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    if sha256(raw).hexdigest() != meta["raw_sha256"]:
        raise ValueError(f"raw digest mismatch: {raw_path}")
    return DeltaRawCapture(
        request_url=meta["request_url"],
        acquired_at=datetime.fromisoformat(meta["acquired_at"]),
        content_sha256=meta["raw_sha256"],
        content=raw,
    ), meta


def audit_generation(generation_dir: Path) -> dict:
    """Check immutable evidence against its declared report and frozen UTC grid."""
    root = generation_dir.resolve(strict=True)
    report = json.loads((root / "evidence-only-report.json").read_text(encoding="utf-8"))
    expected_hash = _sha256_json({k: v for k, v in report.items() if k != "report_sha256"})
    if report.get("report_sha256") != expected_hash:
        raise ValueError("evidence report digest mismatch")
    plan = build_sf088_chunk_plan()
    if (
        report.get("source_product_id") != 27
        or report.get("source_symbol") != SF088_SYMBOL
        or report.get("acquisition_version") != SF088_ACQUISITION_VERSION
    ):
        raise ValueError("evidence source/product/acquisition identity mismatch")
    if (
        report.get("mode") != "EVIDENCE_ONLY"
        or report.get("generation_namespace") != root.name
        or report.get("frozen_start") != SF088_START.isoformat()
        or report.get("frozen_end") != SF088_END.isoformat()
        or report.get("expected_minutes") != SF088_EXPECTED_MINUTES
        or report.get("chunk_identities") != [chunk.identity for chunk in plan]
        or report.get("chunk_count_per_pass") != len(plan)
    ):
        raise ValueError("evidence report does not match frozen SF-088 contract")
    start = int(SF088_START.timestamp())
    end = int(SF088_END.timestamp())
    coverage = bytearray(SF088_EXPECTED_MINUTES)
    results = {}
    semantic_by_pass = []
    for number, prefix in ((1, "first"), (2, "second")):
        folder = root / f"pass-{number}"
        expected_raw = {f"chunk-{c.index:06d}.json" for c in plan}
        expected_meta = {f"chunk-{c.index:06d}.meta.json" for c in plan}
        actual_raw = {
            p.name for p in folder.glob("chunk-*.json")
            if not p.name.endswith(".meta.json")
        }
        actual_meta = {p.name for p in folder.glob("chunk-*.meta.json")}
        if actual_raw != expected_raw or actual_meta != expected_meta:
            raise ValueError(f"pass {number}: missing or unexpected evidence files")
        product_capture, product_meta = _load_capture(
            folder / "product.json", folder / "product.meta.json"
        )
        _verify_evidence_source_url(
            product_capture.request_url, path=f"/v2/products/{SF088_SYMBOL}"
        )
        if product_meta.get("acquisition_version") != SF088_ACQUISITION_VERSION:
            raise ValueError("product acquisition version mismatch")
        product = parse_delta_product_response(product_capture, expected_symbol=SF088_SYMBOL)
        if (
            product.product_id != report["source_product_id"]
            or product.semantic_sha256 != report["source_product_semantic_sha256"]
        ):
            raise ValueError("product semantics contradict acquisition report")
        if product.api_origin != report["source_api_origin"]:
            raise ValueError("product origin mismatch")
        if number == 1:
            first_product_semantic = product.semantic_sha256
        elif product.semantic_sha256 != first_product_semantic:
            raise ValueError("product semantics changed across passes")
        issues: Counter[str] = Counter()
        examples = []
        semantic = []
        pass_coverage = bytearray(SF088_EXPECTED_MINUTES)
        rows = 0
        for chunk in plan:
            capture, meta = _load_capture(
                folder / f"chunk-{chunk.index:06d}.json",
                folder / f"chunk-{chunk.index:06d}.meta.json",
            )
            if (meta.get("acquisition_version") != SF088_ACQUISITION_VERSION
                or meta.get("canonical_start") != chunk.start.isoformat()
                or meta.get("canonical_end") != chunk.end.isoformat()
                or meta.get("provider_start") != chunk.provider_start
                or meta.get("provider_end") != chunk.provider_end):
                raise ValueError(f"pass {number} chunk {chunk.index}: sidecar contract mismatch")
            if meta.get("chunk_identity") != chunk.identity:
                raise ValueError(f"pass {number} chunk {chunk.index}: identity mismatch")
            _verify_evidence_source_url(
                capture.request_url, path="/v2/history/candles",
                params={"resolution": "1m", "symbol": SF088_SYMBOL,
                        "start": chunk.provider_start, "end": chunk.provider_end},
            )
            if capture.content_sha256 != report[f"{prefix}_pass_raw_sha256"][chunk.index]:
                raise ValueError(f"pass {number} chunk {chunk.index}: report raw hash mismatch")
            candles = parse_delta_candles_response(capture)
            digest = _candle_semantic_sha256(candles)
            if (
                digest != meta["semantic_sha256"]
                or digest != report[f"{prefix}_pass_semantic_sha256"][chunk.index]
            ):
                raise ValueError(f"pass {number} chunk {chunk.index}: semantic digest mismatch")
            expected_times = {
                int(chunk.start.timestamp()) + 60 * i
                for i in range(chunk.expected_minutes)
            }
            observed_times = [c.time for c in candles]
            if (meta.get("row_count") != len(candles)
                or meta.get("missing_count") != len(expected_times - set(observed_times))
                or meta.get("duplicate_count") != len(observed_times) - len(set(observed_times))):
                raise ValueError(
                    f"pass {number} chunk {chunk.index}: sidecar quality counts mismatch"
                )
            semantic.append(digest)
            rows += len(candles)
            for candle in candles:
                t = candle.time
                if t % 60:
                    issues["non_minute_aligned"] += 1
                if not start <= t < end:
                    issues["outside_frozen_window"] += 1
                if not int(chunk.start.timestamp()) <= t < int(chunk.end.timestamp()):
                    issues["outside_chunk_window"] += 1
                if t % 60 == 0 and start <= t < end:
                    index = (t - start) // 60
                    if pass_coverage[index]:
                        issues["duplicate_minute"] += 1
                    pass_coverage[index] = 1
                if candle.volume != candle.volume.to_integral_value():
                    issues["fractional_contract_volume"] += 1
                for field in ("open", "high", "low", "close"):
                    value = getattr(candle, field)
                    if value % product.tick_size != 0:
                        issues["off_current_snapshot_tick_price_fields"] += 1
                        if len(examples) < 100:
                            examples.append({
                            "utc": datetime.fromtimestamp(t, UTC).isoformat(),
                            "chunk": chunk.index, "field": field, "value": str(value),
                            "current_snapshot_tick_size": str(product.tick_size),
                        })
        missing = [i for i, flag in enumerate(pass_coverage) if not flag]
        if number == 1:
            coverage = pass_coverage
        elif pass_coverage != coverage:
            issues["cross_pass_timestamp_coverage_differs"] += 1
        results[f"pass_{number}"] = {
            "chunks": len(plan), "rows": rows,
            "unique_minute_count": sum(pass_coverage),
            "missing_minute_count": len(missing),
            "issues": dict(issues),
            "anomaly_examples": examples,
            "anomaly_examples_truncated": (
                issues["off_current_snapshot_tick_price_fields"] > len(examples)
            ),
            "product_snapshot": {
                "id": product.product_id, "symbol": product.symbol,
                "tick_size": str(product.tick_size),
                "contract_value": str(product.contract_value),
                "created_at": product.created_at.isoformat() if product.created_at else None,
                "updated_at": product.updated_at.isoformat() if product.updated_at else None,
            },
        }
        semantic_by_pass.append(semantic)
    missing_ranges = []
    first = previous = None
    for index, flag in enumerate(coverage):
        if flag:
            if first is not None:
                missing_ranges.append((first, previous + 1))
                first = previous = None
        elif first is None:
            first = previous = index
        else:
            previous = index
    if first is not None:
        missing_ranges.append((first, previous + 1))
    result = {
        "audit_contract": "sf088-offline-evidence-audit-v2",
        "source_generation": root.name,
        "frozen_start": SF088_START.isoformat(), "frozen_end": SF088_END.isoformat(),
        "expected_minutes": SF088_EXPECTED_MINUTES,
        "observed_unique_minutes_pass_1": sum(coverage),
        "missing_minutes_pass_1": SF088_EXPECTED_MINUTES - sum(coverage),
        "missing_intervals_utc": [{
            "start": datetime.fromtimestamp(start + a * 60, UTC).isoformat(),
            "end_exclusive": datetime.fromtimestamp(start + b * 60, UTC).isoformat(),
            "minutes": b - a,
        } for a, b in missing_ranges],
        "two_pass_semantic_match_independently_recomputed": (
            semantic_by_pass[0] == semantic_by_pass[1]
        ),
        "passes": results,
        "qualifies_historical_product_applicability": False,
        "canonical_dataset_published": False,
    }
    hard_issue_keys = {
        "non_minute_aligned", "outside_frozen_window", "outside_chunk_window",
        "duplicate_minute", "fractional_contract_volume",
        "cross_pass_timestamp_coverage_differs",
    }
    hard_fail = (
        any(results[f"pass_{n}"]["issues"].get(k, 0) for n in (1, 2) for k in hard_issue_keys)
        or any(results[f"pass_{n}"]["missing_minute_count"] for n in (1, 2))
        or not result["two_pass_semantic_match_independently_recomputed"]
    )
    result["audit_status"] = "FAIL" if hard_fail else "PASS_WITH_UNQUALIFIED_METADATA"
    result["audit_sha256"] = _sha256_json(result)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Read-only SF-088 evidence coverage and anomaly audit"
    )
    parser.add_argument("--generation-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    root = args.generation_dir.resolve(strict=True)
    output = args.output.resolve()
    if not any(part in {".signalforge-data", "signalforge-data"} for part in output.parts):
        parser.error("output must reside in a dedicated local signalforge-data directory")
    if root == output or root in output.parents or output in root.parents:
        parser.error("output must be outside the immutable evidence generation")
    if output.exists():
        parser.error("refusing to overwrite an existing audit report")
    report = audit_generation(root)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, sort_keys=True)
        handle.write("\n")
    print(json.dumps({
        "audit_status": report["audit_status"],
        "output": str(output), "audit_sha256": report["audit_sha256"],
        "unique_minutes": report["observed_unique_minutes_pass_1"],
        "missing_minutes": report["missing_minutes_pass_1"],
        "pass_1_issues": report["passes"]["pass_1"]["issues"],
        "pass_2_issues": report["passes"]["pass_2"]["issues"],
        "two_pass_semantic_match": report["two_pass_semantic_match_independently_recomputed"],
    }, sort_keys=True))
    return 0 if report["audit_status"] != "FAIL" else 1


if __name__ == "__main__":
    raise SystemExit(main())
