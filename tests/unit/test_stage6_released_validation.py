"""Fabricated full-window counters and histories only; never historical input."""

from __future__ import annotations

import importlib.util
import json
import sys
from decimal import Decimal
from pathlib import Path

import pytest

from signalforge.research.stage6_validation import validate_result

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location(
    "stage6_validate_released", SCRIPTS / "stage6_validate_released.py"
)
assert SPEC and SPEC.loader
cli = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cli)
custody = cli.custody


def result_fixture() -> dict[str, object]:
    """Synthetic position crossing IS/OOS, then dataset-end OPEN, never real prices."""
    result = dict.fromkeys(custody.FROZEN_RESULTS)
    result.update(
        {
            "mode": "SCENARIO_RESEARCH",
            "schema_version": "scenario-result-v1",
            "execution_valid": False,
            "certainty": "SCENARIO_CONDITIONED",
            "replay_verified": True,
            "is_observed": 69984,
            "oos_observed": 34848,
            "unsupported": 0,
            "event_count": 3,
            "attempted_outcome_count": 2,
            "attempted_trace_count": 3,
            "blocked_actionable_count": 1,
            "method_status": "SCENARIO_METHOD_VALID",
            "terminal_active_state": "OPEN",
        }
    )

    def outcome(identity: str, state: str, entry: str, exit_at: str | None) -> dict[str, object]:
        return {
            "opportunity_id": identity * 64,
            "certainty": "SCENARIO_CONDITIONED",
            "state": state,
            "reason": "TARGET" if exit_at else "DATASET_END_CONDITIONAL",
            "entry_bucket": entry,
            "exit_bucket": exit_at,
            "entry_price": Decimal("100"),
            "exit_price": Decimal("115") if exit_at else None,
            "r": Decimal("1.5") if exit_at else None,
            "holding_span_1m_buckets": 3 if exit_at else None,
        }

    result["outcomes"] = [
        outcome("a", "CLOSED", "2026-06-30T23:59:00+00:00", "2026-07-01T00:01:00+00:00"),
        outcome("b", "OPEN", "2026-10-29T23:59:00+00:00", None),
    ]
    result["trace"] = [
        {
            "bucket_start": stamp,
            "from_level": Decimal("100"),
            "to_level": Decimal("100"),
            "modeled_base": Decimal("100"),
            "action": action,
            "ordering": "OBSERVED_OPEN",
        }
        for stamp, action in [
            ("2026-06-30T23:59:00+00:00", "ENTRY"),
            ("2026-07-01T00:01:00+00:00", "TARGET"),
            ("2026-10-29T23:59:00+00:00", "ENTRY"),
        ]
    ]
    result["blocked_decisions"] = [
        {
            "interval_start": "2026-06-30T23:55:00+00:00",
            "interval_end": "2026-07-01T00:00:00+00:00",
            "blocking_opportunity_id": "a" * 64,
            "blocking_state": "OPEN",
        }
    ]
    return result


def private(path: Path, raw: bytes) -> Path:
    path.write_bytes(raw)
    path.chmod(0o600)
    return path


def released_fixture(tmp_path: Path, *, mutate=None) -> tuple[Path, list[Path]]:
    root = tmp_path / "custody"
    root.mkdir(mode=0o700)
    records = []
    for profile in custody.RUNS:
        for attempt in (1, 2):
            result = result_fixture()
            if mutate:
                mutate(result, profile, attempt)
            manifest = {
                "source": {"source_diagnostic_id": "synthetic-sf278", "content_hash": "synthetic"},
                "strategy": {"synthetic_fixture_identity": "synthetic-sf278"},
                "fills": {"profile_id": profile},
                "implementation": {"revision": "synthetic"},
            }
            result["scenario_run_id"] = custody._hash_config(
                {"domain": "scenario-run-v1", "inputs": manifest}
            )
            raw = custody._canonical(
                {
                    "manifest": manifest,
                    "result": result,
                    "scenario_result_id": custody._hash_config(
                        {"domain": "scenario-result-v1", "result": result}
                    ),
                }
            )
            source = private(tmp_path / f"synthetic-{profile}-{attempt}.json", raw)
            receipt = custody.seal(
                root=root, source_file=source, profile=profile, attempt=attempt, synthetic=True
            )
            qa = custody.is_qa(root=root, profile=profile, attempt=attempt)
            record = private(
                tmp_path / f"approval-{profile}-{attempt}.json",
                json.dumps(
                    {
                        "parent_issue": 253,
                        "decision": "SYNTHETIC_OOS_RELEASE_TEST",
                        "record_url": "https://github.com/harishkamathuk/signalforge/issues/253#issuecomment-123",
                        "seal_sha256": receipt["result_sha256"],
                        "is_qa_sha256": qa["is_qa_sha256"],
                    }
                ).encode(),
            )
            custody.release_oos(root=root, profile=profile, attempt=attempt, oos_record=record)
            records.append(record)
    return root, records


def test_full_counters_are_not_independent_coverage_proof() -> None:
    report = validate_result(result_fixture())
    assert report["runner_validity"] == "RUNNER_REPORTED_VALID"
    assert report["status"] == "INCONCLUSIVE"
    assert report["checks"]["SAVED_LIFECYCLE_CONSISTENCY"] == "PASS"
    assert report["checks"]["FULL_WINDOW_COUNTERS"] == "PASS"
    assert not report["point_metrics_allowed"]


@pytest.mark.parametrize(
    ("key", "value", "rule", "verdict"),
    [
        ("oos_observed", 34847, "FULL_WINDOW_COUNTERS", "INCONCLUSIVE"),
        ("unsupported", 1, "ZERO_UNSUPPORTED", "INCONCLUSIVE"),
        ("replay_verified", False, "REPLAY_REPORTED", "INVALID"),
        ("replay_verified", 1, "REPLAY_REPORTED", "INVALID"),
        ("is_observed", True, "FULL_WINDOW_COUNTERS", "INCONCLUSIVE"),
        ("terminal_active_state", None, "SAVED_LIFECYCLE_CONSISTENCY", "INVALID"),
        ("event_count", 4, "SAVED_LIFECYCLE_CONSISTENCY", "INVALID"),
        ("attempted_trace_count", 4, "SAVED_LIFECYCLE_CONSISTENCY", "INVALID"),
        ("blocked_actionable_count", 2, "SAVED_LIFECYCLE_CONSISTENCY", "INVALID"),
        ("outcomes", None, "SAVED_LIFECYCLE_CONSISTENCY", "INVALID"),
    ],
)
def test_methodology_negative_cases(key, value, rule, verdict) -> None:
    result = result_fixture()
    result[key] = value
    assert validate_result(result)["checks"][rule] == verdict


@pytest.mark.parametrize(
    "mutation",
    [
        lambda r: r["outcomes"][0].update(holding_span_1m_buckets=2),
        lambda r: r["outcomes"][1].update(r=Decimal("0")),
        lambda r: r["outcomes"][1].update(reason="FORCED_MIDNIGHT_EXIT"),
        lambda r: r["outcomes"][1].update(entry_bucket="2026-07-01T00:00:00+00:00"),
        lambda r: r["outcomes"][1].update(opportunity_id="a" * 64),
        lambda r: r["trace"][0].update(action="TARGET"),
        lambda r: r["trace"][0].update(bucket_start="2026-06-30T23:59:00"),
        lambda r: r["trace"][0].update(bucket_start="2026-06-30T23:59:01+00:00"),
        lambda r: r["trace"][0].update(from_level=Decimal("NaN")),
        lambda r: r["blocked_decisions"][0].update(blocking_opportunity_id="c" * 64),
        lambda r: r["blocked_decisions"][0].update(interval_end="2026-07-01T00:05:00+00:00"),
    ],
)
def test_lifecycle_contradictions(mutation) -> None:
    result = result_fixture()
    mutation(result)
    assert validate_result(result)["checks"]["SAVED_LIFECYCLE_CONSISTENCY"] == "INVALID"


def test_terminal_armed_and_flat_are_permitted() -> None:
    result = result_fixture()
    result["outcomes"][1].update(state="ARMED", entry_bucket=None, entry_price=None)
    result["trace"].pop()
    result.update(terminal_active_state="ARMED", event_count=2, attempted_trace_count=2)
    assert validate_result(result)["checks"]["SAVED_LIFECYCLE_CONSISTENCY"] == "PASS"
    result["outcomes"].pop()
    result.update(terminal_active_state=None, attempted_outcome_count=1)
    assert validate_result(result)["checks"]["SAVED_LIFECYCLE_CONSISTENCY"] == "PASS"


def test_budget_failure_withheld_history_is_inconclusive() -> None:
    result = result_fixture()
    result.update(
        failure="BUDGET_EXHAUSTED: synthetic", outcomes=[], trace=[], blocked_decisions=[]
    )
    report = validate_result(result)
    assert report["status"] == "INCONCLUSIVE"
    assert not report["point_metrics_allowed"]


def test_four_attempt_workflow_is_read_only_deterministic_and_sanitized(tmp_path: Path) -> None:
    root, records = released_fixture(tmp_path)
    before = {p: p.read_bytes() for p in root.rglob("*.json")}
    report = cli.validate_released(root=root, oos_records=records, synthetic=True)
    assert report == cli.validate_released(root=root, oos_records=records, synthetic=True)
    assert report["status"] == "INCONCLUSIVE"
    assert report["within_profile_byte_repeatability"] == dict.fromkeys(custody.RUNS, "PASS")
    assert report["distinct_profile_results"]
    assert len(report["attempts"]) == 4
    text = json.dumps(report)
    # Fingerprints can legitimately contain the digits of a synthetic price;
    # check exact values and field names, not substrings inside approved hashes.
    for secret in (
        "entry_price",
        "exit_price",
        '"115"',
        "holding_span",
        "2026-06-30",
        str(root),
        '"r"',
        '"trace"',
    ):
        assert secret not in text
    assert before == {p: p.read_bytes() for p in root.rglob("*.json")}


def test_two_attempt_mismatch_not_selected(tmp_path: Path) -> None:
    def mutate(result, profile, attempt):
        if profile == "REFERENCE_RAW" and attempt == 2:
            result["outcomes"][0]["r"] = Decimal("2")

    root, records = released_fixture(tmp_path, mutate=mutate)
    report = cli.validate_released(root=root, oos_records=records, synthetic=True)
    assert report["status"] == "INVALID"
    assert report["within_profile_byte_repeatability"]["REFERENCE_RAW"] == "INVALID"
    assert len(report["attempts"]) == 4


@pytest.mark.parametrize(
    "target", ["receipt", "qa", "record", "canonical", "profile", "run", "prereg"]
)
def test_identity_links_fail_closed(tmp_path: Path, target: str) -> None:
    root, records = released_fixture(tmp_path)
    stem = "reference_raw-attempt-1.json"
    if target in ("receipt", "qa", "record"):
        path = (
            records[0]
            if target == "record"
            else root / ("receipts" if target == "receipt" else "is-qa") / stem
        )
        data = json.loads(path.read_bytes())
        data[
            "result_sha256"
            if target == "receipt"
            else "seal_sha256"
            if target == "record"
            else "scenario_run_id"
        ] = "wrong"
        path.write_text(json.dumps(data))
    else:
        path = root / "released" / stem
        if target == "canonical":
            path.write_bytes(b"PRIVATE_BAD_JSON")
        else:
            obj = custody._untag(json.loads(path.read_bytes()))
            if target == "profile":
                obj["manifest"]["fills"]["profile_id"] = "ADVERSE_RAW"
            elif target == "run":
                obj["result"]["scenario_run_id"] = "wrong"
            else:
                # Synthetic mode cannot confer real protected preregistration.
                obj["manifest"]["source"]["source_diagnostic_id"] = custody.SOURCE
            path.write_bytes(custody._canonical(obj))
    report = cli.validate_released(root=root, oos_records=records, synthetic=True)
    assert report["status"] == "INVALID"
    assert "PRIVATE_BAD_JSON" not in json.dumps(report)


def test_missing_extra_and_public_or_symlink_inputs_rejected(tmp_path: Path) -> None:
    root, records = released_fixture(tmp_path)
    extra = root / "released" / "extra.json"
    extra.write_text("synthetic")
    with pytest.raises(custody.CustodyBlocked):
        cli.validate_released(root=root, oos_records=records, synthetic=True)
    extra.unlink()
    selected = root / "released/reference_raw-attempt-1.json"
    selected.chmod(0o644)
    assert (
        cli.validate_released(root=root, oos_records=records, synthetic=True)["status"] == "INVALID"
    )
    selected.chmod(0o600)
    selected.unlink()
    with pytest.raises(custody.CustodyBlocked):
        cli.validate_released(root=root, oos_records=records, synthetic=True)


def test_real_mode_refuses_synthetic_before_full_result_parse(tmp_path: Path, monkeypatch) -> None:
    root, records = released_fixture(tmp_path)

    def forbidden(*args):
        pytest.fail("full result must not be parsed without real release authority")

    monkeypatch.setattr(custody, "_parse_result", forbidden)
    assert cli.validate_released(root=root, oos_records=records)["status"] == "INVALID"


def test_cli_exclusive_private_output_and_summary_gate(tmp_path: Path, capsys) -> None:
    root, records = released_fixture(tmp_path)
    output = tmp_path / "reports"
    output.mkdir(mode=0o700)
    target = output / "validation.json"
    args = [
        "--root",
        str(root),
        "--oos-records",
        *map(str, records),
        "--synthetic-test-only",
        "--output",
        str(target),
    ]
    assert cli.main(args) == 2
    raw = target.read_bytes()
    assert target.stat().st_mode & 0o777 == 0o600
    assert cli.main(args) == 1
    assert target.read_bytes() == raw
    assert "CUSTODY_OR_SELECTION_BLOCKED" in capsys.readouterr().out
    target2 = output / "summary.json"
    args[-1] = str(target2)
    assert cli.main([*args, "--research-summary"]) == 2
    assert json.loads(target2.read_bytes())["status"] == "WITHHELD"
    protected = tmp_path / ".signalforge-data"
    protected.mkdir(mode=0o700)
    args[-1] = str(protected / "report.json")
    assert cli.main(args) == 1
    assert not (protected / "report.json").exists()


def test_published_bindings_have_complete_fingerprints() -> None:
    for sha, qa, records in cli.APPROVED.values():
        assert all(len(value) == 64 for value in (sha, *qa, *records))


def test_ambient_decimal_precision_does_not_change_report(tmp_path: Path) -> None:
    from decimal import localcontext

    root, records = released_fixture(tmp_path)
    expected = cli.validate_released(root=root, oos_records=records, synthetic=True)
    with localcontext() as context:
        context.prec = 3
        context.Emax = 1
        assert cli.validate_released(root=root, oos_records=records, synthetic=True) == expected


@pytest.mark.parametrize("root_style", ["canonical", "dotdot"])
def test_output_cannot_add_files_to_existing_custody(
    tmp_path: Path, capsys, root_style: str
) -> None:
    root, records = released_fixture(tmp_path)
    input_root = root if root_style == "canonical" else root / ".." / root.name
    args = [
        "--root",
        str(input_root),
        "--oos-records",
        *map(str, records),
        "--synthetic-test-only",
        "--output",
        str(root / "released/report.json"),
    ]
    assert cli.main(args) == 1
    assert not (root / "released/report.json").exists()
    assert "CUSTODY_OR_SELECTION_BLOCKED" in capsys.readouterr().out


def test_symlink_selected_input_rejected(tmp_path: Path) -> None:
    root, records = released_fixture(tmp_path)
    selected = root / "released/reference_raw-attempt-1.json"
    other = private(tmp_path / "synthetic-copy.json", selected.read_bytes())
    selected.unlink()
    selected.symlink_to(other)
    report = cli.validate_released(root=root, oos_records=records, synthetic=True)
    assert report["status"] == "INVALID"
    assert report["attempts"][0]["identity_check"] == "INVALID"


def test_stdout_cli_is_machine_readable_and_repeatable(tmp_path: Path) -> None:
    import subprocess

    root, records = released_fixture(tmp_path)
    command = [
        sys.executable,
        str(SCRIPTS / "stage6_validate_released.py"),
        "--root",
        str(root),
        "--oos-records",
        *map(str, records),
        "--synthetic-test-only",
    ]
    first = subprocess.run(command, capture_output=True, check=False)
    second = subprocess.run(command, capture_output=True, check=False)
    assert first.returncode == second.returncode == 2
    assert first.stdout == second.stdout
    assert first.stderr == second.stderr == b""
    report = json.loads(first.stdout)
    assert report["status"] == "INCONCLUSIVE"
    assert not report["point_metrics_allowed"]


def test_source_invalid_failure_is_invalid() -> None:
    result = result_fixture()
    result.update(failure="SOURCE_INVALID: synthetic", outcomes=[], trace=[], blocked_decisions=[])
    assert validate_result(result)["status"] == "INVALID"


def test_noncanonical_timestamp_spelling_is_rejected() -> None:
    result = result_fixture()
    result["trace"][0]["bucket_start"] = "2026-06-30 23:59:00+00:00"
    assert validate_result(result)["checks"]["SAVED_LIFECYCLE_CONSISTENCY"] == "INVALID"


def test_oos_preregistration_mismatch_is_rejected(tmp_path: Path) -> None:
    # Synthetic local record only. Exercise the exact shared approval rule used
    # by production validation without presenting fabricated protected results.
    path = private(
        tmp_path / "synthetic-approval.json",
        json.dumps(
            {
                "parent_issue": 253,
                "decision": "OOS_RELEASE_ACCEPT",
                "record_url": cli.OOS_URL,
                "preregistration_id": "synthetic-wrong-prereg",
            }
        ).encode(),
    )
    with pytest.raises(custody.CustodyBlocked, match="preregistration_id"):
        custody._check_approval(
            path, decision="OOS_RELEASE_ACCEPT", extra={"preregistration_id": custody.PREREG}
        )
