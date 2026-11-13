"""B2-90D-R01: independent verification must defeat self-consistent forged inputs.

All bytes and hashes in these tests are synthetic. No SF-088 archive, protected
scenario or economic metrics are accessed. Neither production run identity nor
the producer's canonical mapping algorithm is modified.
"""

from __future__ import annotations

import copy
import hashlib
from typing import Any

import pytest

from scripts import stage6_90d_independent_verifier as independent
from signalforge.config.identity import canonical_config_json, config_hash
from signalforge.research.historical_execution import HistoricalExecutionAssumptionProfile
from signalforge.research.scenario_execution import (
    ScenarioAssumptionSet,
    ScenarioResourcePolicy,
)

REVISION = "a" * 40


def _receipt_sha(value: dict[str, Any]) -> str:
    encoded = (canonical_config_json(value) + "\n").encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _synthetic_prereg(
    mutate: tuple[str, str, object] | None = None,
) -> tuple[dict[str, Any], dict[str, tuple[dict[str, Any], str]], dict[str, object]]:
    """Fully recompute every outer identity after an optional forged change."""
    child_manifest = {"synthetic_child_grid": "approved", "rows": 131040}
    lineage: dict[str, object] = {
        "child_manifest": child_manifest,
        "child_dataset_hash": "c" * 64,
        "derived_five_minute_close_digest": "d" * 64,
    }
    derived_id = config_hash(lineage)
    assumptions = ScenarioAssumptionSet.btc_ohlc_path_v1()
    resources = ScenarioResourcePolicy(
        "FINITE_FAIL_CLOSED", "1.0.0", 524160, 2096640, 104833, 2096640, 1,
    )
    mappings: dict[str, tuple[dict[str, Any], str]] = {}
    profile_rows = []
    for profile_name, profile in (
        ("REFERENCE_RAW", HistoricalExecutionAssumptionProfile.reference_raw()),
        ("ADVERSE_RAW", HistoricalExecutionAssumptionProfile.adverse_raw()),
    ):
        mapping: dict[str, Any] = {
            "mode_and_schema": {
                "mode": "SCENARIO_RESEARCH",
                "schema": "scenario-manifest-v1",
                "simulator": "btc-ohlc-path-scenario-v1",
                "study_variant": "SF260_90D_AUDITED_V1",
                "sample_status": "REPEATED_SAMPLE",
                "window_selection": "EARLIEST_90_MEASURED_UTC_DAYS",
            },
            "source": {
                "manifest": copy.deepcopy(child_manifest),
                "dataset_id": "c" * 64,
                "content_hash": "c" * 64,
                "source_diagnostic_id": derived_id,
                "audited_slice_lineage": copy.deepcopy(lineage),
                "five_minute_close_digest": "d" * 64,
            },
            "session_and_window": {
                "pre_roll_start": independent.SOURCE_START.isoformat(),
                "is_start": independent.IS_START.isoformat(),
                "oos_start": independent.OOS_START.isoformat(),
                "measured_end": independent.MEASURED_END.isoformat(),
            },
            "strategy": {
                "id": "btc_momentum_baseline_v0",
                "version": "0.1.0-experimental",
                "config_id": independent.CONFIG_HASH,
                "config_hash": independent.CONFIG_HASH,
                "engine_calculation_version": "engine-v1",
                "synthetic_fixture_identity": None,
            },
            "assumptions": {
                **assumptions.mapping(),
                "semantic_hash": assumptions.semantic_hash,
            },
            "fills": profile.semantic_mapping(),
            "implementation": {
                "revision": REVISION,
                "canonical_serializer": "canonical-config-json-v1",
                "scenario_calculation_version": "btc-ohlc-path-scenario-v1",
            },
            "resource_policy": resources.mapping(),
            "resource_policy_semantic_hash": config_hash(resources.mapping()),
        }
        if mutate is not None and profile_name == "REFERENCE_RAW":
            section, key, value = mutate
            mapping[section][key] = value
        run_id = config_hash({"domain": "scenario-run-v1", "inputs": mapping})
        record = {"input_mapping": mapping, "scenario_run_id": run_id}
        digest = _receipt_sha(record)
        filename = f"{profile_name.lower()}-manifest.json"
        mappings[filename] = (record, digest)
        profile_rows.append([profile_name, run_id, digest])
    prereg_id = config_hash({
        "domain": "sf260-90d-source-only-prereg-v1",
        "revision": REVISION,
        "slice_derivation_id": derived_id,
        "profiles": profile_rows,
    })
    readiness: dict[str, Any] = {
        "contract": "sf260-90d-source-only-prereg-v1",
        "disposition": "PREPARATION_ONLY_GATE_D_WITHHELD",
        "gate_d_approved": False,
        "protected_scenario_executed": False,
        "execution_valid": False,
        "revision": REVISION,
        "source_lineage": lineage,
        "derivation_id": derived_id,
        "input_preregistration_id": prereg_id,
        "profiles": [
            {
                "profile": row[0],
                "run_id": row[1],
                "filename": f"{row[0].lower()}-manifest.json",
                "canonical_sha256": row[2],
            }
            for row in profile_rows
        ],
    }
    mappings["source-only-readiness.json"] = (readiness, _receipt_sha(readiness))
    return readiness, mappings, lineage


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (("source", "manifest", {"synthetic_child_grid": "altered", "rows": 131040}),
         "source manifest differs"),
        (("source", "manifest", {"synthetic_child_grid": "approved", "rows": 131040,
                                 "extra": "forged"}),
         "source manifest differs"),
        (("mode_and_schema", "mode", "STRICT_EXECUTION"), "manifest mode differs"),
        (("mode_and_schema", "simulator", "alternative-simulator"), "manifest mode differs"),
        (("mode_and_schema", "extra", "unexpected"), "manifest mode differs"),
    ],
)
def test_forged_self_consistent_prereg_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
    mutation: tuple[str, str, object],
    message: str,
) -> None:
    _run_synthetic_verify(monkeypatch, tmp_path, mutation, message)


def _run_synthetic_verify(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
    mutation: tuple[str, str, object] | None,
    failure: str | None,
) -> None:
    _, records, lineage = _synthetic_prereg(mutation)
    tmp_path.chmod(0o700)
    monkeypatch.setattr(independent, "PRIVATE", tmp_path)
    monkeypatch.setattr(independent, "require_limits", lambda: None)
    monkeypatch.setattr(independent, "git_revision", lambda: REVISION)
    monkeypatch.setattr(
        independent,
        "independently_verified_lineage",
        lambda: (lineage, config_hash(lineage)),
    )

    def read_fake(path: Any) -> tuple[dict[str, Any], str]:
        return records[path.name]

    monkeypatch.setattr(independent, "read_canonical", read_fake)
    if failure:
        with pytest.raises(independent.VerificationBlocked, match=failure):
            independent.verify_source_only()
    else:
        result = independent.verify_source_only()
        assert result["status"] == "SOURCE_ONLY_INDEPENDENTLY_VERIFIED_NO_GATE_D"
        assert result["protected_scenario_executed"] is False


def test_unmodified_synthetic_canonical_prereg_is_accepted(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
) -> None:
    _run_synthetic_verify(monkeypatch, tmp_path, None, None)
