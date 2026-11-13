"""Future-only independent source and strict-reference evidence producers.

These execute BEFORE report serialization and are never invoked by the saved-byte
report CLI. Scenario path assumptions do not create strict-reference observations.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

from signalforge.config.identity import canonical_config_json, config_hash
from signalforge.research.btc_raw_diagnostic_input import RawDiagnosticSource
from signalforge.research.scenario_execution import (
    ScenarioResearchRequest,
    ScenarioResearchResult,
)


def _write_new(path: Path, payload: dict[str, object]) -> None:
    """Write one new canonical companion, never replace prior evidence."""
    if path.suffix != ".json" or not path.parent.is_dir() or path.is_symlink():
        raise ValueError("Companion destination must be a new JSON file")
    parent = path.parent.resolve(strict=True)
    if any(part in (".signalforge-data", "sf088", "sf096") for part in parent.parts):
        raise ValueError("Companion may not be written in protected evidence trees")
    with path.open("x", encoding="utf-8") as stream:
        stream.write(canonical_config_json(payload))
        stream.write("\n")


def _require_matching_request(
    request: ScenarioResearchRequest, result: ScenarioResearchResult,
) -> None:
    """Prevent binding one run's source/strict assessment to another run ID.

    Exact source, profile, strategy, window and calculation inputs must agree
    with the immutable result manifest before any companion is persisted.
    """
    manifest = result.manifest.mapping()
    source = manifest.get("source")
    strategy = manifest.get("strategy")
    windows = manifest.get("session_and_window")
    implementation = manifest.get("implementation")
    assumptions = manifest.get("assumptions")
    if (
        not isinstance(source, dict) or not isinstance(strategy, dict)
        or not isinstance(windows, dict) or not isinstance(implementation, dict)
        or not isinstance(assumptions, dict)
    ):
        raise ValueError("Malformed scenario manifest for diagnostic pairing")
    dataset = request.source.dataset
    checks = (
        source.get("dataset_id") == str(dataset.dataset_id),
        source.get("content_hash") == dataset.content_hash,
        source.get("source_diagnostic_id") == request.source.source_diagnostic_id,
        config_hash({"manifest": source.get("manifest")})
            == config_hash({"manifest": dataset.manifest.semantic_mapping()}),
        windows.get("is_start") == request.is_start.isoformat(),
        windows.get("oos_start") == request.oos_start.isoformat(),
        windows.get("measured_end") == request.measured_end.isoformat(),
        manifest.get("fills") == request.profile.semantic_mapping(),
        manifest.get("resource_policy") == request.resources.mapping(),
        strategy.get("id") == request.strategy_selection.strategy_id,
        strategy.get("version") == request.strategy_selection.strategy_version,
        strategy.get("engine_calculation_version") == request.engine_calculation_version,
        strategy.get("synthetic_fixture_identity") == request.synthetic_fixture_identity,
        implementation.get("revision") == request.repository_revision,
        assumptions.get("semantic_hash") == request.assumptions.semantic_hash,
    )
    if not all(checks):
        raise ValueError("Request evidence does not match result manifest identity")


def write_source_quality_evidence(
    request: ScenarioResearchRequest, result: ScenarioResearchResult, path: Path,
) -> None:
    """Classify the explicit measured 1m source grid from supplied source bars.

    A rejected/corrupt raw observation with unknown interval cannot be silently
    attributed to a valid canonical bucket: declare NOT_ASSESSED instead.
    This producer is independent of the scenario outcome/trace simulation.
    """
    _require_matching_request(request, result)
    source: RawDiagnosticSource = request.source
    ds = source.dataset
    starts = [bar.interval.start for bar in ds.bars]
    observed = Counter(starts)
    windows: dict[str, object] = {}
    for name, low, high in (("IS", request.is_start, request.oos_start),
                             ("OOS", request.oos_start, request.measured_end)):
        expected = int((high - low) / timedelta(minutes=1))
        counts = {"VALID": 0, "MISSING": 0, "CORRUPT": 0,
                  "REPAIRED": 0, "SUBSTITUTED": 0}
        codes: list[str] = []
        for i in range(expected):
            instant = low + timedelta(minutes=i)
            if observed[instant] == 0:
                counts["MISSING"] += 1
                codes.append("M")
            elif observed[instant] == 1:
                counts["VALID"] += 1
                codes.append("V")
            else:
                counts["CORRUPT"] += 1
                codes.append("C")
        windows[name] = {
            "expected_intervals": expected,
            "primary_disposition_counts": counts,
            "primary_dispositions_1m": "".join(codes),
        }
    # Rejected unlocatable raw rows cannot establish every exact 1m class.
    uncertain = ds.manifest.corrupt_rejected_count > 0 or any(
        token in ds.manifest.limitations
        for token in ("REPAIRED", "SUBSTITUTED", "SOURCE_REPAIRED", "SOURCE_SUBSTITUTED")
    )
    payload: dict[str, object] = {
        "schema_version": "scenario-source-quality-v1",
        "scenario_run_id": result.manifest.run_id,
        "scenario_result_v1_id": result.result_id,
        "producer_id": "canonical-source-grid-classifier-v1",
        "unit": "CANONICAL_1M_SOURCE_BUCKET",
        "assessment": "NOT_ASSESSED" if uncertain else "ASSESSED",
        "windows": windows,
    }
    _write_new(path, payload)


def write_strict_reference_evidence(
    result: ScenarioResearchResult,
    request: ScenarioResearchRequest,
    path: Path,
    *,
    assessed_intervals: tuple[datetime, ...],
    ambiguous_intervals: tuple[datetime, ...],
    producer_id: str,
    coverage_proof: dict[str, object] | None = None,
) -> None:
    """Persist independently produced strict diagnostic interval classifications.

    The caller must obtain classifications from the strict-reference producer.
    No scenario trace is interpreted as historical intraminute order. Explicit
    producer identity is required; an empty assessment is NOT_ASSESSED.
    """
    _require_matching_request(request, result)
    if not producer_id or producer_id.startswith("scenario-path"):
        raise ValueError("Independent strict-reference producer identity required")
    eligible = set(assessed_intervals)
    ambiguous = set(ambiguous_intervals)
    if len(eligible) != len(assessed_intervals) or len(ambiguous) != len(ambiguous_intervals):
        raise ValueError("Duplicate strict diagnostic interval")
    if not ambiguous.issubset(eligible):
        raise ValueError("Ambiguity outside explicitly assessed strict intervals")
    # Validate before constructing counts and masks: an off-minute timestamp
    # increments eligible_intervals but cannot occupy any canonical 1m slot.
    for instant in eligible | ambiguous:
        if (not isinstance(instant, datetime)
                or instant.tzinfo is None
                or instant.utcoffset() != timedelta(0)
                or instant.second != 0 or instant.microsecond != 0
                or not request.is_start <= instant < request.measured_end):
            raise ValueError("Strict intervals must be UTC aligned measured 1m buckets")
    windows: dict[str, object] = {}
    for name, lower, upper in (("IS", request.is_start, request.oos_start),
                               ("OOS", request.oos_start, request.measured_end)):
        selected = {instant for instant in eligible if lower <= instant < upper}
        bad = sorted(instant for instant in ambiguous if lower <= instant < upper)
        expected = int((upper - lower) / timedelta(minutes=1))
        mask = "".join(
            "1" if lower + timedelta(minutes=i) in selected else "0"
            for i in range(expected)
        )
        windows[name] = {
            "eligible_intervals": len(selected),
            "assessed_1m_mask": mask,
            "ambiguous_interval_starts": [instant.isoformat() for instant in bad],
        }
    payload: dict[str, object] = {
        "schema_version": "scenario-strict-reference-v1",
        "scenario_run_id": result.manifest.run_id,
        "scenario_result_v1_id": result.result_id,
        "producer_id": producer_id,
        "unit": "CANONICAL_1M_SOURCE_BUCKET",
        "assessment": "ASSESSED" if eligible else "NOT_ASSESSED",
        "windows": windows,
    }
    # B3 is additive: existing v1 eligible_intervals/ASSESSED retain their
    # original meaning (supplied *assessed* keys). A separate independently
    # derived proof distinguishes eligible, ineligible and indeterminate keys.
    # Missing proof is deliberately ineligible for future gross-R reporting.
    if coverage_proof is not None:
        payload["strict_coverage_proof"] = coverage_proof
    _write_new(path, payload)
