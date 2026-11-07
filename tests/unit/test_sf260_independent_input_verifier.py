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


def _private_json(path: Path, payload: object) -> None:
    """Write synthetic JSON as an operator-private byte fixture."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")
    path.chmod(0o600)


def _raw_archive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *,
    unequal_second_pass: bool = False, missing_minute: bool = False
) -> tuple[Path, str]:
    """Build two tiny artificial provider passes with real checksums/sidecars."""
    root = tmp_path / ".signalforge-data/sf088/evidence/evidence-only/generation-0001"
    root.mkdir(parents=True)
    monkeypatch.setattr(verifier, "SOURCE_MINUTES", 10)
    monkeypatch.setattr(verifier, "CHUNK_MINUTES", 5)
    monkeypatch.setattr(verifier, "EXPECTED_5M_CLOSES", 2)
    monkeypatch.setattr(verifier, "END", verifier.START + 600)
    first_sha: list[str] = []
    second_sha: list[str] = []
    first_sem: list[str] = []
    second_sem: list[str] = []
    for pass_no in (1, 2):
        for chunk in (0, 1):
            rows: list[dict[str, object]] = []
            for n in range(chunk * 5, (chunk + 1) * 5):
                stamp = verifier.START + 60 * n
                if missing_minute and pass_no == 1 and n == 3:
                    stamp += 60
                close = "1" if unequal_second_pass and pass_no == 2 and n == 9 else "2"
                rows.append({"time": stamp, "open": "1", "high": "2", "low": "1",
                             "close": close, "volume": "1"})
            payload = json.dumps({"success": True, "result": rows}, separators=(",", ":"))
            raw = payload.encode()
            sha = verifier.hashlib.sha256(raw).hexdigest()
            sem_rows = [{"time": row["time"], "open": "1", "high": "2", "low": "1",
                         "close": row["close"], "volume": "1"} for row in rows]
            sem = verifier.hashlib.sha256(json.dumps(sem_rows, sort_keys=True,
                separators=(",", ":"), ensure_ascii=True).encode("ascii")).hexdigest()
            prefix = root / f"pass-{pass_no}" / f"chunk-{chunk:06d}"
            prefix.parent.mkdir(parents=True, exist_ok=True)
            prefix.with_suffix(".json").write_bytes(raw)
            _private_json(prefix.with_suffix(".meta.json"), {
                "raw_sha256": sha, "semantic_sha256": sem,
                "acquired_at": "2026-11-01T21:54:15+00:00",
            })
            if pass_no == 1:
                first_sha.append(sha)
                first_sem.append(sem)
            else:
                second_sha.append(sha)
                second_sem.append(sem)
    report = {
        "first_pass_raw_sha256": first_sha, "second_pass_raw_sha256": second_sha,
        "first_pass_semantic_sha256": first_sem,
        "second_pass_semantic_sha256": second_sem,
    }
    report["report_sha256"] = verifier.hashlib.sha256(json.dumps(
        report, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode()).hexdigest()
    _private_json(root / "evidence-only-report.json", report)
    inventory = verifier.inventory(root)
    monkeypatch.setattr(verifier, "SOURCE_FILE_COUNT", inventory["file_count"])
    monkeypatch.setattr(verifier, "SOURCE_BYTES", inventory["total_bytes"])
    monkeypatch.setattr(verifier, "INVENTORY", inventory["inventory_sha256_v1"])
    old = verifier.hashlib.sha256()
    for n in (4, 9):
        t = verifier.START + n * 60
        old.update(f"{t-240}:2\n".encode("ascii"))
    monkeypatch.setattr(verifier, "OLD_5M", old.hexdigest())
    return root, verifier.config_hash({"close": [Decimal(2), Decimal(2)]})


def test_tiny_two_pass_source_verifies_without_scenario_runner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, digest = _raw_archive(tmp_path, monkeypatch)
    got = verifier.verify_raw_source(root, digest)
    assert got["two_pass_semantic_check"] == "PASS"
    assert got["source_inventory_check"] == "PASS"
    assert got["one_minute_candles"] == 10
    assert got["scenario_five_minute_close_digest"] == digest


def test_tiny_source_detects_missing_minute(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, digest = _raw_archive(tmp_path, monkeypatch, missing_minute=True)
    with pytest.raises(verifier.Blocked, match="source minute"):
        verifier.verify_raw_source(root, digest)


def test_tiny_source_detects_semantically_different_second_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, digest = _raw_archive(tmp_path, monkeypatch, unequal_second_pass=True)
    with pytest.raises(verifier.Blocked, match="two-pass semantic"):
        verifier.verify_raw_source(root, digest)


def test_tiny_source_detects_changed_chunk_raw_sha(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, digest = _raw_archive(tmp_path, monkeypatch)
    raw_path = root / "pass-1/chunk-000000.json"
    raw_path.write_bytes(raw_path.read_bytes() + b" ")
    latest = verifier.inventory(root)
    monkeypatch.setattr(verifier, "SOURCE_BYTES", latest["total_bytes"])
    monkeypatch.setattr(verifier, "INVENTORY", latest["inventory_sha256_v1"])
    with pytest.raises(verifier.Blocked, match="chunk raw content SHA"):
        verifier.verify_raw_source(root, digest)


def _synthetic_manifest_pair(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Construct two internally coherent but fully synthetic pre-run manifests."""
    root = tmp_path / "preflight"
    root.mkdir(mode=0o700)
    # The same structural checks run on fake input mappings; no provider data
    # or actual protected full-window performance is used in this test.
    mocked_dataset = "synthetic-dataset-digest"
    mocked_report = "synthetic-source-report"
    monkeypatch.setattr(verifier, "DATASET", mocked_dataset)
    monkeypatch.setattr(verifier, "PROVISIONAL", mocked_report)
    fake_close_digest = verifier.config_hash({"close": [Decimal("1"), Decimal("2")]})
    assumption = {"scenario_id": "BTC_OHLC_PATH_V1",
                  "scenario_version": "0.1.0-proposal"}
    for key, name in verifier.FROZEN_RULES.items():
        assumption[key] = {"id": name, "version": "1.0.0-proposal"}
    assumption_sha = verifier.config_hash(assumption)
    monkeypatch.setattr(verifier, "ASSUMPTIONS_HASH", assumption_sha)
    assumption["semantic_hash"] = assumption_sha
    resources = {"policy_id": "FINITE_FAIL_CLOSED", "version": "1.0.0",
                 "max_bars": verifier.MAX_BARS, "max_events": 2096640,
                 "max_outcomes": 104833, "max_trace_records": 2096640,
                 "max_states": 1, "exhaustion": "FAIL_CLOSED_UNRESOLVED"}
    resource_hash = verifier.config_hash(resources)
    monkeypatch.setattr(verifier, "RESOURCE_HASH", resource_hash)
    profiles: dict[str, tuple[str, str, str, str, Decimal]] = {}
    reported: list[dict[str, str]] = []
    prereg_run: list[list[str]] = []
    prereg_sha: list[list[str]] = []
    for profile, bps in (("REFERENCE_RAW", Decimal(0)), ("ADVERSE_RAW", Decimal(10))):
        fills: dict[str, object] = {
            "profile_id": profile, "version": "1.0.0",
            "price_mode": "raw_diagnostic", "tick_rule_version": "unresolved",
            "entry_slippage_bps": bps, "stop_slippage_bps": bps,
            "target_slippage_bps": bps, "forced_exit_slippage_bps": Decimal(0),
        }
        mapping: dict[str, object] = {
            "mode_and_schema": {"mode": "SCENARIO_RESEARCH", "schema": "scenario-manifest-v1",
                                "simulator": "btc-ohlc-path-scenario-v1"},
            "source": {"dataset_id": mocked_dataset, "content_hash": mocked_dataset,
                       "source_diagnostic_id": mocked_report,
                       "five_minute_close_digest": fake_close_digest,
                       "manifest": {"canonical_row_count": 525600,
                                    "provider": "delta_exchange_india",
                                    "acquisition_adapter": "sf095-protected-first-pass-read-only",
                                    "instrument_id": "DELTA:BTCUSD", "price_basis": "traded",
                                    "interval_minutes": 1}},
            "strategy": {"id": "btc_momentum_baseline_v0", "version": "0.1.0-experimental",
                         "config_id": verifier.CONFIG_HASH, "config_hash": verifier.CONFIG_HASH,
                         "engine_calculation_version": "engine-v1",
                         "synthetic_fixture_identity": None},
            "assumptions": assumption, "fills": fills,
            "session_and_window": {"session": {"id": "continuous_utc", "version": "1.0.0"},
                                   "pre_roll_start": "2025-10-30T00:00:00+00:00",
                                   "is_start": "2025-10-31T00:00:00+00:00",
                                   "oos_start": "2026-07-01T00:00:00+00:00",
                                   "measured_end": "2026-10-30T00:00:00+00:00",
                                   "bounds": "half-open UTC"},
            "resource_policy": resources, "resource_policy_semantic_hash": resource_hash,
            "implementation": {"revision": verifier.BASELINE,
                               "canonical_serializer": "canonical-config-json-v1",
                               "scenario_calculation_version": "btc-ohlc-path-scenario-v1"},
        }
        run_id = verifier.config_hash({"domain": "scenario-run-v1", "inputs": mapping})
        record = {"input_mapping": mapping, "scenario_run_id": run_id}
        raw = json.dumps(verifier.tagged(record), separators=(",", ":"),
                         ensure_ascii=False).encode() + b"\n"
        filename = profile.lower() + "-input-manifest.json"
        path = root / filename
        path.write_bytes(raw)
        path.chmod(0o600)
        sha = verifier.hashlib.sha256(raw).hexdigest()
        profiles[profile] = (filename, run_id, sha, verifier.config_hash(fills), bps)
        reported.append({"profile_id": profile, "run_id": run_id,
                         "manifest_file": filename, "canonical_manifest_sha256": sha})
        prereg_run.append([profile, run_id])
        prereg_sha.append([profile, sha])
    monkeypatch.setattr(verifier, "PROFILES", profiles)
    prereg = verifier.config_hash({"domain": "sf261-stage6-preflight-inputs-v1",
                                  "execution_revision": verifier.BASELINE,
                                  "profile_run_ids": prereg_run,
                                  "manifest_bytes_sha256": prereg_sha})
    monkeypatch.setattr(verifier, "PREREG", prereg)
    source_summary = {
        "dataset_id": mocked_dataset, "dataset_content_hash": mocked_dataset,
        "source_diagnostic_id": mocked_report, "provisional_report_sha256": mocked_report,
        "independent_audit_sha256": verifier.SOURCE_AUDIT,
        "original_five_minute_close_sha256": verifier.OLD_5M,
        "one_minute_count": 525600, "five_minute_count": 105120,
        "execution_valid": False, "historical_tick_applicability": "UNRESOLVED",
    }
    _private_json(root / "preflight-readiness.json", {
        "disposition": "PREPARATION_ONLY_GATE_D_WITHHELD",
        "gate_d_approved": False, "gate_d_ready": False, "execution_valid": False,
        "scenario_performance_executed_by_preflight": False,
        "baseline_execution_revision": verifier.BASELINE,
        "current_script_checkout": verifier.CHECKOUT,
        "input_preregistration_id": prereg,
        "source": source_summary,
        "protected_inventory_before_and_after": {
            "file_count": 1057, "total_bytes": 101674328,
            "inventory_sha256_v1": verifier.INVENTORY,
        },
        "profiles": reported,
    })
    return root


def test_synthetic_manifests_validate_and_reject_byte_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _synthetic_manifest_pair(tmp_path, monkeypatch)
    details, source_hash = verifier.verify_manifests(root)
    assert set(details) == {"REFERENCE_RAW", "ADVERSE_RAW"}
    assert len(source_hash) == 64
    altered = root / "adverse_raw-input-manifest.json"
    altered.write_bytes(altered.read_bytes() + b" ")
    with pytest.raises(verifier.Blocked, match="manifest file SHA"):
        verifier.verify_manifests(root)
