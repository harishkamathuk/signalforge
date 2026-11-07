# ruff: noqa: E501
"""Offline Stage 6 sealed-result custody; never run research or approve a gate.

This utility only consumes existing canonical scenario-result files *after* an
explicit Gate D acceptance (unless an unmistakable synthetic fixture is used).
It cannot enforce separation of duties against the workstation owner. See
``docs/engineering/stage6-result-custody.md`` and GitHub #264.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import sys
from decimal import Decimal
from pathlib import Path

BASELINE = "5d2812d11f8f5f061a1b637726f9e73b488c6e43"
PREREG = "9f55f96b47d2f83c8231595769ad0e3aaede6ef17a599e68f6ea115d1d8252c2"
SOURCE = "8632150c1aa75689cb9b3fd933dc3e3d0672ce7eb31c1772b9597d7ce57b7ff6"
RUNS = {
    "REFERENCE_RAW": ("84ac178645c49c0d53ff22c676cb36243ed340945019d46cea878acbe0825099", "6c9f388e1732110177108489350a49c8d8028e7507f3f69e516630d1b7f1a22f"),
    "ADVERSE_RAW": ("75cea6ced58247ad86adc4d16a9a41e02d442274e733b6a957a761b682f30dcf", "5ed7494f7faafb52e71935f27f062fc595f93f5e89fb83256068e0c18d518ff8"),
}
FROZEN_RESULTS = {
    "mode", "schema_version", "scenario_run_id", "execution_valid", "certainty",
    "replay_verified", "is_observed", "oos_observed", "unsupported", "failure",
    "failure_bucket", "event_count", "terminal_active_state", "attempted_outcome_count",
    "attempted_trace_count", "blocked_actionable_count", "failure_opportunity_id",
    "failure_signal_interval_start", "last_complete_bucket", "method_status",
    "outcomes", "trace", "blocked_decisions",
}
COMMENT_URL = re.compile(r"https://github\.com/harishkamathuk/signalforge/issues/253#issuecomment-[1-9][0-9]*\Z")
GIB = 1024**3


class CustodyBlocked(ValueError):
    """An invariant was violated; do not publish or overwrite an artifact."""


def _check(value: bool, detail: str) -> None:
    if not value:
        raise CustodyBlocked(detail)


def _digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _number(value: Decimal) -> str:
    _check(value.is_finite(), "nonfinite canonical decimal")
    compact = value.normalize()
    return "0" if compact == 0 else format(compact, "f")


def _tag(value: object) -> object:
    if value is None:
        return ["null"]
    if isinstance(value, bool):
        return ["bool", value]
    if isinstance(value, int):
        return ["int", str(value)]
    if isinstance(value, Decimal):
        return ["decimal", _number(value)]
    if isinstance(value, str):
        return ["str", value]
    if isinstance(value, (tuple, list)):
        return ["list", [_tag(x) for x in value]]
    if isinstance(value, dict):
        _check(all(isinstance(k, str) for k in value), "non-string mapping key")
        return ["map", [[k, _tag(v)] for k, v in sorted(value.items())]]
    raise CustodyBlocked("unrecognised canonical type")


def _untag(node: object) -> object:
    _check(isinstance(node, list) and len(node) in (1, 2) and type(node[0]) is str,
           "invalid canonical node")
    kind = node[0]
    if kind == "null":
        _check(len(node) == 1, "invalid null")
        return None
    _check(len(node) == 2, "invalid canonical arity")
    value = node[1]
    if kind == "bool":
        _check(type(value) is bool, "invalid canonical bool")
        return value
    if kind == "str":
        _check(type(value) is str, "invalid canonical string")
        return value
    if kind == "int":
        _check(type(value) is str and str(int(value)) == value, "invalid canonical integer")
        return int(value)
    if kind == "decimal":
        _check(type(value) is str and _number(Decimal(value)) == value, "invalid canonical decimal")
        return Decimal(value)
    if kind == "list":
        _check(type(value) is list, "invalid canonical list")
        return [_untag(x) for x in value]
    if kind == "map":
        _check(type(value) is list, "invalid canonical map")
        output: dict[str, object] = {}
        previous: str | None = None
        for entry in value:
            _check(type(entry) is list and len(entry) == 2 and type(entry[0]) is str,
                   "invalid canonical map entry")
            key = entry[0]
            _check(previous is None or key > previous, "non-canonical or duplicate key")
            output[key] = _untag(entry[1])
            previous = key
        return output
    raise CustodyBlocked("unrecognised canonical tag")


def _canonical(value: object) -> bytes:
    return json.dumps(_tag(value), separators=(",", ":"), ensure_ascii=False).encode("utf-8") + b"\n"


def _hash_config(value: dict[str, object]) -> str:
    return _digest(_canonical(value).rstrip(b"\n"))


def _mapping(value: object, name: str) -> dict[str, object]:
    _check(type(value) is dict, name + " must be a mapping")
    return value


def _ancestors_safe(path: Path) -> Path:
    raw = path.absolute()
    for parent in (raw, *raw.parents):
        if parent.is_symlink():
            raise CustodyBlocked("symlink in custody path")
    return raw


def _private_directory(path: Path, *, repo: Path | None = None) -> Path:
    raw = _ancestors_safe(path)
    root = raw.resolve(strict=True)
    _check(root.is_dir() and stat.S_IMODE(root.stat().st_mode) == 0o700,
           "custody directory requires mode 0700")
    _check(".signalforge-data" not in root.parts and "sf088" not in root.parts and
           "sf096" not in root.parts, "protected source tree is not an output destination")
    if repo is not None:
        _check(not root.is_relative_to(_ancestors_safe(repo).resolve(strict=True)),
               "custody directory must be outside Git checkout")
    # Worktrees may use either a .git directory or a .git file. Never allow
    # an operator to accidentally commit sealed outcomes or their receipts.
    _check(not any((p / ".git").exists() for p in (root, *root.parents)),
           "custody directory must be outside every Git checkout")
    return root


def _private_file(path: Path) -> bytes:
    actual = _ancestors_safe(path)
    _check(actual.is_file() and not actual.is_symlink(), "missing private input")
    _check(stat.S_IMODE(actual.stat().st_mode) == 0o600,
           "private input requires 0600 permissions")
    return actual.read_bytes()


def _json_file(path: Path) -> dict[str, object]:
    return _mapping(json.loads(_private_file(path)), "approval/receipt")


def _subdir(root: Path, part: str) -> Path:
    folder = root / part
    try:
        folder.mkdir(mode=0o700)
    except FileExistsError:
        pass
    _check(not folder.is_symlink() and folder.is_dir() and
           stat.S_IMODE(folder.stat().st_mode) == 0o700,
           "custody subdirectory must be private and non-symlinked")
    return folder


def _write_once(path: Path, content: bytes) -> None:
    """Create one durable private artifact without overwriting or following symlinks."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        # Incomplete evidence is deliberately retained for manual quarantine:
        # silently deleting it would erase the incident/collision record.
        raise
    parent_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(parent_fd)
    finally:
        os.close(parent_fd)


def _manifest_record(path: Path) -> tuple[dict[str, object], str]:
    raw = _private_file(path)
    record = _mapping(_untag(json.loads(raw)), "canonical manifest")
    _check(_canonical(record) == raw and set(record) == {"input_mapping", "scenario_run_id"},
           "manifest not canonical")
    return _mapping(record["input_mapping"], "manifest input_mapping"), str(record["scenario_run_id"])


def _check_approval(path: Path, *, decision: str, extra: dict[str, object]) -> dict[str, object]:
    receipt = _json_file(path)
    _check(receipt.get("decision") == decision and receipt.get("parent_issue") == 253,
           "wrong/missing owner decision")
    _check(type(receipt.get("record_url")) is str and COMMENT_URL.fullmatch(receipt["record_url"]) is not None,
           "owner decision URL must link to a #253 comment")
    for key, value in extra.items():
        _check(receipt.get(key) == value, "owner decision mismatch: " + key)
    # This is a typed local attestation, NOT a cryptographic/API verification of
    # the linked GitHub comment. Human operator must check the decision itself.
    return receipt


def _parse_result(path: Path) -> tuple[bytes, dict[str, object], dict[str, object]]:
    raw = _private_file(path)
    record = _mapping(_untag(json.loads(raw)), "scenario result envelope")
    _check(_canonical(record) == raw and set(record) == {"manifest", "result", "scenario_result_id"},
           "scenario result is not canonical scenario-result JSON")
    manifest = _mapping(record["manifest"], "scenario input manifest")
    result = _mapping(record["result"], "scenario result mapping")
    _check(set(result) == FROZEN_RESULTS, "unapproved result schema keys")
    _check(result.get("mode") == "SCENARIO_RESEARCH" and result.get("schema_version") == "scenario-result-v1"
           and result.get("execution_valid") is False and result.get("certainty") == "SCENARIO_CONDITIONED",
           "scenario result boundary mismatch")
    _check(record["scenario_result_id"] == _hash_config({"domain": "scenario-result-v1", "result": result}),
           "scenario result identity mismatch")
    _check(result.get("scenario_run_id") == _hash_config({"domain": "scenario-run-v1", "inputs": manifest}),
           "scenario run identity mismatch")
    for field in ("is_observed", "oos_observed", "unsupported"):
        _check(type(result.get(field)) is int and result[field] >= 0, "invalid measured grid count")
    return raw, manifest, result


def _validate_source(manifest: dict[str, object], *, synthetic: bool) -> str:
    source = _mapping(manifest.get("source"), "manifest source")
    diagnostic = source.get("source_diagnostic_id")
    _check(type(diagnostic) is str, "missing source diagnostic identity")
    strat = _mapping(manifest.get("strategy"), "manifest strategy")
    implementation = _mapping(manifest.get("implementation"), "manifest implementation")
    if synthetic:
        _check(diagnostic.startswith("synthetic-") and
               type(strat.get("synthetic_fixture_identity")) is str and
               strat["synthetic_fixture_identity"].startswith("synthetic-") and
               source.get("content_hash") != "85d89887078504385a5023eaba007ffcdeeb7f4c67689c79cd5db9a407c999f9",
               "synthetic-only mode refuses protected source")
    else:
        _check(diagnostic == SOURCE and implementation.get("revision") == BASELINE and
               strat.get("synthetic_fixture_identity") is None,
               "protected source/revision is not frozen")
    return diagnostic


def seal(*, root: Path, source_file: Path, profile: str, attempt: int, synthetic: bool,
         private_manifest: Path | None = None, gate_d_record: Path | None = None) -> dict[str, object]:
    """Seal a pre-existing scenario result and its provenance, never run a strategy.

    Args:
        root: Existing private 0700 custody root outside Git/protected archive.
        source_file: Existing private 0600 canonical output produced elsewhere.
        profile: Registered RAW profile.
        attempt: Process-isolated attempt number, 1 or 2.
        synthetic: True only for explicitly synthetic test input.
        private_manifest: Frozen preflight manifest required for protected inputs.
        gate_d_record: Operator-attested external #253 Gate D ACCEPT required for protected inputs.

    Returns:
        Non-economic SHA/receipt summary. Failures never overwrite evidence.
    """
    _check(profile in RUNS and attempt in (1, 2), "unknown profile or attempt")
    root = _private_directory(root)
    # Check external Gate D authority BEFORE reading any protected full-result
    # bytes. Merely parsing outcomes would breach the pre-execution boundary.
    if not synthetic:
        _check(private_manifest is not None and gate_d_record is not None,
               "protected sealing requires approved Gate D and frozen private manifest")
        _check_approval(gate_d_record, decision="GATE_D_ACCEPT",
                        extra={"preregistration_id": PREREG,
                               "execution_revision": BASELINE})
    data, manifest, result = _parse_result(source_file)
    _validate_source(manifest, synthetic=synthetic)
    fills = _mapping(manifest.get("fills"), "manifest fills")
    _check(fills.get("profile_id") == profile, "wrong profile in scenario result")
    run_id = result["scenario_run_id"]
    if not synthetic:
        assert private_manifest is not None and gate_d_record is not None
        expected_run, expected_file_sha = RUNS[profile]
        _check(run_id == expected_run and _digest(_private_file(private_manifest)) == expected_file_sha,
               "frozen manifest/run identity differs")
        mapping, verified_id = _manifest_record(private_manifest)
        _check(mapping == manifest and verified_id == run_id, "full frozen input manifest mismatch")
    _check(result["is_observed"] <= 69984 and result["oos_observed"] <= 34848,
           "invalid scenario grid count")
    stem = f"{profile.lower()}-attempt-{attempt}"
    sealed = _subdir(root, "sealed") / f"{stem}.json"
    receipt_file = _subdir(root, "receipts") / f"{stem}.json"
    _check(not sealed.exists() and not receipt_file.exists(), "seal or receipt collision")
    sha = _digest(data)
    receipt: dict[str, object] = {
        "schema": "stage6-seal-receipt-v1", "profile": profile, "attempt": attempt,
        "source_kind": "SYNTHETIC_TEST_ONLY" if synthetic else "PROTECTED_GATE_D_APPROVED",
        "scenario_run_id": run_id, "result_sha256": sha, "byte_length": len(data),
        "scenario_result_id": _hash_config({"domain": "scenario-result-v1", "result": result}),
        "preregistration_id": None if synthetic else PREREG,
        "gate_d_record_sha256": None if synthetic else _digest(_private_file(gate_d_record)),
    }
    # Artifact is written before receipt. A crash between them leaves a conspicuous
    # orphan and refuses future reuse of this attempt; no silent repair/overwrite.
    _write_once(sealed, data)
    _write_once(receipt_file, (json.dumps(receipt, sort_keys=True, indent=2) + "\n").encode())
    return {"status": "SEALED_NO_DISCLOSURE", "profile": profile, "attempt": attempt,
            "result_sha256": sha, "source_kind": receipt["source_kind"]}


def _verified_seal(
    root: Path, profile: str, attempt: int
) -> tuple[dict[str, object], dict[str, object], bytes]:
    _check(profile in RUNS and attempt in (1, 2), "unknown profile/attempt")
    stem = f"{profile.lower()}-attempt-{attempt}"
    receipt = _json_file(root / "receipts" / f"{stem}.json")
    raw, manifest, result = _parse_result(root / "sealed" / f"{stem}.json")
    _check(receipt.get("schema") == "stage6-seal-receipt-v1" and
           receipt.get("profile") == profile and receipt.get("attempt") == attempt and
           receipt.get("result_sha256") == _digest(raw) and
           receipt.get("byte_length") == len(raw) and
           receipt.get("scenario_run_id") == result.get("scenario_run_id"),
           "sealed bytes or receipt modified")
    is_synthetic = receipt.get("source_kind") == "SYNTHETIC_TEST_ONLY"
    _validate_source(manifest, synthetic=is_synthetic)
    _check(receipt.get("source_kind") in ("SYNTHETIC_TEST_ONLY", "PROTECTED_GATE_D_APPROVED"),
           "unknown seal provenance")
    if not is_synthetic:
        _check(result.get("scenario_run_id") == RUNS[profile][0] and
               receipt.get("preregistration_id") == PREREG,
               "protected seal does not match frozen preregistration")
        _check(type(receipt.get("gate_d_record_sha256")) is str and
               len(receipt["gate_d_record_sha256"]) == 64,
               "missing Gate D acceptance fingerprint")
    return receipt, result, raw


def is_qa(*, root: Path, profile: str, attempt: int) -> dict[str, object]:
    """Publish an IS-only *methodological count*, never OOS or trade economics."""
    root = _private_directory(root)
    receipt, result, _ = _verified_seal(root, profile, attempt)
    report: dict[str, object] = {
        "schema": "stage6-is-qa-v1", "profile": profile, "attempt": attempt,
        "source_kind": receipt["source_kind"],
        "scenario_run_id": receipt["scenario_run_id"],
        "sealed_result_sha256": receipt["result_sha256"],
        "is_expected_5m": 69984, "is_observed_5m": result["is_observed"],
        "is_grid_complete": result["is_observed"] == 69984,
        "limitations": "IS_GRID_QA_ONLY_NO_PERFORMANCE_NO_OOS_RELEASE",
    }
    path = _subdir(root, "is-qa") / f"{profile.lower()}-attempt-{attempt}.json"
    _write_once(path, (json.dumps(report, sort_keys=True, indent=2) + "\n").encode())
    return {"status": "IS_QA_ONLY", "profile": profile, "attempt": attempt,
            "is_grid_complete": report["is_grid_complete"], "is_qa_sha256": _digest(_private_file(path))}


def release_oos(*, root: Path, profile: str, attempt: int, oos_record: Path | None) -> dict[str, object]:
    """Copy previously sealed full result after a separate operator-attested OOS decision."""
    root = _private_directory(root)
    _check(oos_record is not None, "explicit OOS owner decision required")
    receipt, _, verified_bytes = _verified_seal(root, profile, attempt)
    stem = f"{profile.lower()}-attempt-{attempt}"
    is_path = root / "is-qa" / f"{stem}.json"
    is_report = _json_file(is_path)
    is_sha = _digest(_private_file(is_path))
    _check(is_report.get("sealed_result_sha256") == receipt["result_sha256"] and
           is_report.get("scenario_run_id") == receipt["scenario_run_id"] and
           is_report.get("schema") == "stage6-is-qa-v1", "IS QA checkpoint incorrect")
    if receipt["source_kind"] == "SYNTHETIC_TEST_ONLY":
        _check_approval(oos_record, decision="SYNTHETIC_OOS_RELEASE_TEST",
                        extra={"seal_sha256": receipt["result_sha256"], "is_qa_sha256": is_sha})
    else:
        _check_approval(oos_record, decision="OOS_RELEASE_ACCEPT",
                        extra={"preregistration_id": PREREG, "seal_sha256": receipt["result_sha256"],
                               "is_qa_sha256": is_sha})
    destination = _subdir(root, "released") / f"{stem}.json"
    _check(not destination.exists(), "OOS release collision")
    # Never print the released content; operator controls the only full-result copy.
    # Release the *same* bytes whose digest and identity were checked above:
    # reopening the owner-writable seal would create a TOCTOU mutation window.
    _write_once(destination, verified_bytes)
    return {"status": "OOS_RELEASED_BY_OPERATOR_RECORD", "profile": profile,
            "attempt": attempt, "released_sha256": receipt["result_sha256"],
            "record_sha256": _digest(_private_file(oos_record)),
            "authority_note": "operator-attested decision; GitHub authenticity not verified by offline tool"}


def resource_check(*, root: Path, min_ram_gib: int, min_disk_gib: int) -> dict[str, object]:
    """Measure capacity only; full-run RAM/serialization feasibility remains unproven."""
    root = _private_directory(root)
    _check(min_ram_gib > 0 and min_disk_gib > 0, "resource thresholds must be positive")
    mem = Path("/proc/meminfo")
    _check(mem.is_file(), "resource check currently requires Linux MemAvailable")
    values = dict(line.split(":", 1) for line in mem.read_text().splitlines() if ":" in line)
    _check("MemAvailable" in values, "MemAvailable absent")
    ram_bytes = int(values["MemAvailable"].strip().split()[0]) * 1024
    disk_bytes = shutil.disk_usage(root).free
    return {
        "status": "CAPACITY_SNAPSHOT_ONLY_NOT_FULL_RUN_CERTIFIED",
        "available_ram_bytes": ram_bytes, "available_disk_bytes": disk_bytes,
        "min_ram_bytes": min_ram_gib * GIB, "min_disk_bytes": min_disk_gib * GIB,
        "meets_thresholds": ram_bytes >= min_ram_gib * GIB and disk_bytes >= min_disk_gib * GIB,
        "limits": "does not bound Python object graph, replay peaks, or JSON output size",
    }


def main(argv: list[str] | None = None) -> int:
    """Run an explicit offline custody subcommand, never a scenario runner."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True, help="private 0700 custody root outside Git")
    cmds = parser.add_subparsers(dest="command", required=True)
    sealing = cmds.add_parser("seal", help="seal existing canonical result, no performance evaluation")
    sealing.add_argument("--source-file", type=Path, required=True)
    sealing.add_argument("--profile", choices=tuple(RUNS), required=True)
    sealing.add_argument("--attempt", type=int, choices=(1, 2), required=True)
    sealing.add_argument("--synthetic-test-only", action="store_true")
    sealing.add_argument("--private-manifest", type=Path)
    sealing.add_argument("--gate-d-record", type=Path)
    for name in ("is-qa", "oos-release"):
        cmd = cmds.add_parser(name)
        cmd.add_argument("--profile", choices=tuple(RUNS), required=True)
        cmd.add_argument("--attempt", type=int, choices=(1, 2), required=True)
        if name == "oos-release":
            cmd.add_argument("--oos-record", type=Path, required=True)
    capacity = cmds.add_parser("resource-check", help="input-free RAM and disk snapshot")
    capacity.add_argument("--min-ram-gib", type=int, default=6)
    capacity.add_argument("--min-disk-gib", type=int, default=20)
    args = parser.parse_args(argv)
    try:
        if args.command == "seal":
            result = seal(root=args.root, source_file=args.source_file,
                          profile=args.profile, attempt=args.attempt,
                          synthetic=args.synthetic_test_only,
                          private_manifest=args.private_manifest, gate_d_record=args.gate_d_record)
        elif args.command == "is-qa":
            result = is_qa(root=args.root, profile=args.profile, attempt=args.attempt)
        elif args.command == "oos-release":
            result = release_oos(root=args.root, profile=args.profile,
                                 attempt=args.attempt, oos_record=args.oos_record)
        else:
            result = resource_check(root=args.root, min_ram_gib=args.min_ram_gib,
                                    min_disk_gib=args.min_disk_gib)
        print(json.dumps(result, sort_keys=True, indent=2))
        return 0 if result.get("meets_thresholds", True) else 2
    except (CustodyBlocked, OSError, ValueError, TypeError, KeyError, IndexError,
            json.JSONDecodeError) as exc:
        print("BLOCKED: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
