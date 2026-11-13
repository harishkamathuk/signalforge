"""Independent SF-260 90D source-only verification, no strategy evaluation.

Recompute the protected parent audit, ordered original observations, child
identity, canonical source-only run identities and profile custody receipts.
No scenario runner/run_verified is imported or invoked.
"""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import os
import resource
import sys
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

# Direct absolute-path invocation otherwise exposes scripts/, not its parent.
# The import root is derived from this checked-out file, never operator input.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from scripts.stage6_90d_source_preflight import (  # noqa: E402
    MEMORY_LIMIT,
    PRIVATE,
    PROFILES,
    SOURCE,
    git_revision,
    require_limits,
)
from signalforge.config.identity import canonical_config_json, config_hash  # noqa: E402
from signalforge.domain.time import CandleInterval  # noqa: E402
from signalforge.research.audited_source_slice_v1 import (  # noqa: E402
    DERIVATION_VERSION,
    IS_CANDLES,
    IS_START,
    MEASURED_END,
    OOS_CANDLES,
    OOS_START,
    PARENT_DATASET_HASH,
    SOURCE_MINUTES,
    SOURCE_START,
)
from signalforge.research.btc_raw_diagnostic_input import (  # noqa: E402
    FROZEN_PROVISIONAL_REPORT_SHA256,
    load_sf095_raw_diagnostic_source,
)
from signalforge.research.delta_historical_evidence_audit import audit_generation  # noqa: E402
from signalforge.research.historical_bars import HistoricalBarDataset  # noqa: E402
from signalforge.research.historical_grid import HistoricalBarGrid  # noqa: E402

CONFIG_HASH = "88e90c23cd635248385d820406ef2201badc59bfd9f99043a63e8823227de242"
ASSUMPTIONS_HASH = "b7d89c3bcdfda94eb7b489ff12c03ab313573445bbf558fa4d10ce58ff081dc6"
RESOURCE_HASH = "28ecfb2d956a60ffbc33d334aeb379fcbabe61e056e3e254112ec34b0310c9d6"
RAW_PROFILE_HASHES = {
    "REFERENCE_RAW": "617e9e7698cc563c014e2b37699f704d863e7ae83a7bc5341ba2631f81574905",
    "ADVERSE_RAW": "2461fb0042083d97cdac511312ade824990f7965c68bc34f726fdf4a80bba875",
}


class VerificationBlocked(ValueError):
    """Source and/or canonical prereg cannot be independently reconciled."""


def check(condition: bool, reason: str) -> None:
    if not condition:
        raise VerificationBlocked(reason)


def decode_tagged(node: object) -> object:
    """Strict independent canonical decoder; reject duplicate/unsorted map keys."""
    check(isinstance(node, list) and node and isinstance(node[0], str),
          "invalid canonical type tag")
    typ = node[0]
    if typ == "null":
        check(len(node) == 1, "invalid null tag")
        return None
    check(len(node) == 2, "invalid canonical tag length")
    value = node[1]
    if typ == "str":
        check(type(value) is str, "invalid string tag")
        return value
    if typ == "bool":
        check(type(value) is bool, "invalid boolean tag")
        return value
    if typ == "int":
        check(type(value) is str and str(int(value)) == value, "invalid integer tag")
        return int(value)
    if typ == "decimal":
        check(type(value) is str, "invalid decimal tag")
        decimal = Decimal(value)
        check(decimal.is_finite(), "nonfinite decimal tag")
        return decimal
    if typ == "list":
        check(isinstance(value, list), "invalid list tag")
        return [decode_tagged(item) for item in value]
    if typ == "map":
        check(isinstance(value, list), "invalid map tag")
        decoded: dict[str, object] = {}
        previous: str | None = None
        for pair in value:
            check(isinstance(pair, list) and len(pair) == 2 and type(pair[0]) is str,
                  "invalid canonical map member")
            key = pair[0]
            check(previous is None or key > previous, "duplicate/unsorted canonical map key")
            decoded[key] = decode_tagged(pair[1])
            previous = key
        return decoded
    raise VerificationBlocked("unknown canonical type tag")


def read_canonical(path: Path) -> tuple[dict[str, Any], str]:
    check(path.is_file() and not path.is_symlink(), "missing/linked private receipt")
    check(path.stat().st_mode & 0o077 == 0, "non-private source-only artifact")
    data = path.read_bytes()
    root = decode_tagged(json.loads(data))
    check(isinstance(root, dict), "invalid canonical manifest shape")
    check(data == (canonical_config_json(root) + "\n").encode("utf-8"),
          "noncanonical source-only artifact bytes")
    return root, hashlib.sha256(data).hexdigest()


def independently_verified_lineage() -> tuple[dict[str, object], str]:
    """Compute child SHA and 5m close digest without invoking producer factory."""
    audit = audit_generation(SOURCE)
    check(audit["audit_status"] == "PASS_WITH_UNQUALIFIED_METADATA",
          "parent independent audit failed")
    check(audit["two_pass_semantic_match_independently_recomputed"] is True,
          "parent two-pass audit mismatch")
    parent = load_sf095_raw_diagnostic_source(SOURCE)
    check(
        parent.source_diagnostic_id == FROZEN_PROVISIONAL_REPORT_SHA256
        and parent.dataset.content_hash == PARENT_DATASET_HASH,
        "parent source hash/provenance mismatch",
    )
    ds = parent.dataset
    bars = ds.bars[:SOURCE_MINUTES]
    check(
        len(bars) == SOURCE_MINUTES
        and bars[0].interval.start == SOURCE_START
        and bars[-1].interval.end == MEASURED_END,
        "source-only slice boundaries invalid",
    )
    h = hashlib.sha256()
    h.update(b"sf260-ordered-one-minute-bars-v1\n")
    five_closes: list[object] = []
    for index, bar in enumerate(bars):
        start = SOURCE_START + timedelta(minutes=index)
        check(bar.interval.start == start and bar.interval.end ==
              start + timedelta(minutes=1), "nonunique/incorrect one-minute source key")
        h.update(canonical_config_json(bar.semantic_mapping()).encode("utf-8"))
        h.update(b"\n")
        if index % 5 == 4:
            five_closes.append(bar.close.value)
    check(len(five_closes) == SOURCE_MINUTES // 5, "five-minute source grid incomplete")
    grid = HistoricalBarGrid(
        "sf260-approved-90d-source", "1",
        (CandleInterval(SOURCE_START, MEASURED_END),),
    )
    manifest = replace(
        ds.manifest,
        requested_start=SOURCE_START, requested_end=MEASURED_END,
        returned_start=SOURCE_START, returned_end=MEASURED_END,
        raw_row_count=SOURCE_MINUTES, canonical_row_count=SOURCE_MINUTES,
        duplicate_observation_count=0, corrupt_rejected_count=0,
        missing_interval_count=0, grid=grid,
        limitations=tuple(
            "parent_full_year_" + label
            if label.startswith((
                "five_minute_close_sha256=",
                "frozen_provisional_report_sha256=",
            ))
            else label
            for label in ds.manifest.limitations
        ),
    )
    child = HistoricalBarDataset(manifest, bars)
    close_sha = config_hash({"close": five_closes})
    lineage: dict[str, object] = {
        "domain": DERIVATION_VERSION,
        "parent_dataset_hash": PARENT_DATASET_HASH,
        "parent_diagnostic_id": parent.source_diagnostic_id,
        "source_start": SOURCE_START.isoformat(),
        "source_end": MEASURED_END.isoformat(),
        "child_dataset_hash": child.content_hash,
        "child_manifest": child.manifest.semantic_mapping(),
        "ordered_one_minute_sha256": h.hexdigest(),
        "derived_five_minute_close_digest": close_sha,
        "historical_metadata_status": "UNQUALIFIED_HISTORICAL_METADATA",
        "execution_valid": False,
    }
    del child, parent, ds, bars, five_closes
    gc.collect()
    check(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024 < MEMORY_LIMIT,
          "independent audit/slice exceeded RSS ceiling")
    return lineage, config_hash(lineage)


def verify_source_only() -> dict[str, object]:
    require_limits()  # Before reading historical source.
    revision = git_revision()
    check(PRIVATE.is_dir() and not PRIVATE.is_symlink()
          and PRIVATE.stat().st_mode & 0o077 == 0, "unsafe private prereg directory")
    receipt, receipt_sha = read_canonical(PRIVATE / "source-only-readiness.json")
    check(
        receipt.get("contract") == "sf260-90d-source-only-prereg-v1"
        and receipt.get("disposition") == "PREPARATION_ONLY_GATE_D_WITHHELD"
        and receipt.get("gate_d_approved") is False
        and receipt.get("protected_scenario_executed") is False
        and receipt.get("execution_valid") is False
        and receipt.get("revision") == revision,
        "missing or mismatched versioned source-only attestation",
    )
    lineage, derived_id = independently_verified_lineage()
    check(receipt.get("source_lineage") == lineage
          and receipt.get("derivation_id") == derived_id,
          "independent derived source proof differs")
    rows = receipt.get("profiles")
    check(isinstance(rows, list) and len(rows) == 2, "wrong source-only profile count")
    run_rows: list[list[str]] = []
    for index, profile in enumerate(PROFILES):
        row = rows[index]
        check(isinstance(row, dict) and row.get("profile") == profile,
              "source-only profile/order mismatch")
        name = f"{profile.lower()}-manifest.json"
        check(row.get("filename") == name, "profile filename mismatch")
        record, content_sha = read_canonical(PRIVATE / name)
        mapping = record.get("input_mapping")
        check(isinstance(mapping, dict), "missing typed scenario manifest input")
        check(record.get("scenario_run_id") ==
              config_hash({"domain": "scenario-run-v1", "inputs": mapping}),
              "source-only domain-separated run identity mismatch")
        check(row.get("run_id") == record["scenario_run_id"]
              and row.get("canonical_sha256") == content_sha,
              "source-only profile hash/readback mismatch")
        mode = mapping.get("mode_and_schema")
        check(
            mode == {
                "mode": "SCENARIO_RESEARCH",
                "schema": "scenario-manifest-v1",
                "simulator": "btc-ohlc-path-scenario-v1",
                "study_variant": "SF260_90D_AUDITED_V1",
                "sample_status": "REPEATED_SAMPLE",
                "window_selection": "EARLIEST_90_MEASURED_UTC_DAYS",
            },
            "90D variant manifest mode differs",
        )
        source = mapping.get("source")
        check(isinstance(source, dict) and source.get("audited_slice_lineage") == lineage
              and source.get("dataset_id") == lineage["child_dataset_hash"]
              and source.get("content_hash") == lineage["child_dataset_hash"]
              and source.get("source_diagnostic_id") == derived_id,
              "profile source lineage/hash mismatch")
        check(
            source.get("manifest") == lineage["child_manifest"],
            "profile source manifest differs from independently audited child",
        )
        # Source-bound digest is independently recomputed from verified 1m closes.
        check(source.get("five_minute_close_digest") ==
              lineage["derived_five_minute_close_digest"],
              "source five-minute digest drift")
        session = mapping.get("session_and_window")
        check(isinstance(session, dict)
              and session.get("pre_roll_start") == SOURCE_START.isoformat()
              and session.get("is_start") == IS_START.isoformat()
              and session.get("oos_start") == OOS_START.isoformat()
              and session.get("measured_end") == MEASURED_END.isoformat(),
              "approved study window changed")
        strategy = mapping.get("strategy")
        check(
            isinstance(strategy, dict)
            and strategy.get("id") == "btc_momentum_baseline_v0"
            and strategy.get("version") == "0.1.0-experimental"
            and strategy.get("config_id") == CONFIG_HASH
            and strategy.get("config_hash") == CONFIG_HASH
            and strategy.get("engine_calculation_version") == "engine-v1"
            and strategy.get("synthetic_fixture_identity") is None,
            "frozen strategy/config identity mismatch",
        )
        assumptions = mapping.get("assumptions")
        check(
            isinstance(assumptions, dict)
            and assumptions.get("scenario_id") == "BTC_OHLC_PATH_V1"
            and assumptions.get("scenario_version") == "0.1.0-proposal"
            and assumptions.get("semantic_hash") == ASSUMPTIONS_HASH
            and config_hash({
                key: value for key, value in assumptions.items()
                if key != "semantic_hash"
            }) == ASSUMPTIONS_HASH,
            "scenario assumption preimage changed",
        )
        fills = mapping.get("fills")
        check(
            isinstance(fills, dict)
            and fills.get("profile_id") == profile
            and fills.get("version") == "1.0.0"
            and fills.get("price_mode") == "raw_diagnostic"
            and fills.get("tick_rule_version") == "unresolved"
            and config_hash(fills) == RAW_PROFILE_HASHES[profile],
            "frozen RAW profile semantics mismatch",
        )
        impl = mapping.get("implementation")
        check(
            isinstance(impl, dict)
            and impl == {
                "revision": revision,
                "canonical_serializer": "canonical-config-json-v1",
                "scenario_calculation_version": "btc-ohlc-path-scenario-v1",
            },
            "source-only execution revision/serializer drift",
        )
        policy = mapping.get("resource_policy")
        check(
            isinstance(policy, dict)
            and config_hash(policy) == RESOURCE_HASH
            and mapping.get("resource_policy_semantic_hash") == RESOURCE_HASH,
            "finite resource contract differs",
        )
        run_rows.append([profile, str(record["scenario_run_id"]), content_sha])
    candidate = config_hash({
        "domain": "sf260-90d-source-only-prereg-v1",
        "revision": revision, "slice_derivation_id": derived_id,
        "profiles": run_rows,
    })
    check(receipt.get("input_preregistration_id") == candidate,
          "independent canonical prereg control mismatch")
    check(IS_CANDLES == 17_280 and OOS_CANDLES == 8_640,
          "frozen methodological grid drift")
    return {
        "status": "SOURCE_ONLY_INDEPENDENTLY_VERIFIED_NO_GATE_D",
        "preregistration_id": candidate, "receipt_sha256": receipt_sha,
        "audit_recomputed": True, "source_only": True,
        "protected_scenario_executed": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--independent-source-only-verify", action="store_true")
    parser.add_argument("--write-private-receipt", action="store_true")
    args = parser.parse_args(argv)
    if not args.independent_source_only_verify:
        parser.error("explicit independent source-only verification is required")
    try:
        result = verify_source_only()
        if args.write_private_receipt:
            receipt = {
                "contract": "sf260-90d-independent-source-only-v1",
                "revision": git_revision(),
                **result,
                "gate_d_approved": False,
                "execution_valid": False,
            }
            fd = os.open(
                PRIVATE / "independent-verification.json",
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
            )
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as output:
                output.write(canonical_config_json(receipt) + "\n")
                output.flush()
                os.fsync(output.fileno())
    except (OSError, ValueError, VerificationBlocked) as exc:
        parser.exit(2, f"SF260 SOURCE-ONLY VERIFICATION BLOCKED: {exc}\n")
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
