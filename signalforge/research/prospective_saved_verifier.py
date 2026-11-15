"""SF-296 synthetic-only, non-economic persisted-evidence verification.

Never run a strategy, load historical bars, or calculate/report economic metrics.
A separate guarded-parent custody proof is required before the result may be
labelled verified: a hash-consistent file alone cannot authenticate its producer.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Literal

from signalforge.research.scenario_reportability import (
    FUTURE_FIELDS,
    ReportabilityError,
    _companion,
    _count,
    _decode_canonical,
    _identity,
    _items,
    _map,
    _reconcile_saved_actions,
    _require,
    _source_quality,
    _strict_reference,
    _utc,
)

EvidenceDisposition = Literal["COMPLETE", "WITHHELD"]


class EvidenceBlocked(ValueError):
    """Malformed, inconsistent or unauthenticated evidence; no partial result."""


def verify_v2_structure(
    result_bytes: bytes, source_bytes: bytes, strict_bytes: bytes,
) -> EvidenceDisposition:
    """Check saved canonical identity, source/strict and lifecycle without economics.

    This only proves T1 structural integrity; T2 is enforced separately by the
    controlled operator's committed-set receipt and verified guarded lineage.
    No supplied bytes are presumed to prove historical B3/source authenticity.
    """
    try:
        envelope = _decode_canonical(result_bytes)
        _require(
            set(envelope) == {"manifest", "result", "scenario_result_id"},
            "UNKNOWN_ENVELOPE",
        )
        manifest = _map(envelope.get("manifest"), "manifest")
        result = _map(envelope.get("result"), "result")
        _require(
            result.get("schema_version") == "scenario-result-v2"
            and result.get("report_contract") == "sf283-contained-gross-r-v1",
            "UNKNOWN_REPORT_CONTRACT",
        )
        _require(
            result.get("mode") == "SCENARIO_RESEARCH"
            and result.get("execution_valid") is False
            and result.get("certainty") == "SCENARIO_CONDITIONED",
            "WRONG_EVIDENCE_TIER",
        )
        strategy = _map(manifest.get("strategy"), "strategy")
        fixture = strategy.get("synthetic_fixture_identity")
        _require(
            type(fixture) is str and fixture.startswith("synthetic-"),
            "SYNTHETIC_IDENTITY_REQUIRED",
        )
        source_manifest = _map(manifest.get("source"), "source")
        source_id = source_manifest.get("source_diagnostic_id")
        _require(
            type(source_id) is str and source_id.startswith("synthetic-"),
            "SYNTHETIC_SOURCE_REQUIRED",
        )
        run_id = _identity({"domain": "scenario-run-v1", "inputs": manifest})
        _require(result.get("scenario_run_id") == run_id, "RUN_ID_MISMATCH")
        _require(
            envelope.get("scenario_result_id")
            == _identity({"domain": "scenario-result-v2", "result": result}),
            "RESULT_ID_MISMATCH",
        )
        future = _items(result.get("outcomes"), "outcomes")
        for outcome in future:
            _require(set(FUTURE_FIELDS).issubset(outcome), "INCOMPLETE_V2_LIFECYCLE")
        legacy = dict(result)
        legacy["schema_version"] = "scenario-result-v1"
        del legacy["report_contract"]
        binding = _map(legacy.pop("companion_sha256"), "companion_hashes")
        legacy["outcomes"] = [
            {key: value for key, value in outcome.items() if key not in FUTURE_FIELDS}
            for outcome in future
        ]
        legacy_id = _identity({"domain": "scenario-result-v1", "result": legacy})
        _require(
            set(binding) == {"source_quality", "strict_reference"},
            "MISSING_COMPANION",
        )
        source = _companion(
            source_bytes, binding["source_quality"], "source-quality", run_id, legacy_id,
        )
        strict = _companion(
            strict_bytes, binding["strict_reference"], "strict-reference", run_id, legacy_id,
        )
        _require(
            source.get("producer_id") == "canonical-source-grid-classifier-v1"
            and strict.get("producer_id") == "adr011-fail-closed-independent-strict-v1",
            "UNSUPPORTED_PRODUCER",
        )
        windows = _map(manifest.get("session_and_window"), "windows")
        start = _utc(windows["is_start"])
        split = _utc(windows["oos_start"])
        finish = _utc(windows["measured_end"])
        _require(
            start < split <= finish
            and (split - start) % timedelta(minutes=5) == timedelta(0)
            and (finish - split) % timedelta(minutes=5) == timedelta(0),
            "INVALID_WINDOWS",
        )
        bounds = {"IS": (start, split), "OOS": (split, finish)}
        expected = {
            key: int((high - low) / timedelta(minutes=5))
            for key, (low, high) in bounds.items()
        }
        _require(
            _count(result.get("is_observed")) == expected["IS"]
            and _count(result.get("oos_observed")) == expected["OOS"]
            and result.get("failure") is None
            and _count(result.get("unsupported")) == 0
            and result.get("replay_verified") is True
            and result.get("method_status") in (
                "SCENARIO_METHOD_VALID", "SCENARIO_METHOD_INCONCLUSIVE",
            ),
            "INCOMPLETE_RUN",
        )
        # Strict/source checks are shared with the saved report but return no
        # public data here. They may fail closed on authentic incomplete source.
        _source_quality(source, bounds)
        _strict_reference(strict, bounds, manifest)
        _require(
            _count(result.get("attempted_outcome_count")) == len(future),
            "OUTCOME_COUNT_MISMATCH",
        )
        seen: set[str] = set()
        for outcome in future:
            oid = outcome.get("opportunity_id")
            _require(
                type(oid) is str and oid not in seen
                and outcome.get("certainty") == "SCENARIO_CONDITIONED"
                and outcome.get("state") in (
                    "CLOSED", "OPEN", "ARMED", "EXPIRED", "REJECTED",
                ),
                "INVALID_OUTCOME",
            )
            seen.add(oid)
        fills = _map(manifest.get("fills"), "fills")
        _require(
            fills.get("profile_id") in ("REFERENCE_RAW", "ADVERSE_RAW")
            and fills.get("price_mode") == "raw_diagnostic",
            "INVALID_PROFILE",
        )
        _reconcile_saved_actions(result, future, start, finish, fills)
        return "COMPLETE"
    except ReportabilityError as exc:
        # Distinguish evidence that is authentic but insufficient. Never send
        # the internal error name or any partial evidence to the operator.
        if str(exc) in (
            "SOURCE_NOT_ASSESSED",
            "UNQUALIFIED_SOURCE",
            "STRICT_COVERAGE_INCOMPLETE_WITHHOLD",
        ):
            return "WITHHELD"
        raise EvidenceBlocked("INVALID_EVIDENCE") from None
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
        raise EvidenceBlocked("INVALID_EVIDENCE") from None
