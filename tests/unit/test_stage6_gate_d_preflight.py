"""Negative and synthetic-only tests for the SF-261 Stage 6 preflight."""

from __future__ import annotations

import ast
import json
import stat
from pathlib import Path

import pytest

from scripts import stage6_gate_d_preflight as preflight


def _private(path: Path) -> Path:
    path.mkdir(parents=True, mode=0o700)
    path.chmod(0o700)
    return path


def _generation(tmp_path: Path) -> Path:
    return _private(
        tmp_path / ".signalforge-data" / "sf088" / "evidence"
        / "evidence-only" / "generation-0001"
    )


def _manifests() -> list[tuple[str, str, str, str]]:
    return [
        ("REFERENCE_RAW", "reference-run", "reference-payload\n", "reference-hash"),
        ("ADVERSE_RAW", "adverse-run", "adverse-payload\n", "adverse-hash"),
    ]


def test_protected_path_must_be_original_generation(tmp_path: Path) -> None:
    source = _generation(tmp_path)
    assert preflight._protected_root(source) == source.resolve()
    with pytest.raises(preflight.PreflightError, match="exact protected"):
        preflight._protected_root(_private(tmp_path / "fixture"))
    alias = tmp_path / "archive-alias"
    alias.symlink_to(source, target_is_directory=True)
    with pytest.raises(preflight.PreflightError, match="symlink"):
        preflight._protected_root(alias)


def test_protected_directory_rejects_symlink_ancestor(tmp_path: Path) -> None:
    source = _generation(tmp_path)
    shortcut = tmp_path / "shortcut"
    shortcut.symlink_to(source.parent, target_is_directory=True)
    with pytest.raises(preflight.PreflightError, match="symlink ancestor"):
        preflight._protected_root(shortcut / "generation-0001")


def test_inventory_is_deterministic_and_detects_mutation(tmp_path: Path) -> None:
    source = _generation(tmp_path)
    (source / "pass-1").mkdir()
    first = source / "pass-1" / "chunk-000000.json"
    first.write_bytes(b"first")
    (source / "evidence-only-report.json").write_bytes(b"report")
    original = preflight.inventory(source)
    assert original == preflight.inventory(source)
    assert original["file_count"] == 2
    assert original["total_bytes"] == 11
    first.write_bytes(b"edited")
    assert preflight.inventory(source)["inventory_sha256_v1"] != original["inventory_sha256_v1"]


def test_inventory_rejects_symlink_and_nonregular_content(tmp_path: Path) -> None:
    source = _generation(tmp_path)
    item = source / "real.json"
    item.write_text("safe")
    (source / "alias.json").symlink_to(item)
    with pytest.raises(preflight.PreflightError, match="symlink"):
        preflight.inventory(source)


def test_output_must_be_private_outside_repository(tmp_path: Path) -> None:
    repo = _private(tmp_path / "repo")
    good = _private(tmp_path / "private-results")
    assert preflight._output_dir(good, repo) == good
    with pytest.raises(preflight.PreflightError, match="outside Git"):
        preflight._output_dir(_private(repo / "results"), repo)
    with pytest.raises(preflight.PreflightError, match="protected"):
        preflight._output_dir(_private(tmp_path / "sf096" / "results"), repo)
    public = _private(tmp_path / "public")
    public.chmod(0o755)
    with pytest.raises(preflight.PreflightError, match="private"):
        preflight._output_dir(public, repo)
    alias = tmp_path / "alias-results"
    alias.symlink_to(good, target_is_directory=True)
    with pytest.raises(preflight.PreflightError, match="symlink"):
        preflight._output_dir(alias, repo)


def test_output_is_exclusive_and_private(tmp_path: Path) -> None:
    path = _private(tmp_path / "results") / "manifest.json"
    preflight._exclusive_json(path, "one\n")
    assert path.read_text() == "one\n"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    with pytest.raises(FileExistsError):
        preflight._exclusive_json(path, "two\n")
    assert path.read_text() == "one\n"


def test_symlink_output_cannot_replace_existing_evidence(tmp_path: Path) -> None:
    folder = _private(tmp_path / "results")
    protected = folder / "existing.json"
    protected.write_text("protected\n")
    alias = folder / "manifest.json"
    alias.symlink_to(protected)
    with pytest.raises(FileExistsError):
        preflight._exclusive_json(alias, "new\n")
    assert protected.read_text() == "protected\n"


def test_revision_rejects_dirty_or_changed_execution_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _private(tmp_path / "repo")
    head = "c" * 40

    def fake_git(_root: Path, *args: str) -> str:
        if args[:2] == ("rev-parse", "--show-toplevel"):
            return str(repo.resolve())
        if args[:2] == ("symbolic-ref", "--short"):
            return "develop"
        if args[:2] == ("status", "--porcelain"):
            return " M signalforge/research/scenario_execution.py"
        if args[:2] == ("rev-parse", "HEAD"):
            return head
        return ""

    monkeypatch.setattr(preflight, "_git", fake_git)
    with pytest.raises(preflight.PreflightError, match="not clean"):
        preflight.verify_revision(repo)

    def changed_git(_root: Path, *args: str) -> str:
        if args[:2] == ("status", "--porcelain"):
            return ""
        if args[:2] == ("diff", "--name-only"):
            return "signalforge/research/scenario_execution.py"
        return fake_git(_root, *args)

    monkeypatch.setattr(preflight, "_git", changed_git)
    with pytest.raises(preflight.PreflightError, match="frozen Gate C"):
        preflight.verify_revision(repo)


def test_write_packet_retains_gate_d_withheld_and_no_metric_fields(tmp_path: Path) -> None:
    folder = _private(tmp_path / "results")
    preflight.write_packet(
        folder,
        {"dataset_content_hash": "synthetic-test-only"},
        {"file_count": 2, "inventory_sha256_v1": "synthetic"},
        _manifests(), "prereg-test", preflight.BASELINE_SHA,
    )
    summary = json.loads((folder / "preflight-readiness.json").read_text())
    assert summary["gate_d_ready"] is False
    assert summary["gate_d_approved"] is False
    assert summary["execution_valid"] is False
    assert summary["scenario_performance_executed_by_preflight"] is False
    assert summary["custody_and_oos_quarantine_independent_review"] == "PENDING"
    assert "metrics" not in summary
    assert "outcomes" not in summary
    assert (folder / "reference_raw-input-manifest.json").read_text() == "reference-payload\n"
    assert (folder / "adverse_raw-input-manifest.json").read_text() == "adverse-payload\n"
    assert all(
        stat.S_IMODE(path.stat().st_mode) == 0o600 for path in folder.iterdir()
    )


def test_existing_output_prevents_partial_overwrite(tmp_path: Path) -> None:
    folder = _private(tmp_path / "results")
    preexisting = folder / "adverse_raw-input-manifest.json"
    preexisting.write_text("original")
    with pytest.raises(preflight.PreflightError, match="already exists"):
        preflight.write_packet(folder, {}, {}, _manifests(), "prereg", preflight.BASELINE_SHA)
    assert preexisting.read_text() == "original"
    assert not (folder / "reference_raw-input-manifest.json").exists()


def test_execute_fails_before_manifest_if_source_inventory_is_wrong(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _private(tmp_path / "repo")
    generation = _generation(tmp_path)
    output = _private(tmp_path / "results")
    monkeypatch.setattr(preflight, "verify_revision", lambda _: preflight.BASELINE_SHA)
    monkeypatch.setattr(preflight, "inventory", lambda _: {
        "file_count": 999, "total_bytes": preflight.EXPECTED_SOURCE_BYTES,
    })

    def impossible(*_args: object) -> None:
        raise AssertionError("must not enter manifest/source processing on inventory failure")

    monkeypatch.setattr(preflight, "verify_source", impossible)
    with pytest.raises(preflight.PreflightError, match="inventory count"):
        preflight.execute(repo, generation, output)
    assert list(output.iterdir()) == []


def test_script_does_not_import_or_invoke_scenario_runner() -> None:
    root = Path(preflight.__file__)
    parsed = ast.parse(root.read_text(encoding="utf-8"))
    imports = [
        node for node in ast.walk(parsed) if isinstance(node, ast.ImportFrom)
    ]
    for module in imports:
        if module.module == "signalforge.research.scenario_execution":
            assert "ScenarioResearchRunner" not in {name.name for name in module.names}
    calls = [node for node in ast.walk(parsed) if isinstance(node, ast.Call)]
    assert not any(
        isinstance(call.func, ast.Attribute)
        and call.func.attr in {"run_verified", "evaluate_completed_candle"}
        for call in calls
    )
