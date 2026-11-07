"""Synthetic-only offline tests for the #264 full-window custody boundary."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import stat
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
MODULE_PATH = SCRIPTS / "stage6_result_custody.py"
SPEC = importlib.util.spec_from_file_location("stage6_result_custody", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
custody = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = custody
SPEC.loader.exec_module(custody)


def private_file(path: Path, raw: bytes) -> Path:
    """Create a restricted synthetic input fixture with exact bytes."""
    path.write_bytes(raw)
    path.chmod(0o600)
    return path


def fixture(tmp_path: Path, *, profile: str = "REFERENCE_RAW") -> tuple[Path, Path, bytes]:
    """Synthetic canonical result with fake economics deliberately confined to OOS."""
    root = tmp_path / "vault"
    root.mkdir(mode=0o700)
    manifest = {
        "source": {"source_diagnostic_id": "synthetic-sf264",
                   "content_hash": "synthetic-nonprovider"},
        "strategy": {"synthetic_fixture_identity": "synthetic-sf264"},
        "fills": {"profile_id": profile},
        "implementation": {"revision": "synthetic-only"},
    }
    result = {key: None for key in custody.FROZEN_RESULTS}
    result.update({"mode": "SCENARIO_RESEARCH", "schema_version": "scenario-result-v1",
                   "execution_valid": False, "certainty": "SCENARIO_CONDITIONED",
                   "replay_verified": True, "is_observed": 10, "oos_observed": 4,
                   "unsupported": 0, "failure": None, "event_count": 4,
                   "attempted_outcome_count": 1, "attempted_trace_count": 1,
                   "blocked_actionable_count": 0,
                   "method_status": "SCENARIO_METHOD_INCONCLUSIVE",
                   "outcomes": [{"r": "TOP_SECRET_OOS_PROFIT"}],
                   "trace": [{"bucket_start": "2026-07-01T00:00:00+00:00",
                              "action": "OOS_SECRET"}], "blocked_decisions": []})
    run = custody._hash_config({"domain": "scenario-run-v1", "inputs": manifest})
    result["scenario_run_id"] = run
    record = {"manifest": manifest, "result": result,
              "scenario_result_id": custody._hash_config({"domain": "scenario-result-v1",
                                                          "result": result})}
    raw = custody._canonical(record)
    source = private_file(tmp_path / "generated-synthetic.json", raw)
    return root, source, raw


def test_synthetic_seal_is_qa_and_oos_release(tmp_path: Path) -> None:
    root, source, raw = fixture(tmp_path)
    receipt = custody.seal(root=root, source_file=source, profile="REFERENCE_RAW",
                           attempt=1, synthetic=True)
    assert receipt["status"] == "SEALED_NO_DISCLOSURE"
    assert receipt["result_sha256"] == hashlib.sha256(raw).hexdigest()
    assert (root / "sealed/reference_raw-attempt-1.json").read_bytes() == raw
    assert stat.S_IMODE((root / "sealed/reference_raw-attempt-1.json").stat().st_mode) == 0o600
    qa = custody.is_qa(root=root, profile="REFERENCE_RAW", attempt=1)
    assert qa["status"] == "IS_QA_ONLY"
    published = (root / "is-qa/reference_raw-attempt-1.json").read_text()
    assert "TOP_SECRET" not in published and "OOS_SECRET" not in published
    assert "oos_observed" not in published and "outcomes" not in published
    release = private_file(tmp_path / "release.json", json.dumps({
        "decision": "SYNTHETIC_OOS_RELEASE_TEST", "parent_issue": 253,
        "record_url": "https://github.com/harishkamathuk/signalforge/issues/253#issuecomment-123",
        "seal_sha256": receipt["result_sha256"], "is_qa_sha256": qa["is_qa_sha256"],
    }).encode())
    assert custody.release_oos(root=root, profile="REFERENCE_RAW", attempt=1,
                               oos_record=release)["status"] == "OOS_RELEASED_BY_OPERATOR_RECORD"
    assert (root / "released/reference_raw-attempt-1.json").read_bytes() == raw
    with pytest.raises(custody.CustodyBlocked, match="collision"):
        custody.release_oos(root=root, profile="REFERENCE_RAW", attempt=1, oos_record=release)


def test_duplicate_seal_fails_without_overwrite(tmp_path: Path) -> None:
    root, source, raw = fixture(tmp_path)
    custody.seal(root=root, source_file=source, profile="REFERENCE_RAW", attempt=1,
                 synthetic=True)
    with pytest.raises(custody.CustodyBlocked, match="collision"):
        custody.seal(root=root, source_file=source, profile="REFERENCE_RAW", attempt=1,
                     synthetic=True)
    assert (root / "sealed/reference_raw-attempt-1.json").read_bytes() == raw


def test_result_tamper_fails_closed(tmp_path: Path) -> None:
    root, source, _ = fixture(tmp_path)
    custody.seal(root=root, source_file=source, profile="REFERENCE_RAW", attempt=1,
                 synthetic=True)
    sealed = root / "sealed/reference_raw-attempt-1.json"
    sealed.write_bytes(sealed.read_bytes().replace(b"synthetic-sf264", b"synthetic-sf265"))
    with pytest.raises(custody.CustodyBlocked):
        custody.is_qa(root=root, profile="REFERENCE_RAW", attempt=1)
    assert not (root / "is-qa/reference_raw-attempt-1.json").exists()


def test_release_requires_is_checkpoint_and_valid_separate_authority(tmp_path: Path) -> None:
    root, source, _ = fixture(tmp_path)
    receipt = custody.seal(root=root, source_file=source, profile="REFERENCE_RAW",
                           attempt=1, synthetic=True)
    release = private_file(tmp_path / "release.json", json.dumps({
        "decision": "SYNTHETIC_OOS_RELEASE_TEST", "parent_issue": 253,
        "record_url": "https://github.com/harishkamathuk/signalforge/issues/253#issuecomment-123",
        "seal_sha256": receipt["result_sha256"], "is_qa_sha256": "wrong",
    }).encode())
    with pytest.raises(custody.CustodyBlocked):
        custody.release_oos(root=root, profile="REFERENCE_RAW", attempt=1, oos_record=release)
    qa = custody.is_qa(root=root, profile="REFERENCE_RAW", attempt=1)
    with pytest.raises(custody.CustodyBlocked, match="owner decision mismatch"):
        custody.release_oos(root=root, profile="REFERENCE_RAW", attempt=1, oos_record=release)
    assert qa["is_qa_sha256"] != "wrong"
    assert not (root / "released/reference_raw-attempt-1.json").exists()


@pytest.mark.parametrize("mutator", [
    lambda obj: obj["result"].update(execution_valid=True),
    lambda obj: obj["result"].update(scenario_run_id="wrong"),
    lambda obj: obj["result"].update(extra_field="unknown"),
    lambda obj: obj["result"].update(outcomes=[{"r": float("nan")}]),
])
def test_invalid_canonical_result_rejected(tmp_path: Path, mutator: object) -> None:
    root, source, raw = fixture(tmp_path)
    obj = custody._untag(json.loads(raw))
    assert isinstance(obj, dict)
    mutator(obj)
    try:
        source.write_bytes(custody._canonical(obj))
    except custody.CustodyBlocked:
        # Invalid non-canonical number is rejected even before serialization.
        return
    with pytest.raises((custody.CustodyBlocked, ValueError)):
        custody.seal(root=root, source_file=source, profile="REFERENCE_RAW", attempt=1,
                     synthetic=True)


def test_synthetic_flag_cannot_accept_protected_source(tmp_path: Path) -> None:
    root, source, raw = fixture(tmp_path)
    obj = custody._untag(json.loads(raw))
    obj["manifest"]["source"]["source_diagnostic_id"] = custody.SOURCE
    # The run/result identities must also be recomputed, not accidentally differ.
    new_run = custody._hash_config({"domain": "scenario-run-v1", "inputs": obj["manifest"]})
    obj["result"]["scenario_run_id"] = new_run
    obj["scenario_result_id"] = custody._hash_config({"domain": "scenario-result-v1",
                                                     "result": obj["result"]})
    source.write_bytes(custody._canonical(obj))
    with pytest.raises(custody.CustodyBlocked, match="synthetic-only"):
        custody.seal(root=root, source_file=source, profile="REFERENCE_RAW", attempt=1,
                     synthetic=True)


def test_unapproved_protected_path_fails_closed(tmp_path: Path) -> None:
    root, source, _ = fixture(tmp_path)
    with pytest.raises(custody.CustodyBlocked):
        custody.seal(root=root, source_file=source, profile="REFERENCE_RAW", attempt=1,
                     synthetic=False)


def test_public_mode_and_symlink_rejected(tmp_path: Path) -> None:
    root, source, _ = fixture(tmp_path)
    root.chmod(0o755)
    with pytest.raises(custody.CustodyBlocked, match="0700"):
        custody.seal(root=root, source_file=source, profile="REFERENCE_RAW",
                     attempt=1, synthetic=True)
    root.chmod(0o700)
    alias = tmp_path / "alias"
    alias.symlink_to(root, target_is_directory=True)
    with pytest.raises(custody.CustodyBlocked, match="symlink"):
        custody.seal(root=alias, source_file=source, profile="REFERENCE_RAW",
                     attempt=1, synthetic=True)
    source.chmod(0o644)
    with pytest.raises(custody.CustodyBlocked, match="0600"):
        custody.seal(root=root, source_file=source, profile="REFERENCE_RAW",
                     attempt=1, synthetic=True)


def test_repository_output_path_rejected(tmp_path: Path) -> None:
    repo = tmp_path / "project"
    repo.mkdir()
    (repo / ".git").mkdir()
    root = repo / "custody"
    root.mkdir(mode=0o700)
    source = private_file(tmp_path / "source.json", b"{}")
    with pytest.raises(custody.CustodyBlocked, match="Git checkout"):
        custody.seal(root=root, source_file=source, profile="REFERENCE_RAW",
                     attempt=1, synthetic=True)


def test_resources_are_snapshot_only(tmp_path: Path) -> None:
    root, _, _ = fixture(tmp_path)
    result = custody.resource_check(root=root, min_ram_gib=9999, min_disk_gib=9999)
    assert result["status"] == "CAPACITY_SNAPSHOT_ONLY_NOT_FULL_RUN_CERTIFIED"
    assert result["meets_thresholds"] is False
    assert result["available_ram_bytes"] > 0
    assert "does not bound" in result["limits"]


def test_protected_seal_never_reads_result_before_gate_d_accept(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, source, _ = fixture(tmp_path)

    def no_read(_path: Path) -> None:
        raise AssertionError("protected performance was read before Gate D")

    monkeypatch.setattr(custody, "_parse_result", no_read)
    with pytest.raises(custody.CustodyBlocked, match="requires approved Gate D"):
        custody.seal(root=root, source_file=source, profile="REFERENCE_RAW", attempt=1,
                     synthetic=False)
