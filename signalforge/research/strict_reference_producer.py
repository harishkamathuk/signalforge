"""SF-260 B3 independent, prospective ADR-011 strict-minute coverage producer.

The observed-minute classifications come exclusively from the strict
FAIL_CLOSED_V1 historical runner, never the scenario OHLC assumed path.
This producer is code-only until separately authorised protected execution.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from signalforge.research.historical_execution import (
    CONTINUOUS_HISTORICAL_SESSION_POLICY,
    HISTORICAL_EXECUTION_CALCULATION_VERSION,
    HistoricalBarExecutionRunner,
    HistoricalContinuationPolicy,
    HistoricalOutcomeCertainty,
    HistoricalStrictMinuteAudit,
)
from signalforge.research.scenario_execution import (
    ScenarioResearchRequest,
    ScenarioResearchResult,
)
from signalforge.research.scenario_report_evidence import (
    _require_matching_request,
    write_strict_reference_evidence,
)

PROOF_VERSION = "adr011-strict-eligible-1m-v1"


def produce_strict_reference_evidence(
    request: ScenarioResearchRequest,
    scenario_result: ScenarioResearchResult,
    path: Path,
    *,
    runner: HistoricalBarExecutionRunner | None = None,
) -> None:
    """Write one source-bound strict evidence companion using ADR-011 only.

    This is intentionally separate from the scenario runner. A stopped strict
    assessment keeps the observed causal prefix; future minutes are
    eligibility-INDETERMINATE rather than invented eligible or flat.
    """
    _require_matching_request(request, scenario_result)
    dataset = request.source.dataset
    intervals: list[HistoricalStrictMinuteAudit] = []
    engine = runner if runner is not None else HistoricalBarExecutionRunner()
    strict = engine.run(
        dataset,
        strategy_selection=request.strategy_selection,
        engine_calculation_version=request.engine_calculation_version,
        tick_schedule=None,
        execution_profile=request.profile,
        market_session_policy=CONTINUOUS_HISTORICAL_SESSION_POLICY,
        raw_source=request.source,
        measurement_start=request.is_start,
        continuation_policy=HistoricalContinuationPolicy.FAIL_CLOSED_V1,
        strict_minute_observer=intervals.append,
    )
    manifest = scenario_result.manifest.mapping()
    source = manifest["source"]
    strategy = manifest["strategy"]
    assert isinstance(source, dict) and isinstance(strategy, dict)
    if (
        strict.execution_valid
        or strict.dataset_id != source["dataset_id"]
        or strict.source_diagnostic_id != source["source_diagnostic_id"]
        or strict.strategy_id != strategy["id"]
        or strict.strategy_version != strategy["version"]
        or strict.config_hash != strategy["config_hash"]
        or strict.engine_calculation_version != request.engine_calculation_version
        or strict.execution_profile_semantic_id != request.profile.semantic_id
        or strict.simulator_calculation_version != HISTORICAL_EXECUTION_CALCULATION_VERSION
    ):
        raise ValueError("Strict runner result provenance does not match scenario request")

    grid = dataset.manifest.effective_grid
    first = grid.coverage[0].start
    source_total = grid.expected_minute_count
    if len(grid.coverage) != 1 or len(intervals) > source_total:
        raise ValueError("Strict minute audit does not cover one ordered source grid")
    for position, item in enumerate(intervals):
        at = first + timedelta(minutes=position)
        if (
            item.bucket_start != at
            or item.bucket_start.second != 0
            or item.bucket_start.microsecond != 0
            or item.ambiguous and (not item.assessed or not item.eligible)
            or item.assessed and not item.eligible
            or item.eligible and item.reason == "KNOWN_INELIGIBLE"
        ):
            raise ValueError("Contradictory strict audit state or minute order")
    if not strict.terminated_early and len(intervals) != source_total:
        raise ValueError("Strict audit unexpectedly lacks completed source minutes")
    if strict.terminated_early and len(intervals) >= source_total:
        raise ValueError("Early terminated strict audit has no missing suffix")

    known: dict[object, HistoricalStrictMinuteAudit] = {
        item.bucket_start: item for item in intervals
    }
    windows: dict[str, object] = {}
    assessed: list[object] = []
    ambiguous: list[object] = []
    for name, low, high in (
        ("IS", request.is_start, request.oos_start),
        ("OOS", request.oos_start, request.measured_end),
    ):
        length = int((high - low) / timedelta(minutes=1))
        mask: list[str] = []
        assessed_mask: list[str] = []
        reasons: set[str] = set()
        for i in range(length):
            key = low + timedelta(minutes=i)
            observation = known.get(key)
            if observation is None:
                mask.append("?")
                assessed_mask.append("0")
                continue
            if not observation.eligible:
                mask.append("I")
                assessed_mask.append("0")
                continue
            mask.append("E")
            assessed_mask.append("1" if observation.assessed else "0")
            if observation.assessed:
                assessed.append(key)
                if observation.ambiguous:
                    ambiguous.append(key)
            else:
                reasons.add(observation.reason)
        classification = "".join(mask)
        assessment = "".join(assessed_mask)
        eligible = classification.count("E")
        ineligible = classification.count("I")
        indeterminate = classification.count("?")
        assessed_count = assessment.count("1")
        unassessed = eligible - assessed_count
        if indeterminate:
            reasons.add("STRICT_EARLY_TERMINATION")
        status = (
            "ELIGIBILITY_INDETERMINATE" if indeterminate else
            "ELIGIBLE_UNASSESSED" if unassessed else
            "ASSESSED_ZERO_ELIGIBLE" if eligible == 0 else "COMPLETE"
        )
        windows[name] = {
            "window_1m_expected": length,
            "eligibility_1m_mask": classification,
            "assessed_1m_mask": assessment,
            "known_eligible": eligible,
            "known_ineligible": ineligible,
            "eligibility_indeterminate": indeterminate,
            "expected_eligible": None if indeterminate else eligible,
            "assessed": assessed_count,
            "ambiguous": len([t for t in ambiguous if low <= t < high]),
            "unassessed": unassessed,
            "status": status,
            "incomplete_reasons": sorted(reasons),
        }
    stop = None
    if strict.terminated_early:
        last = strict.outcomes[-1]
        stop = {
            "after_bucket": intervals[-1].bucket_start.isoformat() if intervals else None,
            "certainty": last.certainty.value,
            "reasons": sorted(r.value for r in last.ambiguity_reasons),
        }
    binding = {
        key: manifest[key] for key in (
            "source", "strategy", "fills", "session_and_window", "implementation",
        )
    }
    proof: dict[str, object] = {
        "version": PROOF_VERSION,
        "producer_id": "adr011-fail-closed-independent-strict-v1",
        "continuation_policy": "FAIL_CLOSED_V1",
        "strict_result_id": strict.result_id,
        "strict_calculation_version": strict.simulator_calculation_version,
        "strict_terminated_early": strict.terminated_early,
        "stop": stop,
        "binding": binding,
        "windows": windows,
    }
    write_strict_reference_evidence(
        scenario_result,
        request,
        path,
        assessed_intervals=tuple(assessed),
        ambiguous_intervals=tuple(ambiguous),
        producer_id="adr011-fail-closed-independent-strict-v1",
        coverage_proof=proof,
    )
