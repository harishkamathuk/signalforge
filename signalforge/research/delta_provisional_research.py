"""Read-only, unqualified BTCUSD price-series exploration from immutable SF-088 evidence.

This module never publishes a canonical HistoricalBarDataset, qualifies a
historical product rule, evaluates a strategy, or estimates executable P&L.
"""
from __future__ import annotations

import argparse
import json
from collections import deque
from collections.abc import Iterable
from datetime import UTC, datetime
from decimal import Decimal, localcontext
from hashlib import sha256
from pathlib import Path

from signalforge.research.delta_historical_dataset_acquisition import (
    SF088_END,
    SF088_EXPECTED_MINUTES,
    SF088_START,
    _candle_semantic_sha256,
    _canonical_decimal,
    _sha256_json,
    build_sf088_chunk_plan,
)
from signalforge.research.delta_historical_evidence_audit import (
    _load_capture,
    audit_generation,
)
from signalforge.research.delta_historical_qualification import (
    DeltaCandle,
    parse_delta_candles_response,
)

PROVISIONAL_CONTRACT = "sf088-provisional-price-exploration-v1"
UNQUALIFIED_STATUS = "UNQUALIFIED_HISTORICAL_METADATA"


def summarize_completed_five_minute_closes(
    candles: Iterable[DeltaCandle],
) -> dict[str, object]:
    """Summarize completed UTC five-minute closes and trailing SMA(20).

    Args:
        candles: Strictly consecutive one-minute candles ordered by UTC open.

    Returns:
        Deterministic counts and SHA-256 digests of the derived close/SMA
        observations; no price series or strategy signals are published.

    Raises:
        ValueError: If minutes are missing, duplicated, misaligned or a final
            five-minute group is incomplete.

    Notes:
        SMA(20) is the arithmetic mean of the latest 20 *completed* five-minute
        closes, including the current completed bar. The first 19 values are
        absent. A fixed decimal context avoids ambient precision changes.
    """
    closes_digest = sha256()
    sma_digest = sha256()
    last_minute: int | None = None
    bucket: list[Decimal] = []
    window: deque[Decimal] = deque()
    rolling = Decimal(0)
    minute_count = five_count = sma_count = 0
    first_sma_available_at: str | None = None
    last_sma_available_at: str | None = None

    with localcontext() as context:
        context.prec = 40
        for candle in candles:
            minute = candle.time
            if minute % 60 or (last_minute is not None and minute != last_minute + 60):
                raise ValueError("provisional input must have consecutive UTC minutes")
            # A group must start on a real UTC five-minute boundary; a partial
            # group must never be misrepresented as a completed five-minute bar.
            if not bucket and minute % 300:
                raise ValueError("provisional input begins mid-five-minute bucket")
            last_minute = minute
            minute_count += 1
            bucket.append(candle.close)
            if len(bucket) != 5:
                continue
            completed_close = bucket[-1]
            bucket.clear()
            five_count += 1
            closes_digest.update(
                f"{minute - 240}:{_canonical_decimal(completed_close)}\n".encode("ascii")
            )
            window.append(completed_close)
            rolling += completed_close
            if len(window) > 20:
                rolling -= window.popleft()
            if len(window) == 20:
                sma_count += 1
                sma = rolling / Decimal(20)
                # The digest labels the completed candle by its UTC open, while
                # its value only becomes available at the end-exclusive boundary.
                available_at = datetime.fromtimestamp(minute + 60, UTC).isoformat()
                if first_sma_available_at is None:
                    first_sma_available_at = available_at
                last_sma_available_at = available_at
                sma_digest.update(
                    f"{minute - 240}:{_canonical_decimal(sma)}\n".encode("ascii")
                )
    if bucket:
        raise ValueError("provisional input ends in incomplete five-minute bucket")
    if not minute_count:
        raise ValueError("provisional input contains no candles")
    return {
        "one_minute_candles": minute_count,
        "completed_five_minute_closes": five_count,
        "five_minute_close_sha256": closes_digest.hexdigest(),
        "sma20_completed_points": sma_count,
        "sma20_sha256": sma_digest.hexdigest(),
        "sma20_first_available_at_utc": first_sma_available_at,
        "sma20_last_available_at_utc": last_sma_available_at,
        "sma20_warmup_completed_bars": min(five_count, 19),
    }


def explore_generation(generation_dir: Path) -> dict[str, object]:
    """Audit and explore the frozen raw evidence without qualifying metadata.

    Args:
        generation_dir: Existing immutable SF-088 evidence-only generation.

    Returns:
        Local-only diagnostic report with explicit unqualified provenance.

    Raises:
        ValueError: If independent audit or source identity/coverage fails.
    """
    root = generation_dir.resolve(strict=True)
    # The established audit validates both passes, sidecars, source identities,
    # raw/semantic hashes and complete coverage before any derived observation.
    audit = audit_generation(root)
    if (
        root.name != "generation-0001"
        or audit["audit_status"] != "PASS_WITH_UNQUALIFIED_METADATA"
        or audit["frozen_start"] != SF088_START.isoformat()
        or audit["frozen_end"] != SF088_END.isoformat()
        or audit["observed_unique_minutes_pass_1"] != SF088_EXPECTED_MINUTES
        or not audit["two_pass_semantic_match_independently_recomputed"]
    ):
        raise ValueError("provisional exploration requires complete, audited generation-0001")

    report = json.loads((root / "evidence-only-report.json").read_text(encoding="utf-8"))
    plan = build_sf088_chunk_plan()

    def verified_first_pass() -> Iterable[DeltaCandle]:
        for chunk in plan:
            prefix = root / "pass-1" / f"chunk-{chunk.index:06d}"
            capture, meta = _load_capture(
                prefix.with_suffix(".json"), prefix.with_suffix(".meta.json")
            )
            if capture.content_sha256 != report["first_pass_raw_sha256"][chunk.index]:
                raise ValueError("provisional raw evidence changed after audit")
            values = parse_delta_candles_response(capture)
            if (
                _candle_semantic_sha256(values) != meta["semantic_sha256"]
                or meta["semantic_sha256"]
                != report["first_pass_semantic_sha256"][chunk.index]
            ):
                raise ValueError("provisional semantic evidence changed after audit")
            # Delta returns newest-first within each chunk. Chronology is
            # explicit and only the already-validated frozen generation is used.
            yield from sorted(values, key=lambda candle: candle.time)

    summary = summarize_completed_five_minute_closes(verified_first_pass())
    if (
        summary["one_minute_candles"] != SF088_EXPECTED_MINUTES
        or summary["completed_five_minute_closes"] != SF088_EXPECTED_MINUTES // 5
    ):
        raise ValueError("provisional derived coverage contradicts frozen interval")
    results: dict[str, object] = {
        "contract": PROVISIONAL_CONTRACT,
        "source_generation": root.name,
        "source_product_id": 27,
        "source_symbol": "BTCUSD",
        "frozen_start": SF088_START.isoformat(),
        "frozen_end": SF088_END.isoformat(),
        "evidence_report_sha256": report["report_sha256"],
        "independent_audit_sha256": audit["audit_sha256"],
        "independent_audit_status": audit["audit_status"],
        "historical_metadata_status": UNQUALIFIED_STATUS,
        "canonical_dataset_published": False,
        "strategy_or_trade_performance_authorized": False,
        "historical_tick_size_assumed": False,
        "source_prices_repaired": False,
        "limitations": [
            "Historical contract/tick applicability unproven",
            "SMA is exploratory, not a trading signal or backtest",
            "No simulated fills, contract-value P&L, or strategy promotion",
        ],
        "current_snapshot_tick_observations": audit["passes"]["pass_1"][
            "anomaly_examples"
        ],
        "current_snapshot_tick_observation_count": audit["passes"]["pass_1"][
            "issues"
        ].get("off_current_snapshot_tick_price_fields", 0),
        "derived_price_diagnostics": summary,
    }
    results["report_sha256"] = _sha256_json(results)
    return results


def main(argv: list[str] | None = None) -> int:
    """Write an explicit, local-only, write-once provisional report."""
    parser = argparse.ArgumentParser(
        description="Unqualified, read-only SF-088 five-minute price/SMA exploration"
    )
    parser.add_argument("--generation-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    root = args.generation_dir.resolve(strict=True)
    output = args.output.resolve()
    # Bind the report to the SAME .signalforge-data root as the protected source.
    # A similarly named directory elsewhere need not be Git-ignored; resolving
    # first prevents a symlinked parent from escaping this boundary.
    protected_root = next(
        (parent for parent in (root, *root.parents) if parent.name == ".signalforge-data"),
        None,
    )
    if protected_root is None:
        parser.error("generation must reside under the protected .signalforge-data root")
    # Confine reports to the dedicated audit subtree, never another immutable
    # generation or an unrelated location under the protected data root.
    audits_root = protected_root / "sf088" / "audits"
    if not output.is_relative_to(audits_root) or output == audits_root:
        parser.error("output must stay under the source .signalforge-data/sf088/audits")
    if output == root or output.is_relative_to(root):
        parser.error("output must be outside the immutable evidence generation")
    if output.exists():
        parser.error("refusing to overwrite existing provisional report")
    result = explore_generation(root)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2, sort_keys=True)
        handle.write("\n")
    print(json.dumps({
        "status": UNQUALIFIED_STATUS,
        "audit_status": result["independent_audit_status"],
        "output": str(output),
        "report_sha256": result["report_sha256"],
        "derived_price_diagnostics": result["derived_price_diagnostics"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
