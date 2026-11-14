"""Read-only, IS-first, non-economic verification of frozen SF-260 v1 evidence.

No protected-result read is authorised by the existence of this adapter.
A separate 00.01 owner inspection record is mandatory for protected mode.
The combined v1 result is parsed in a bounded, non-logging process only AFTER
all four sealed files pass byte/receipt authentication. OOS economics are never
returned, written or displayed. No strict ADR-011 proof is inferred from v1.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import stage6_result_custody as canonical  # noqa: E402
from scripts.stage6_90d_independent_verifier import read_canonical  # noqa: E402

REVISION = "76a7abbb8f0fb1697a2af62725a604711dbb413d"
VARIANT = "SF260_90D_AUDITED_V1"
PREREG = "0facaab1cbd57b76d3d7f7669c9156eb82101f018e16e058e9b4da41a9a0134e"
DERIVATION = "a85237fbcdbb562077555c85036edf8c5f29c22b3e63136ef8200948209abea5"
CHILD = "a23b78a7bee658ea57cb399bcaff7714f628386e6ccc38b564d515c46f942f9f"
SOURCE_START = datetime(2025, 10, 30, tzinfo=UTC)
IS_START = datetime(2025, 10, 31, tzinfo=UTC)
OOS_START = datetime(2025, 12, 30, tzinfo=UTC)
MEASURED_END = datetime(2026, 1, 29, tzinfo=UTC)
MAX_CANONICAL_BYTES = 12 * 1024 * 1024
PROFILES = ("REFERENCE_RAW", "ADVERSE_RAW")
FROZEN = {
    "REFERENCE_RAW": (
        "895b36b4dd22206ffd21a94084da5a7fac50790a6f8a9c51e99b5053458cfca1",
        "0b53818f7c66dcce62217958dd16082c18eea980b644b617b1e7ea03188ffabf",
        8_481_157,
        "163ab564e9fc2b97296e80b38c59a0165d04acccafdece9846dcb7e6c9601c8f",
    ),
    "ADVERSE_RAW": (
        "ce02137d0ea8c91867f608bcb495ec59973e2b279fd51a7e2e040b94c24c7bd9",
        "9360d65d76d72edeb0c7ca373bfff8459573947068c6823a71053047b40a4b44",
        10_399_344,
        "e77605545135d65ae2a46bba55fab50c0aa919cdb1481236eca275690cbec421",
    ),
}
OWNER_URL = re.compile(
    r"https://github\\.com/harishkamathuk/signalforge/issues/253#issuecomment-[1-9][0-9]*\\Z"
)


class ValidationBlocked(ValueError):
    """Untrusted bytes or unsupported evidence; details never reach stdout."""


def require(ok: bool) -> None:
    if not ok:
        raise ValidationBlocked("validation blocked")


def private(path: Path, mode: int) -> Path:
    """Reject links throughout the resolved path, unexpected types and permissions."""
    raw = path.absolute()
    real = raw.resolve(strict=True)
    require(real == raw and stat.S_IMODE(real.stat().st_mode) == mode)
    require(real.is_dir() if mode == 0o700 else real.is_file())
    require(not real.is_relative_to(ROOT))
    require(not any((p / ".git").exists() for p in (real, *real.parents)))
    return real


def read_private_json(path: Path) -> dict[str, Any]:
    data = private(path, 0o600).read_bytes()
    require(len(data) <= 16_384)
    value = json.loads(data)
    require(type(value) is dict)
    return value


def fingerprint(path: Path) -> tuple[int, str]:
    """Stream without deserialising economic payload or generating a readout."""
    p = private(path, 0o600)
    size = p.stat().st_size
    require(0 < size <= MAX_CANONICAL_BYTES)
    sha = hashlib.sha256()
    with p.open("rb") as handle:
        while block := handle.read(64 * 1024):
            sha.update(block)
    require(p.stat().st_size == size)
    return size, sha.hexdigest()


def synthetic_source(manifest: dict[str, Any]) -> bool:
    source = manifest.get("source")
    strategy = manifest.get("strategy")
    return (
        type(source) is dict and type(strategy) is dict
        and type(source.get("source_diagnostic_id")) is str
        and source["source_diagnostic_id"].startswith("synthetic-")
        and type(strategy.get("synthetic_fixture_identity")) is str
        and strategy["synthetic_fixture_identity"].startswith("synthetic-")
        and source.get("content_hash") != CHILD
    )


def protected_registration(prereg: Path) -> dict[str, dict[str, Any]]:
    private(prereg, 0o700)
    ready, ready_sha = read_canonical(private(prereg / "source-only-readiness.json", 0o600))
    independent, _ = read_canonical(private(prereg / "independent-verification.json", 0o600))
    require(
        ready.get("revision") == REVISION
        and ready.get("derivation_id") == DERIVATION
        and ready.get("input_preregistration_id") == PREREG
        and ready.get("execution_valid") is False
        and ready.get("protected_scenario_executed") is False
        and independent.get("status") == "SOURCE_ONLY_INDEPENDENTLY_VERIFIED_NO_GATE_D"
        and independent.get("receipt_sha256") == ready_sha
        and independent.get("preregistration_id") == PREREG
        and independent.get("revision") == REVISION
    )
    profiles = ready.get("profiles")
    require(type(profiles) is list and len(profiles) == 2)
    output: dict[str, dict[str, Any]] = {}
    for index, profile in enumerate(PROFILES):
        row = profiles[index]
        require(
            type(row) is dict and row.get("profile") == profile
            and row.get("run_id") == FROZEN[profile][0]
            and row.get("canonical_sha256") == FROZEN[profile][1]
            and row.get("filename") == profile.lower() + "-manifest.json"
        )
        path = private(prereg / str(row["filename"]), 0o600)
        size, sha = fingerprint(path)
        require(size > 0 and sha == FROZEN[profile][1])
        record, _ = read_canonical(path)
        require(
            record.get("scenario_run_id") == FROZEN[profile][0]
            and set(record) == {"input_mapping", "scenario_run_id"}
            and type(record.get("input_mapping")) is dict
        )
        output[profile] = record["input_mapping"]
    return output


def protected_permission(path: Path) -> None:
    """Explicit separate owner approval; a Gate D execution record is insufficient."""
    row = read_private_json(path)
    require(
        row.get("decision") == "SF260_V1_IS_QA_PROTECTED_READ_ACCEPT"
        and row.get("parent_issue") == 253
        and row.get("variant") == VARIANT
        and row.get("execution_revision") == REVISION
        and row.get("input_preregistration_id") == PREREG
        and row.get("source_derivation_id") == DERIVATION
        and type(row.get("approval_url")) is str
        and OWNER_URL.fullmatch(row["approval_url"]) is not None
        and row["approval_url"] !=
        "https://github.com/harishkamathuk/signalforge/issues/253#issuecomment-6883237655"
    )
    # Local approval is operator attestation. Human must independently
    # verify linked owner wording; never claim the CLI authenticates GitHub.


def check_manifest(manifest: dict[str, Any], profile: str, synthetic: bool) -> None:
    require(type(manifest) is dict)
    mode = manifest.get("mode_and_schema")
    source = manifest.get("source")
    implementation = manifest.get("implementation")
    fills = manifest.get("fills")
    window = manifest.get("session_and_window")
    require(all(type(x) is dict for x in (mode, source, implementation, fills, window)))
    require(
        mode.get("mode") == "SCENARIO_RESEARCH"
        and mode.get("schema") == "scenario-manifest-v1"
        and mode.get("simulator") == "btc-ohlc-path-scenario-v1"
        and mode.get("study_variant") == VARIANT
        and mode.get("sample_status") == "REPEATED_SAMPLE"
        and fills.get("profile_id") == profile
        and window.get("is_start") == IS_START.isoformat()
        and window.get("oos_start") == OOS_START.isoformat()
        and window.get("measured_end") == MEASURED_END.isoformat()
        and window.get("pre_roll_start") == SOURCE_START.isoformat()
    )
    if synthetic:
        require(synthetic_source(manifest))
    else:
        require(
            implementation.get("revision") == REVISION
            and source.get("source_diagnostic_id") == DERIVATION
            and source.get("dataset_id") == CHILD
            and source.get("content_hash") == CHILD
            and source.get("audited_slice_lineage", {}).get("child_dataset_hash") == CHILD
            and not synthetic_source(manifest)
        )


def minute(value: object, *, end: bool = False) -> datetime:
    require(type(value) is str)
    date = datetime.fromisoformat(value)
    require(date.tzinfo == UTC and date.second == 0 and date.microsecond == 0)
    require(IS_START <= date <= MEASURED_END if end else IS_START <= date < MEASURED_END)
    require(value == date.isoformat())
    return date


def lifecycle(result: dict[str, Any]) -> bool:
    """Check supported chronology and saved action counts, never economic values."""
    outcomes, traces, blocked = (
        result.get("outcomes"), result.get("trace"), result.get("blocked_decisions")
    )
    require(type(outcomes) is list and type(traces) is list and type(blocked) is list)
    require(
        len(outcomes) == result.get("attempted_outcome_count")
        and len(traces) == result.get("attempted_trace_count")
        and len(blocked) == result.get("blocked_actionable_count")
        and len(outcomes) <= 104_833
        and len(traces) + len(blocked) <= 2_096_640
    )
    seen: set[str] = set()
    prior_exit: datetime | None = None
    terminal: str | None = None
    entries: list[datetime] = []
    exits: list[datetime] = []
    for index, row in enumerate(outcomes):
        require(type(row) is dict)
        identity, state, reason = row.get("opportunity_id"), row.get("state"), row.get("reason")
        require(type(identity) is str and len(identity) == 64
                and all(c in "0123456789abcdef" for c in identity)
                and identity not in seen)
        seen.add(identity)
        require(state in ("CLOSED", "OPEN", "ARMED", "REJECTED", "EXPIRED"))
        if state in ("OPEN", "ARMED"):
            require(index == len(outcomes) - 1 and reason == "DATASET_END_CONDITIONAL")
            terminal = state
        elif state == "REJECTED":
            require(reason == "NON_POSITIVE_OR_UNSUPPORTED_RISK")
        elif state == "EXPIRED":
            require(reason in ("PRE_ENTRY_INVALIDATION", "VALIDITY_WINDOW_END"))
        else:
            require(reason in ("STOP", "TARGET"))
        if state in ("CLOSED", "OPEN"):
            entry = minute(row.get("entry_bucket"))
            require(prior_exit is None or entry > prior_exit)
            entries.append(entry)
            if state == "CLOSED":
                leave = minute(row.get("exit_bucket"))
                require(leave >= entry)
                exits.append(leave)
                prior_exit = leave
            else:
                require(row.get("exit_bucket") is None)
        else:
            require(row.get("entry_bucket") is None and row.get("exit_bucket") is None)
    require(result.get("terminal_active_state") == terminal)
    prior: datetime | None = None
    entry_action: list[datetime] = []
    exit_action: list[datetime] = []
    action_counts = {"ENTRY": 0, "INVALIDATION": 0, "STOP": 0, "TARGET": 0}
    for row in traces:
        require(type(row) is dict)
        bucket = minute(row.get("bucket_start"))
        require(prior is None or prior <= bucket)
        prior = bucket
        action = row.get("action")
        require(action in ("ASSUMED_SEGMENT", *action_counts))
        if action != "ASSUMED_SEGMENT":
            action_counts[action] += 1
        if action == "ENTRY":
            entry_action.append(bucket)
        elif action in ("STOP", "TARGET"):
            exit_action.append(bucket)
    require(entry_action == entries and exit_action == exits)
    require(sum(action_counts.values()) == result.get("event_count"))
    require(action_counts["INVALIDATION"] ==
            sum(x.get("reason") == "PRE_ENTRY_INVALIDATION" for x in outcomes))
    prev: datetime | None = None
    for row in blocked:
        require(type(row) is dict)
        start = minute(row.get("interval_start"))
        end = minute(row.get("interval_end"), end=True)
        require(end - start == timedelta(minutes=5)
                and start.minute % 5 == 0 and (prev is None or end > prev))
        prev = end
        require(row.get("blocking_opportunity_id") in seen
                and row.get("blocking_state") in ("ARMED", "OPEN"))
    return True


def method_checks(result: dict[str, Any]) -> dict[str, str]:
    """Runner-reported observations and independent saved-field consistency differ."""
    counts = (
        type(result.get("is_observed")) is int
        and result["is_observed"] == 17_280
        and type(result.get("oos_observed")) is int
        and result["oos_observed"] == 8_640
    )
    unsupported = type(result.get("unsupported")) is int and result["unsupported"] == 0
    failure = all(result.get(k) is None for k in (
        "failure", "failure_bucket", "failure_opportunity_id",
        "failure_signal_interval_start", "last_complete_bucket",
    ))
    replay = result.get("replay_verified") is True
    valid = result.get("method_status") == "SCENARIO_METHOD_VALID"
    require(result.get("execution_valid") is False and
            result.get("certainty") == "SCENARIO_CONDITIONED")
    require(result.get("method_status") in (
        "SCENARIO_METHOD_VALID", "SCENARIO_METHOD_INCONCLUSIVE",
        "SCENARIO_METHOD_INVALID",
    ))
    if valid:
        require(counts and unsupported and failure and replay)
    if failure:
        lifecycle(result)
    else:
        require(all(not result.get(k) for k in ("outcomes", "trace", "blocked_decisions")))
    return {
        "FROZEN_GRID_RUNNER_REPORTED": "PASS" if counts else "INCONCLUSIVE",
        "ZERO_UNSUPPORTED_RUNNER_REPORTED": "PASS" if unsupported else "INCONCLUSIVE",
        "REPLAY_RUNNER_REPORTED": "PASS" if replay else "INCONCLUSIVE",
        "NO_FAILURE_RUNNER_REPORTED": "PASS" if failure else "INCONCLUSIVE",
        "METHOD_STATUS_RUNNER_REPORTED": "PASS" if valid else "INCONCLUSIVE",
        "SAVED_LIFECYCLE_INDEPENDENT_CONSISTENCY": "PASS" if failure else "INCONCLUSIVE",
    }


def validate(
    root: Path, prereg: Path | None = None, *,
    synthetic: bool = False, inspection_record: Path | None = None,
) -> dict[str, object]:
    """Read only after access authority and all four original hashes match."""
    if not synthetic:
        require(inspection_record is not None and prereg is not None)
        protected_permission(inspection_record)
    root = private(root, 0o700)
    require(not (root / ".sf260-90d-active.json").exists())
    if synthetic:
        require(inspection_record is None and prereg is None)
        mappings: dict[str, dict[str, Any]] = {}
    else:
        assert prereg is not None
        mappings = protected_registration(prereg)
    verified: list[tuple[str, int, Path, dict[str, Any]]] = []
    for profile in PROFILES:
        for attempt in (1, 2):
            folder = private(root / f"{profile.lower()}-attempt-{attempt}", 0o700)
            require(not (folder / "partial.json").exists()
                    and not (folder / "failure.json").exists())
            path = private(folder / "canonical-result.json", 0o600)
            size, sha = fingerprint(path)
            if not synthetic:
                require((size, sha) == (FROZEN[profile][2], FROZEN[profile][3]))
            receipt = read_private_json(folder / "worker-receipt.json")
            require(
                receipt == {
                    "status": "CANONICAL_WRITE_COMPLETED_METHOD_UNASSESSED",
                    "variant": VARIANT, "profile": profile, "attempt": attempt,
                    "scenario_run_id": (
                        FROZEN[profile][0] if not synthetic else receipt.get("scenario_run_id")
                    ),
                    "canonical_sha256": sha, "canonical_bytes": size,
                    "execution_valid": False, "oos_released": False,
                }
            )
            verified.append((profile, attempt, path, receipt))
    checks: dict[str, str] = {}
    hashes: dict[str, list[str]] = {profile: [] for profile in PROFILES}
    for profile, attempt, path, receipt in verified:
        _, manifest, result = canonical._parse_result(path)
        check_manifest(manifest, profile, synthetic)
        run = result.get("scenario_run_id")
        require(run == receipt["scenario_run_id"])
        if synthetic:
            require(run != FROZEN[profile][0] and synthetic_source(manifest))
        else:
            require(run == FROZEN[profile][0] and manifest == mappings[profile])
        case = method_checks(result)
        require(all(key in case for key in (
            "FROZEN_GRID_RUNNER_REPORTED", "SAVED_LIFECYCLE_INDEPENDENT_CONSISTENCY",
        )))
        for key, value in case.items():
            if key not in checks:
                checks[key] = value
            elif value != "PASS":
                checks[key] = "INCONCLUSIVE"
        hashes[profile].append(receipt["canonical_sha256"])
    require(all(len(hashes[p]) == 2 and hashes[p][0] == hashes[p][1] for p in PROFILES))
    return {
        "schema": "sf260-90d-v1-is-first-non-economic-qa-v1",
        "status": "NON_ECONOMIC_EVIDENCE_CHECKS_COMPLETED",
        "artifact_integrity": "PASS",
        "within_profile_byte_repeatability": "PASS",
        "checks": checks,
        "evidence_tier": {
            "artifact_integrity": "INDEPENDENT_RECOMPUTATION_OF_SAVED_BYTES",
            "grid_replay_method": "AUTHENTICATED_PERSISTED_RUNNER_SELF_REPORT",
            "lifecycle": "INDEPENDENT_SAVED_FIELD_CONSISTENCY_ONLY",
            "source_minutes": "NOT_RECONSTRUCTED",
        },
        "B3_INDEPENDENT_STRICT_COVERAGE": "NOT_ESTABLISHED",
        "economics": "WITHHELD",
        "oos": "SEALED",
        "gate_e": "NOT_APPROVED",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results-root", type=Path, required=True)
    parser.add_argument("--source-prereg", type=Path)
    parser.add_argument("--protected-inspection-record", type=Path)
    parser.add_argument("--synthetic-test-only", action="store_true")
    args = parser.parse_args(argv)
    try:
        answer = validate(
            args.results_root, args.source_prereg,
            synthetic=args.synthetic_test_only,
            inspection_record=args.protected_inspection_record,
        )
    except (Exception, SystemExit):
        # Never display untrusted values, paths, exception text or traceback.
        print('{"status":"VALIDATION_BLOCKED","economics":"WITHHELD","oos":"SEALED"}')
        return 2
    print(json.dumps(answer, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
