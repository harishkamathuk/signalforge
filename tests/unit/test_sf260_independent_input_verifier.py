"""Synthetic-only source-independent tests for repo-managed SF-260 verifier."""

from __future__ import annotations

import importlib.util
import json
import sys
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

PATH = Path(__file__).resolve().parents[2] / "scripts/sf260_independent_input_verifier.py"
SPEC = importlib.util.spec_from_file_location("sf260_independent_input_verifier", PATH)
assert SPEC is not None and SPEC.loader is not None
verifier = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = verifier
SPEC.loader.exec_module(verifier)


def test_canonical_codec_and_domain_hashes() -> None:
    value = {"x": [Decimal("1.200"), False, None, "v"], "y": -42}
    tagged = verifier.tagged(value)
    assert verifier.decode(json.loads(json.dumps(tagged))) == value
    assert verifier.config_hash({"domain": "a", "inputs": value}) != verifier.config_hash(
        {"domain": "b", "inputs": value}
    )


def test_duplicate_and_noncanonical_map_keys_blocked() -> None:
    with pytest.raises(verifier.Blocked, match="duplicate/unsorted"):
        verifier.decode(["map", [["x", ["int", "1"]], ["x", ["int", "2"]]]])
    with pytest.raises(verifier.Blocked):
        verifier.decode(["decimal", "1.200"])


def test_checkout_allows_future_unchanged_develop(monkeypatch: pytest.MonkeyPatch,
                                                      tmp_path: Path) -> None:
    def fake_run(args: list[str], **kwargs: object) -> SimpleNamespace:
        if "--is-ancestor" in args or "--quiet" in args:
            return SimpleNamespace(returncode=0, stdout="")
        op = args[3:]
        values = {
            ("rev-parse", "--show-toplevel"): str(tmp_path),
            ("symbolic-ref", "--short", "HEAD"): "develop",
            ("rev-parse", "HEAD"): "f" * 40,
            ("status", "--porcelain", "--untracked-files=normal"): "",
        }
        return SimpleNamespace(returncode=0, stdout=values[tuple(op)])

    monkeypatch.setattr(verifier.subprocess, "run", fake_run)
    assert verifier.verify_checkout(tmp_path) == "f" * 40


def test_checkout_rejects_frozen_calculation_drift(monkeypatch: pytest.MonkeyPatch,
                                                    tmp_path: Path) -> None:
    def fake_run(args: list[str], **kwargs: object) -> SimpleNamespace:
        if "--quiet" in args:
            return SimpleNamespace(returncode=1, stdout="")
        if "--is-ancestor" in args:
            return SimpleNamespace(returncode=0, stdout="")
        op = args[3:]
        values = {
            ("rev-parse", "--show-toplevel"): str(tmp_path),
            ("symbolic-ref", "--short", "HEAD"): "develop",
            ("rev-parse", "HEAD"): "f" * 40,
            ("status", "--porcelain", "--untracked-files=normal"): "",
        }
        return SimpleNamespace(returncode=0, stdout=values[tuple(op)])

    monkeypatch.setattr(verifier.subprocess, "run", fake_run)
    with pytest.raises(verifier.Blocked, match="frozen execution/contract"):
        verifier.verify_checkout(tmp_path)


def test_no_scenario_runner_import_or_execution() -> None:
    code = PATH.read_text()
    assert "ScenarioResearchRunner" not in code
    assert "import signalforge" not in code
    assert "from signalforge" not in code
