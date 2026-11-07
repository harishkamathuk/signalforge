"""Read-only SF-261 Gate D preflight: verify SF-088 and freeze scenario inputs.

This operator tool is NOT an experiment runner. It must never evaluate BTC
strategy signals, process hypothetical paths, execute protected IS/OOS
performance, contact a provider, or declare Gate D approved. It writes only
input manifests and sanitized provenance to a private directory.

Run from a clean post-Gate-C develop checkout with the protected local archive.
See docs/engineering/stage6-gate-d-preflight.md and GitHub #261.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

BASELINE_SHA = "5d2812d11f8f5f061a1b637726f9e73b488c6e43"
SOURCE_REPORT_SHA256 = "8632150c1aa75689cb9b3fd933dc3e3d0672ce7eb31c1772b9597d7ce57b7ff6"
SOURCE_AUDIT_SHA256 = "cecc741b67e394e93fa73d578c6c710a806c46b8a26712830d508048de8269e7"
SOURCE_DATASET_HASH = "85d89887078504385a5023eaba007ffcdeeb7f4c67689c79cd5db9a407c999f9"
FIVE_MINUTE_CLOSE_SHA256 = "0787429a8203913b08b954c40d8dc57a0bad0be4b367a7d39580cdaf311733b8"
STRATEGY_CONFIG_HASH = "88e90c23cd635248385d820406ef2201badc59bfd9f99043a63e8823227de242"
SCENARIO_SEMANTIC_HASH = "b7d89c3bcdfda94eb7b489ff12c03ab313573445bbf558fa4d10ce58ff081dc6"
RESOURCE_SEMANTIC_HASH = "28ecfb2d956a60ffbc33d334aeb379fcbabe61e056e3e254112ec34b0310c9d6"
EXPECTED_MINUTES = 525_600
EXPECTED_FIVE_MINUTES = 105_120
EXPECTED_FILE_COUNT = 1_057
EXPECTED_SOURCE_BYTES = 101_674_328
RESOURCE_LIMITS = {
    "policy_id": "FINITE_FAIL_CLOSED",
    "version": "1.0.0",
    "max_bars": 524_160,
    "max_events": 2_096_640,
    "max_outcomes": 104_833,
    "max_trace_records": 2_096_640,
    "max_states": 1,
}
FROZEN_CODE_PATHS = (
    # Pin the complete implementation dependency closure, not merely the
    # manifest entry point: transitive domain/indicator changes can silently
    # change the meaning of the registered calculation without changing it.
    "signalforge",
    "docs/architecture/decisions/ADR-011-scenario-execution-proposed-amendment.md",
    "docs/architecture/execution-scenario-modelling-contract-proposal.md",
    "docs/strategies/btc-momentum-baseline-v0.md",
    "docs/validation/btc-momentum-baseline-v0-validation-v0.md",
    "docs/validation/btc-momentum-baseline-v0-scenario-validation-v0-proposal.md",
)


class PreflightError(ValueError):
    """Missing, contradictory, or unsafe prerequisite; never infer readiness."""


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise PreflightError(reason)


def _git(root: Path, *args: str) -> str:
    command = ["git", "-C", str(root), *args]
    result = subprocess.run(command, check=False, capture_output=True, text=True, timeout=20)
    if result.returncode:
        raise PreflightError("Git verification failed: " + " ".join(args))
    return result.stdout.strip()


def verify_revision(root: Path) -> str:
    """Require clean develop and unchanged frozen calculation/contract files.

    Args:
        root: Local repository root; the script itself is not an execution revision.

    Returns:
        Current fully qualified integration commit.

    Raises:
        PreflightError: If a dirty, unpinned, or modified implementation is found.
    """
    _require(_git(root, "rev-parse", "--show-toplevel") == str(root.resolve()),
             "repository root mismatch")
    _require(_git(root, "symbolic-ref", "--short", "HEAD") == "develop",
             "preflight requires local develop")
    _require(not _git(root, "status", "--porcelain", "--untracked-files=normal"),
             "working tree is not clean")
    head = _git(root, "rev-parse", "HEAD")
    _require(len(head) == 40, "invalid Git commit")
    _git(root, "merge-base", "--is-ancestor", BASELINE_SHA, head)
    _require(
        not _git(root, "diff", "--name-only", BASELINE_SHA, head, "--", *FROZEN_CODE_PATHS),
        "frozen Gate C implementation or accepted contracts changed",
    )
    return head


def _protected_root(path: Path) -> Path:
    _require(not path.is_symlink(), "protected generation path must not be a symlink")
    resolved = path.resolve(strict=True)
    _require(path.absolute() == resolved, "protected source must have no symlink ancestor")
    _require(
        resolved.parts[-5:] == (
            ".signalforge-data", "sf088", "evidence", "evidence-only", "generation-0001"
        ),
        "source is not the exact protected SF-088 generation-0001 root",
    )
    _require(resolved.is_dir(), "protected source is not a directory")
    return resolved


def inventory(root: Path) -> dict[str, object]:
    """Fingerprint raw archive files without recording their paths or contents.

    Args:
        root: Validated protected generation root.

    Returns:
        Source count, total size and deterministic streaming inventory digest.

    Raises:
        PreflightError: For symlinks, special files or unreadable evidence.

    Notes:
        This digest uses a newly declared inventory encoding, so it is
        comparable *before vs after* this invocation, not to the unrelated
        historical SF-096 inventory hash.
    """
    digest = hashlib.sha256()
    files = 0
    total = 0
    for path in sorted(root.rglob("*")):
        info = path.lstat()
        _require(not stat.S_ISLNK(info.st_mode), "symlink in protected source archive")
        if stat.S_ISDIR(info.st_mode):
            continue
        _require(stat.S_ISREG(info.st_mode), "non-regular protected source evidence")
        part = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1_048_576), b""):
                part.update(block)
        entry = [path.relative_to(root).as_posix(), info.st_size, part.hexdigest()]
        digest.update(json.dumps(entry, separators=(",", ":"), ensure_ascii=True).encode())
        digest.update(b"\n")
        files += 1
        total += info.st_size
    return {"file_count": files, "total_bytes": total, "inventory_sha256_v1": digest.hexdigest()}


def _output_dir(path: Path, repo: Path) -> Path:
    _require(not path.is_symlink(), "output directory must not be a symlink")
    resolved = path.resolve(strict=True)
    _require(resolved == path.absolute(), "output directory has a symlink ancestor")
    _require(resolved.is_dir(), "output destination must already be a directory")
    _require(not resolved.is_relative_to(repo.resolve()), "output must be outside Git repository")
    _require(
        not any(part in (".signalforge-data", "sf088", "sf096") for part in resolved.parts),
        "output must be outside protected historical evidence trees",
    )
    _require(resolved.stat().st_mode & 0o077 == 0,
             "output directory must have private 0700-style permissions")
    return resolved


def _exclusive_json(path: Path, payload: str) -> None:
    """Create a private evidence file without overwriting existing bytes."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        stream.write(payload)
    _require(path.stat().st_mode & 0o077 == 0, "output file permissions not private")


def _equal(actual: object, expected: object, field: str) -> None:
    _require(actual == expected, "frozen identity mismatch: " + field)


def verify_source(root: Path) -> tuple[Any, tuple[Any, ...], dict[str, object]]:
    """Audit both passes, the frozen bridge and complete 1m/5m source, not outcomes.

    Args:
        root: Protected evidence root.

    Returns:
        Audited raw source, completed 5m candles and sanitized source summary.

    Raises:
        PreflightError: For any source identity or continuity contradiction.
    """
    # Imports are deliberately limited to source/audit/aggregation code.
    # Never call ScenarioResearchRunner.run or run_verified in this tool.
    from signalforge.domain.market import CandleQuality
    from signalforge.research.btc_raw_diagnostic_input import (
        load_sf095_raw_diagnostic_source,
    )
    from signalforge.research.delta_historical_evidence_audit import audit_generation
    from signalforge.research.delta_provisional_research import explore_generation
    from signalforge.research.historical_bars import (
        HistoricalPriceBasis,
        aggregate_one_minute_to_five_minute,
    )

    audit = audit_generation(root)
    _equal(audit["audit_status"], "PASS_WITH_UNQUALIFIED_METADATA", "source audit status")
    _equal(audit["audit_sha256"], SOURCE_AUDIT_SHA256, "independent source audit digest")
    _require(bool(audit["two_pass_semantic_match_independently_recomputed"]),
             "SF-088 two-pass semantic mismatch")
    report = explore_generation(root)
    _equal(report["report_sha256"], SOURCE_REPORT_SHA256, "frozen provisional report")
    _equal(report["historical_metadata_status"], "UNQUALIFIED_HISTORICAL_METADATA",
           "source metadata qualification")
    _equal(report["canonical_dataset_published"], False, "canonical publication")
    derived = report["derived_price_diagnostics"]
    _equal(derived["one_minute_candles"], EXPECTED_MINUTES, "1m report coverage")
    _equal(derived["completed_five_minute_closes"], EXPECTED_FIVE_MINUTES,
           "5m report coverage")
    _equal(derived["five_minute_close_sha256"], FIVE_MINUTE_CLOSE_SHA256,
           "original 5m-close digest")
    source = load_sf095_raw_diagnostic_source(root)
    _equal(source.source_diagnostic_id, SOURCE_REPORT_SHA256, "diagnostic identity")
    _equal(source.dataset.content_hash, SOURCE_DATASET_HASH, "dataset semantic content")
    _equal(str(source.dataset.dataset_id), SOURCE_DATASET_HASH, "diagnostic dataset ID")
    _require(not source.execution_valid, "source unexpectedly execution valid")
    ds = source.dataset
    _equal(ds.manifest.price_basis, HistoricalPriceBasis.TRADED, "traded price basis")
    _equal(len(ds.bars), EXPECTED_MINUTES, "source 1m bar count")
    _equal(ds.manifest.missing_interval_count, 0, "missing 1m bars")
    _equal(ds.manifest.duplicate_observation_count, 0, "duplicate 1m bars")
    _equal(ds.manifest.corrupt_rejected_count, 0, "corrupt 1m bars")
    candles = aggregate_one_minute_to_five_minute(ds)
    _equal(len(candles), EXPECTED_FIVE_MINUTES, "derived 5m candle count")
    _require(all(c.quality is CandleQuality.VALID for c in candles),
             "incomplete or invalid derived 5m candle")
    return source, candles, {
        "source_generation": "generation-0001",
        "source_diagnostic_id": source.source_diagnostic_id,
        "independent_audit_sha256": audit["audit_sha256"],
        "provisional_report_sha256": report["report_sha256"],
        "dataset_id": str(ds.dataset_id),
        "dataset_content_hash": ds.content_hash,
        "original_five_minute_close_sha256": derived["five_minute_close_sha256"],
        "one_minute_count": len(ds.bars),
        "five_minute_count": len(candles),
        "historical_tick_applicability": "UNRESOLVED",
        "historical_metadata_status": "UNQUALIFIED_HISTORICAL_METADATA",
        "execution_valid": False,
    }


def freeze_manifests(
    source: Any, candles: tuple[Any, ...]
) -> tuple[list[tuple[str, str, str, str]], str]:
    """Derive actual input-only run IDs with the accepted unmodified builder.

    Args:
        source: Freshly audited protected raw source.
        candles: Independently aggregated complete 5m source candles.

    Returns:
        Profile name, run ID, canonical manifest JSON, manifest SHA-256 pairs
        and a pre-registration identity.

    Notes:
        Only the pure _manifest construction path is entered. Neither strategy
        evaluation nor scenario performance is executed.
    """
    from signalforge.config.identity import canonical_config_json, config_hash
    from signalforge.config.strategy_registry import (
        DEFAULT_STRATEGY_REGISTRY,
        StrategySelection,
    )
    from signalforge.research.historical_execution import HistoricalExecutionAssumptionProfile
    from signalforge.research.scenario_execution import (
        ScenarioAssumptionSet,
        ScenarioMode,
        ScenarioResearchRequest,
        ScenarioResourcePolicy,
        _manifest,
    )

    selection = StrategySelection("btc_momentum_baseline_v0", "0.1.0-experimental", {})
    strategy = DEFAULT_STRATEGY_REGISTRY.resolve(selection)
    _equal(strategy.config_identity.config_hash, STRATEGY_CONFIG_HASH, "strategy config hash")
    assumptions = ScenarioAssumptionSet.btc_ohlc_path_v1()
    _equal(assumptions.semantic_hash, SCENARIO_SEMANTIC_HASH, "scenario semantic hash")
    resources = ScenarioResourcePolicy(**RESOURCE_LIMITS)
    _equal(config_hash(resources.mapping()), RESOURCE_SEMANTIC_HASH, "resource semantic hash")
    start = datetime(2025, 10, 31, tzinfo=UTC)
    split = datetime(2026, 7, 1, tzinfo=UTC)
    end = datetime(2026, 10, 30, tzinfo=UTC)
    manifests: list[tuple[str, str, str, str]] = []
    for profile in (
        HistoricalExecutionAssumptionProfile.reference_raw(),
        HistoricalExecutionAssumptionProfile.adverse_raw(),
    ):
        request = ScenarioResearchRequest(
            mode=ScenarioMode.SCENARIO_RESEARCH,
            source=source,
            strategy_selection=selection,
            engine_calculation_version="engine-v1",
            assumptions=assumptions,
            profile=profile,
            resources=resources,
            is_start=start,
            oos_start=split,
            measured_end=end,
            repository_revision=BASELINE_SHA,
        )
        manifest = _manifest(request, strategy, candles)
        mapping = manifest.mapping()
        _equal(mapping["implementation"]["revision"], BASELINE_SHA, "execution revision")
        _equal(mapping["assumptions"]["semantic_hash"], SCENARIO_SEMANTIC_HASH,
               "manifest scenario mapping")
        _equal(mapping["source"]["content_hash"], SOURCE_DATASET_HASH, "manifest source")
        payload = canonical_config_json({
            "input_mapping": mapping,
            "scenario_run_id": manifest.run_id,
        }) + "\n"
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        manifests.append((profile.profile_id, manifest.run_id, payload, digest))
    prereg_id = config_hash({
        "domain": "sf261-stage6-preflight-inputs-v1",
        "execution_revision": BASELINE_SHA,
        "profile_run_ids": [[p, run] for p, run, _, _ in manifests],
        "manifest_bytes_sha256": [[p, digest] for p, _, _, digest in manifests],
    })
    return manifests, prereg_id


def write_packet(
    output: Path, source_summary: dict[str, object], inventory_summary: dict[str, object],
    manifests: list[tuple[str, str, str, str]], prereg_id: str, head: str,
) -> None:
    """Write three exclusively-created private non-performance artifacts."""
    from signalforge.config.identity import canonical_config_json

    names = {
        "REFERENCE_RAW": "reference_raw-input-manifest.json",
        "ADVERSE_RAW": "adverse_raw-input-manifest.json",
    }
    targets = [output / names[p] for p, _, _, _ in manifests]
    targets.append(output / "preflight-readiness.json")
    _require(len({str(p) for p in targets}) == 3, "profile manifest filenames collide")
    _require(all(not p.exists() and not p.is_symlink() for p in targets),
             "preflight output already exists; choose a fresh private directory")
    summary = {
        "schema": "stage6-gate-d-preflight-v1",
        "disposition": "PREPARATION_ONLY_GATE_D_WITHHELD",
        "source_verified_read_only": True,
        "scenario_performance_executed_by_preflight": False,
        "gate_d_approved": False,
        "gate_d_ready": False,
        "custody_and_oos_quarantine_independent_review": "PENDING",
        "resource_feasibility_independent_review": "PENDING",
        "sf098_live_disposition_recheck": "REQUIRED_BEFORE_GATE_D",
        "execution_valid": False,
        "baseline_execution_revision": BASELINE_SHA,
        "current_script_checkout": head,
        "python_version": sys.version.split()[0],
        "source": source_summary,
        "protected_inventory_before_and_after": inventory_summary,
        "declared_grid": {
            "warmup_5m": 288, "is_decisions_5m": 69984,
            "oos_decisions_5m": 34848, "total_measured_5m": 104832,
        },
        "profiles": [
            {"profile_id": p, "run_id": run, "manifest_file": names[p],
             "canonical_manifest_sha256": digest}
            for p, run, _, digest in manifests
        ],
        "input_preregistration_id": prereg_id,
        "remaining_gate_d_evidence": [
            "independent review of archive audit and manifest identities",
            "validated operator custodianship and restricted OOS release protocol",
            "separate resource-capacity evidence, storage and replay plan",
            "fresh SF-098 disposition and separate owner Gate D ACCEPT on parent #253",
        ],
    }
    for profile, _, payload, _ in manifests:
        _exclusive_json(output / names[profile], payload)
    # The self-contained report intentionally cannot claim independent approval.
    _exclusive_json(
        output / "preflight-readiness.json",
        json.dumps(summary, sort_keys=True, indent=2, ensure_ascii=False) + "\n",
    )


def execute(repo: Path, generation: Path, destination: Path) -> str:
    """Perform local source/manifest checks; never run historical scenario performance.

    Args:
        repo: Local SignalForge repository root.
        generation: Original protected SF-088 evidence-only generation.
        destination: Precreated private output directory outside Git.

    Returns:
        Frozen, input-only pre-registration digest.

    Raises:
        PreflightError: On failed source, identity, revision or custody checks.
    """
    repo = repo.resolve(strict=True)
    output = _output_dir(destination, repo)
    root = _protected_root(generation)
    head = verify_revision(repo)
    before = inventory(root)
    _equal(before["file_count"], EXPECTED_FILE_COUNT, "protected file inventory count")
    _equal(before["total_bytes"], EXPECTED_SOURCE_BYTES, "protected archive byte size")
    source, candles, summary = verify_source(root)
    manifests, prereg_id = freeze_manifests(source, candles)
    after = inventory(root)
    _equal(before, after, "protected source changed during preflight")
    write_packet(output, summary, before, manifests, prereg_id, head)
    return prereg_id


def main(argv: list[str] | None = None) -> int:
    """Parse the deliberately non-performance command-line interface."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--generation-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        identity = execute(args.repo_root, args.generation_dir, args.output_dir)
    except (
        PreflightError, OSError, KeyError, ValueError, TypeError, subprocess.TimeoutExpired
    ) as exc:
        parser.exit(2, "BLOCKED: " + str(exc) + "\n")
    print("PREPARATION_ONLY_GATE_D_WITHHELD")
    print("input_preregistration_id=" + identity)
    print("No historical scenario performance was executed by this tool.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
