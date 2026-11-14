"""Synthetic adversarial assurance for the SF-260 v1 IS-first CLI.

No SF-088 data or private 90D result is read. All identities are generated in
a temporary 0700 workspace. These fixtures do not claim historical evidence.
"""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from scripts import stage6_90d_v1_is_first_qa as qa
from scripts import stage6_result_custody as canonical


def _write(path: Path, data: bytes) -> None:
    path.write_bytes(data)
    path.chmod(0o600)


def _manifest(profile: str) -> dict[str, Any]:
    return {
        "mode_and_schema": {
            "mode": "SCENARIO_RESEARCH",
            "schema": "scenario-manifest-v1",
            "simulator": "btc-ohlc-path-scenario-v1",
            "study_variant": qa.VARIANT,
            "sample_status": "REPEATED_SAMPLE",
            "window_selection": "EARLIEST_90_MEASURED_UTC_DAYS",
        },
        "source": {
            "source_diagnostic_id": "synthetic-sf260-qa",
            "content_hash": "synthetic-source",
            "dataset_id": "synthetic-source",
        },
        "strategy": {"synthetic_fixture_identity": "synthetic-sf260-qa"},
        "implementation": {"revision": "synthetic-fixture-v1"},
        "fills": {"profile_id": profile},
        "session_and_window": {
            "pre_roll_start": qa.SOURCE_START.isoformat(),
            "is_start": qa.IS_START.isoformat(),
            "oos_start": qa.OOS_START.isoformat(),
            "measured_end": qa.MEASURED_END.isoformat(),
        },
    }


def _result(manifest: dict[str, Any]) -> dict[str, Any]:
    result = {name: None for name in canonical.FROZEN_RESULTS}
    result.update({
        "mode": "SCENARIO_RESEARCH",
        "schema_version": "scenario-result-v1",
        "scenario_run_id": canonical._hash_config({
            "domain": "scenario-run-v1", "inputs": manifest,
        }),
        "execution_valid": False,
        "certainty": "SCENARIO_CONDITIONED",
        "replay_verified": True,
        "is_observed": 17_280,
        "oos_observed": 8_640,
        "unsupported": 0,
        "failure": None,
        "failure_bucket": None,
        "event_count": 0,
        "terminal_active_state": None,
        "attempted_outcome_count": 0,
        "attempted_trace_count": 0,
        "blocked_actionable_count": 0,
        "failure_opportunity_id": None,
        "failure_signal_interval_start": None,
        "last_complete_bucket": None,
        "method_status": "SCENARIO_METHOD_VALID",
        "outcomes": [],
        "trace": [],
        "blocked_decisions": [],
    })
    return result


def _rewrite(root: Path, profile: str, attempt: int, record: dict[str, Any]) -> None:
    folder = root / f"{profile.lower()}-attempt-{attempt}"
    raw = canonical._canonical(record)
    _write(folder / "canonical-result.json", raw)
    _write(
        folder / "worker-receipt.json",
        (json.dumps({
            "status": "CANONICAL_WRITE_COMPLETED_METHOD_UNASSESSED",
            "variant": qa.VARIANT,
            "profile": profile,
            "attempt": attempt,
            "scenario_run_id": record["result"]["scenario_run_id"],
            "canonical_sha256": qa.hashlib.sha256(raw).hexdigest(),
            "canonical_bytes": len(raw),
            "execution_valid": False,
            "oos_released": False,
        }, sort_keys=True) + "\n").encode(),
    )


def _record(profile: str) -> dict[str, Any]:
    manifest = _manifest(profile)
    result = _result(manifest)
    return {
        "manifest": manifest,
        "result": result,
        "scenario_result_id": canonical._hash_config({
            "domain": "scenario-result-v1", "result": result,
        }),
    }


@pytest.fixture()
def synthetic_root(tmp_path: Path) -> Path:
    root = tmp_path / "synthetic"
    root.mkdir(mode=0o700)
    for profile in qa.PROFILES:
        for attempt in (1, 2):
            (root / f"{profile.lower()}-attempt-{attempt}").mkdir(mode=0o700)
            _rewrite(root, profile, attempt, _record(profile))
    return root


def _mutate(root: Path, profile: str, operation: Any) -> None:
    for attempt in (1, 2):
        folder = root / f"{profile.lower()}-attempt-{attempt}"
        _, manifest, result = canonical._parse_result(folder / "canonical-result.json")
        envelope = {
            "manifest": copy.deepcopy(manifest),
            "result": copy.deepcopy(result),
        }
        operation(envelope)
        envelope["result"]["scenario_run_id"] = canonical._hash_config({
            "domain": "scenario-run-v1", "inputs": envelope["manifest"],
        })
        envelope["scenario_result_id"] = canonical._hash_config({
            "domain": "scenario-result-v1", "result": envelope["result"],
        })
        _rewrite(root, profile, attempt, envelope)


def test_four_synthetic_results_via_actual_cli_without_pythonpath(
    synthetic_root: Path, tmp_path: Path,
) -> None:
    cli = Path(qa.__file__).resolve()
    env = dict(os.environ)
    for key in (
        "PYTHONPATH", "COV_CORE_SOURCE", "COV_CORE_CONFIG",
        "COV_CORE_DATAFILE", "COVERAGE_PROCESS_START", "COVERAGE_FILE",
    ):
        env.pop(key, None)
    before = {
        str(p): p.read_bytes()
        for p in synthetic_root.rglob("*") if p.is_file()
    }
    proc = subprocess.run(
        [sys.executable, str(cli), "--results-root", str(synthetic_root),
         "--synthetic-test-only"],
        cwd=tmp_path, env=env, capture_output=True, text=True,
        timeout=20, check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stderr == ""
    data = json.loads(proc.stdout)
    assert data["artifact_integrity"] == "PASS"
    assert data["within_profile_byte_repeatability"] == "PASS"
    assert data["checks"]["FROZEN_GRID_RUNNER_REPORTED"] == "PASS"
    assert data["B3_INDEPENDENT_STRICT_COVERAGE"] == "NOT_ESTABLISHED"
    assert data["economics"] == "WITHHELD"
    assert data["oos"] == "SEALED"
    assert data["gate_e"] == "NOT_APPROVED"
    assert "outcomes" not in proc.stdout and "entry_price" not in proc.stdout
    assert before == {
        str(p): p.read_bytes()
        for p in synthetic_root.rglob("*") if p.is_file()
    }


@pytest.mark.parametrize("change", [
    "truncated", "changed_receipt", "symlink", "active_marker",
    "wrong_profile", "partial", "failure_marker",
])
def test_bad_artifact_or_custody_blocks(synthetic_root: Path, change: str) -> None:
    folder = synthetic_root / "reference_raw-attempt-1"
    path = folder / "canonical-result.json"
    if change == "truncated":
        _write(path, path.read_bytes()[:-17])
    elif change == "changed_receipt":
        rec = json.loads((folder / "worker-receipt.json").read_text())
        rec["canonical_sha256"] = "0" * 64
        _write(folder / "worker-receipt.json", json.dumps(rec).encode())
    elif change == "symlink":
        data = path.read_bytes()
        other = folder / "copy.json"
        _write(other, data)
        path.unlink()
        path.symlink_to(other)
    elif change == "active_marker":
        _write(synthetic_root / ".sf260-90d-active.json", b"{}")
    elif change == "wrong_profile":
        rec = json.loads((folder / "worker-receipt.json").read_text())
        rec["profile"] = "ADVERSE_RAW"
        _write(folder / "worker-receipt.json", json.dumps(rec).encode())
    elif change == "partial":
        _write(folder / "partial.json", b"x")
    elif change == "failure_marker":
        _write(folder / "failure.json", b"x")
    with pytest.raises((qa.ValidationBlocked, canonical.CustodyBlocked)):
        qa.validate(synthetic_root, synthetic=True)


@pytest.mark.parametrize(("field", "value", "expected"), [
    ("is_observed", 17_279, "INCONCLUSIVE"),
    ("oos_observed", 8_641, "INCONCLUSIVE"),
    ("unsupported", 1, "INCONCLUSIVE"),
    ("replay_verified", False, "INCONCLUSIVE"),
    ("method_status", "SCENARIO_METHOD_INCONCLUSIVE", "INCONCLUSIVE"),
])
def test_rehashed_self_report_discrepancy_never_becomes_pass(
    synthetic_root: Path, field: str, value: object, expected: str,
) -> None:
    def alter(envelope: dict[str, Any]) -> None:
        result = envelope["result"]
        result[field] = value
        if field != "method_status":
            result["method_status"] = "SCENARIO_METHOD_INCONCLUSIVE"
    _mutate(synthetic_root, "REFERENCE_RAW", alter)
    answer = qa.validate(synthetic_root, synthetic=True)
    tag = {
        "is_observed": "FROZEN_GRID_RUNNER_REPORTED",
        "oos_observed": "FROZEN_GRID_RUNNER_REPORTED",
        "unsupported": "ZERO_UNSUPPORTED_RUNNER_REPORTED",
        "replay_verified": "REPLAY_RUNNER_REPORTED",
        "method_status": "METHOD_STATUS_RUNNER_REPORTED",
    }[field]
    assert answer["checks"][tag] == expected
    assert answer["economics"] == "WITHHELD"


def test_self_consistent_rehashed_lifecycle_contradiction_blocks(
    synthetic_root: Path,
) -> None:
    def alter(envelope: dict[str, Any]) -> None:
        envelope["result"]["attempted_outcome_count"] = 1
    _mutate(synthetic_root, "REFERENCE_RAW", alter)
    with pytest.raises(qa.ValidationBlocked):
        qa.validate(synthetic_root, synthetic=True)


def test_rehashed_unexpected_schema_blocks(synthetic_root: Path) -> None:
    def alter(envelope: dict[str, Any]) -> None:
        envelope["result"]["unexpected"] = "SECRET_OOS_PROFIT_987"
    _mutate(synthetic_root, "REFERENCE_RAW", alter)
    with pytest.raises((qa.ValidationBlocked, canonical.CustodyBlocked)):
        qa.validate(synthetic_root, synthetic=True)


def test_protected_read_denied_before_any_result_access(tmp_path: Path) -> None:
    nonexistent = tmp_path / "does-not-exist"
    with pytest.raises(qa.ValidationBlocked):
        qa.validate(nonexistent)
    with pytest.raises(qa.ValidationBlocked):
        qa.validate(nonexistent, inspection_record=nonexistent)


def test_cli_never_echoes_malformed_payload_or_exception(
    synthetic_root: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    folder = synthetic_root / "reference_raw-attempt-1"
    _write(folder / "canonical-result.json", b"SECRET_OOS_PROFIT_987")
    exit_code = qa.main(["--results-root", str(synthetic_root), "--synthetic-test-only"])
    report = capsys.readouterr()
    assert exit_code == 2
    assert "SECRET_OOS_PROFIT_987" not in report.out + report.err
    assert "Traceback" not in report.out + report.err
    assert report.err == ""
    assert json.loads(report.out)["economics"] == "WITHHELD"


def test_no_runner_invocation(synthetic_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from signalforge.research.scenario_execution import ScenarioResearchRunner

    def forbidden(*_args: object, **_kwargs: object) -> None:
        pytest.fail("historical execution is forbidden in v1 validation")

    monkeypatch.setattr(ScenarioResearchRunner, "run_verified", forbidden)
    assert qa.validate(synthetic_root, synthetic=True)["artifact_integrity"] == "PASS"


def test_immutable_hash_rechecked_at_actual_semantic_read(
    synthetic_root: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A changed canonical file between fingerprint and parse must never pass."""
    original = qa.canonical._parse_result
    attacked = False

    def swapped(path: Path) -> tuple[bytes, dict[str, Any], dict[str, Any]]:
        nonlocal attacked
        if not attacked:
            attacked = True
            folder = synthetic_root / "reference_raw-attempt-1"
            target = folder / "canonical-result.json"
            _, manifest, result = original(target)
            # This is semantically allowed; only rehashing the *parsed* bytes
            # detects a between-check-and-use swap.
            result["method_status"] = "SCENARIO_METHOD_INCONCLUSIVE"
            new_record = {
                "manifest": manifest,
                "result": result,
                "scenario_result_id": canonical._hash_config({
                    "domain": "scenario-result-v1", "result": result,
                }),
            }
            _write(target, canonical._canonical(new_record))
        return original(path)

    monkeypatch.setattr(qa.canonical, "_parse_result", swapped)
    with pytest.raises(qa.ValidationBlocked):
        qa.validate(synthetic_root, synthetic=True)


def test_valid_separate_owner_comment_url_is_accepted_as_local_shape_only(
    tmp_path: Path,
) -> None:
    """This tests record format, not existence or authenticity of an owner GO."""
    receipt = tmp_path / "synthetic-inspection-approval.json"
    record = {
        "decision": "SF260_V1_IS_QA_PROTECTED_READ_ACCEPT",
        "parent_issue": 253,
        "variant": qa.VARIANT,
        "execution_revision": qa.REVISION,
        "input_preregistration_id": qa.PREREG,
        "source_derivation_id": qa.DERIVATION,
        "approval_url": (
            "https://github.com/harishkamathuk/signalforge/issues/253"
            "#issuecomment-9999999999"
        ),
    }
    _write(receipt, (json.dumps(record) + "\n").encode())
    qa.protected_permission(receipt)
    record["approval_url"] = (
        "https://github.com/harishkamathuk/signalforge/issues/253"
        "#issuecomment-6883237655"
    )
    _write(receipt, (json.dumps(record) + "\n").encode())
    with pytest.raises(qa.ValidationBlocked):
        qa.protected_permission(receipt)


def _one_closed(envelope: dict[str, Any], *, action: str) -> None:
    result = envelope["result"]
    entry = (qa.IS_START + qa.timedelta(minutes=1)).isoformat()
    leave = (qa.IS_START + qa.timedelta(minutes=2)).isoformat()
    result["outcomes"] = [{
        "opportunity_id": "e" * 64,
        "certainty": "SCENARIO_CONDITIONED",
        "state": "CLOSED",
        "reason": "TARGET",
        "entry_bucket": entry,
        "exit_bucket": leave,
        "entry_price": Decimal("100"),
        "exit_price": Decimal("105"),
        "r": Decimal("0.5"),
        "holding_span_1m_buckets": 2,
    }]
    result["trace"] = [{
        "bucket_start": entry,
        "from_level": Decimal("100"),
        "to_level": Decimal("100"),
        "action": "ENTRY",
        "ordering": "OBSERVED_OPEN",
        "modeled_base": Decimal("100"),
    }, {
        "bucket_start": leave,
        "from_level": Decimal("105"),
        "to_level": Decimal("105"),
        "action": action,
        "ordering": "OBSERVED_OPEN",
        "modeled_base": Decimal("105"),
    }]
    result["attempted_outcome_count"] = 1
    result["attempted_trace_count"] = 2
    result["event_count"] = 2


def test_valid_synthetic_saved_closed_lifecycle_is_consistent(
    synthetic_root: Path,
) -> None:
    _mutate(synthetic_root, "REFERENCE_RAW", lambda e: _one_closed(e, action="TARGET"))
    answer = qa.validate(synthetic_root, synthetic=True)
    assert answer["checks"]["SAVED_LIFECYCLE_INDEPENDENT_CONSISTENCY"] == "PASS"
    assert answer["economics"] == "WITHHELD"


def test_forged_exit_action_rejected_even_with_consistent_ids(
    synthetic_root: Path,
) -> None:
    _mutate(synthetic_root, "REFERENCE_RAW", lambda e: _one_closed(e, action="STOP"))
    with pytest.raises(qa.ValidationBlocked):
        qa.validate(synthetic_root, synthetic=True)


def test_forged_post_exit_blocking_interval_rejected(
    synthetic_root: Path,
) -> None:
    def alter(envelope: dict[str, Any]) -> None:
        _one_closed(envelope, action="TARGET")
        result = envelope["result"]
        result["blocked_decisions"] = [{
            "interval_start": (qa.IS_START + qa.timedelta(minutes=5)).isoformat(),
            "interval_end": (qa.IS_START + qa.timedelta(minutes=10)).isoformat(),
            "blocking_opportunity_id": "e" * 64,
            "blocking_state": "OPEN",
        }]
        result["blocked_actionable_count"] = 1

    _mutate(synthetic_root, "REFERENCE_RAW", alter)
    with pytest.raises(qa.ValidationBlocked):
        qa.validate(synthetic_root, synthetic=True)


@pytest.mark.parametrize("kind", [
    "mismatched_source", "mismatched_simulator", "mismatched_profile",
])
def test_forged_rehashed_manifest_rejected(
    synthetic_root: Path, kind: str,
) -> None:
    def alter(envelope: dict[str, Any]) -> None:
        m = envelope["manifest"]
        if kind == "mismatched_source":
            m["source"]["content_hash"] = qa.CHILD
        elif kind == "mismatched_simulator":
            m["mode_and_schema"]["simulator"] = "unexpected-mode"
        else:
            m["fills"]["profile_id"] = "ADVERSE_RAW"

    _mutate(synthetic_root, "REFERENCE_RAW", alter)
    with pytest.raises(qa.ValidationBlocked):
        qa.validate(synthetic_root, synthetic=True)


def test_rehashed_incorrect_holding_span_is_rejected(
    synthetic_root: Path,
) -> None:
    def alter(envelope: dict[str, Any]) -> None:
        _one_closed(envelope, action="TARGET")
        envelope["result"]["outcomes"][0]["holding_span_1m_buckets"] = 999

    _mutate(synthetic_root, "REFERENCE_RAW", alter)
    with pytest.raises(qa.ValidationBlocked):
        qa.validate(synthetic_root, synthetic=True)
