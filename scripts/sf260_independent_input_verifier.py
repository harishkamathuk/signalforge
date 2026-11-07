# ruff: noqa: E501
"""SF-260 independent, read-only Gate D *input* verifier (no scenario performance).

Standard library only; no SignalForge imports, network calls, runner methods, result
artifacts, or writes. Operate on the original protected SF-088 evidence and two
private manifests. This is a second algorithmic pass under solo-operator control,
NOT independent human custody/review.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import stat
import subprocess
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

BASELINE = "5d2812d11f8f5f061a1b637726f9e73b488c6e43"
CHECKOUT = "458ead333e29e51b073c1655acbea5d077d650aa"
PREREG = "9f55f96b47d2f83c8231595769ad0e3aaede6ef17a599e68f6ea115d1d8252c2"
DATASET = "85d89887078504385a5023eaba007ffcdeeb7f4c67689c79cd5db9a407c999f9"
PROVISIONAL = "8632150c1aa75689cb9b3fd933dc3e3d0672ce7eb31c1772b9597d7ce57b7ff6"
SOURCE_AUDIT = "cecc741b67e394e93fa73d578c6c710a806c46b8a26712830d508048de8269e7"
OLD_5M = "0787429a8203913b08b954c40d8dc57a0bad0be4b367a7d39580cdaf311733b8"
INVENTORY = "a39b3f970d4fba35d7ad456d466f1a00f34f0b0e7ead858c65ddffa23a18b802"
CONFIG_HASH = "88e90c23cd635248385d820406ef2201badc59bfd9f99043a63e8823227de242"
ASSUMPTIONS_HASH = "b7d89c3bcdfda94eb7b489ff12c03ab313573445bbf558fa4d10ce58ff081dc6"
RESOURCE_HASH = "28ecfb2d956a60ffbc33d334aeb379fcbabe61e056e3e254112ec34b0310c9d6"
PROFILES = {
    "REFERENCE_RAW": ("reference_raw-input-manifest.json", "84ac178645c49c0d53ff22c676cb36243ed340945019d46cea878acbe0825099", "6c9f388e1732110177108489350a49c8d8028e7507f3f69e516630d1b7f1a22f", "617e9e7698cc563c014e2b37699f704d863e7ae83a7bc5341ba2631f81574905", Decimal(0)),
    "ADVERSE_RAW": ("adverse_raw-input-manifest.json", "75cea6ced58247ad86adc4d16a9a41e02d442274e733b6a957a761b682f30dcf", "5ed7494f7faafb52e71935f27f062fc595f93f5e89fb83256068e0c18d518ff8", "2461fb0042083d97cdac511312ade824990f7965c68bc34f726fdf4a80bba875", Decimal(10)),
}
FROZEN_RULES = {
    "price_path_rule": "OPEN_HIGH_LOW_CLOSE",
    "event_tie_policy": "REJECT_SAME_LEVEL_TIE_V1",
    "gap_policy": "OBSERVED_OPEN_FIRST_V1",
    "time_boundary_policy": "FIVE_MINUTE_EXPIRY_AFTER_FINAL_CLOSE_V1",
    "fill_application_policy": "RAW_PROFILE_AFTER_BASE_V1",
}
MAX_BARS = 524160
START = int(datetime(2025, 10, 30, tzinfo=UTC).timestamp())
END = int(datetime(2026, 10, 30, tzinfo=UTC).timestamp())


class Blocked(ValueError):
    """Fail closed before any execution or approval evidence is emitted."""


def require(check: bool, reason: str) -> None:
    if not check:
        raise Blocked(reason)


def decimal_text(x: Decimal) -> str:
    require(x.is_finite(), "nonfinite decimal")
    n = x.normalize()
    return "0" if n == 0 else format(n, "f")


def tagged(value: object) -> object:
    """Separate canonical encoder, not imported from SignalForge."""
    if value is None:
        return ["null"]
    if isinstance(value, bool):
        return ["bool", value]
    if isinstance(value, int):
        return ["int", str(value)]
    if isinstance(value, str):
        return ["str", value]
    if isinstance(value, Decimal):
        return ["decimal", decimal_text(value)]
    if isinstance(value, dict):
        require(all(isinstance(k, str) for k in value), "non-string mapping key")
        return ["map", [[k, tagged(v)] for k, v in sorted(value.items())]]
    if isinstance(value, (list, tuple)):
        return ["list", [tagged(v) for v in value]]
    raise Blocked("unsupported identity type")


def config_hash(value: dict[str, object]) -> str:
    payload = json.dumps(tagged(value), separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def decode(node: object) -> object:
    """Decode type-tagged data with strict structure and duplicate-key guards."""
    require(isinstance(node, list) and node and isinstance(node[0], str), "invalid tagged node")
    typ = node[0]
    if typ == "null":
        require(len(node) == 1, "invalid null")
        return None
    require(len(node) == 2, "invalid typed length")
    v = node[1]
    if typ == "bool":
        require(type(v) is bool, "invalid bool")
        return v
    if typ == "str":
        require(type(v) is str, "invalid string")
        return v
    if typ == "int":
        require(type(v) is str and str(int(v)) == v, "invalid integer")
        return int(v)
    if typ == "decimal":
        require(type(v) is str and decimal_text(Decimal(v)) == v, "invalid decimal")
        return Decimal(v)
    if typ == "list":
        require(isinstance(v, list), "invalid list")
        return [decode(item) for item in v]
    if typ == "map":
        require(isinstance(v, list), "invalid map")
        out: dict[str, object] = {}
        prev: str | None = None
        for pair in v:
            require(isinstance(pair, list) and len(pair) == 2 and isinstance(pair[0], str),
                    "invalid map entry")
            key = pair[0]
            require(prev is None or key > prev, "duplicate/unsorted map key")
            out[key] = decode(pair[1])
            prev = key
        return out
    raise Blocked("unknown canonical type tag")


def read_json(path: Path) -> object:
    require(path.is_file() and not path.is_symlink(), "missing or symlinked private input")
    return json.loads(path.read_bytes(), parse_float=Decimal)


def as_map(x: object, reason: str) -> dict[str, object]:
    require(isinstance(x, dict), reason)
    return x


def private_dir(path: Path) -> Path:
    require(not path.is_symlink(), "private directory is a symlink")
    root = path.resolve(strict=True)
    require(root == path.absolute() and root.is_dir(), "private directory has symlink ancestors")
    require(root.stat().st_mode & 0o077 == 0, "private directory not restricted to owner")
    return root


def verify_manifests(directory: Path) -> tuple[dict[str, object], str]:
    readiness_path = directory / "preflight-readiness.json"
    readiness = as_map(read_json(readiness_path), "invalid readiness report")
    require(readiness.get("disposition") == "PREPARATION_ONLY_GATE_D_WITHHELD", "wrong disposition")
    require(readiness.get("gate_d_approved") is False and readiness.get("gate_d_ready") is False,
            "readiness prematurely asserts approval")
    require(readiness.get("execution_valid") is False and readiness.get("scenario_performance_executed_by_preflight") is False,
            "readiness asserts historical execution")
    require(readiness.get("baseline_execution_revision") == BASELINE and readiness.get("current_script_checkout") == CHECKOUT,
            "unexpected code revision")
    require(readiness.get("input_preregistration_id") == PREREG, "wrong preregistration")
    source = as_map(readiness.get("source"), "missing source report")
    for key, expected in (("dataset_id", DATASET), ("dataset_content_hash", DATASET),
                          ("source_diagnostic_id", PROVISIONAL), ("provisional_report_sha256", PROVISIONAL),
                          ("independent_audit_sha256", SOURCE_AUDIT), ("original_five_minute_close_sha256", OLD_5M)):
        require(source.get(key) == expected, "source report identity: " + key)
    require(source.get("one_minute_count") == 525600 and source.get("five_minute_count") == 105120,
            "wrong source grid")
    require(source.get("execution_valid") is False and source.get("historical_tick_applicability") == "UNRESOLVED",
            "invalid source qualification")
    inv = as_map(readiness.get("protected_inventory_before_and_after"), "missing inventory")
    require(inv.get("file_count") == 1057 and inv.get("total_bytes") == 101674328
            and inv.get("inventory_sha256_v1") == INVENTORY, "inventory identity drift")
    recorded_profiles = readiness.get("profiles")
    require(isinstance(recorded_profiles, list) and len(recorded_profiles) == 2,
            "wrong profile report count")
    prereg_runs: list[list[str]] = []
    prereg_sha: list[list[str]] = []
    details: dict[str, object] = {}
    source_dependent_digests: set[str] = set()
    for i, (profile, (filename, expected_run, expected_file_sha, expected_profile_sha, bps)) in enumerate(PROFILES.items()):
        row = as_map(recorded_profiles[i], "bad profile readiness row")
        require((row.get("profile_id"), row.get("run_id"), row.get("manifest_file"), row.get("canonical_manifest_sha256"))
                == (profile, expected_run, filename, expected_file_sha), "profile report differs")
        path = directory / filename
        require(path.is_file() and not path.is_symlink(), "missing/symlinked manifest")
        require(path.stat().st_mode & 0o077 == 0, "manifest not private")
        raw = path.read_bytes()
        file_sha = hashlib.sha256(raw).hexdigest()
        require(file_sha == expected_file_sha, "manifest file SHA-256 mismatch: " + profile)
        record = as_map(decode(json.loads(raw)), "invalid canonical manifest root")
        require(set(record) == {"input_mapping", "scenario_run_id"}, "manifest unexpected extra fields")
        mapping = as_map(record["input_mapping"], "invalid input mapping")
        run_id = config_hash({"domain": "scenario-run-v1", "inputs": mapping})
        require(run_id == expected_run == record["scenario_run_id"], "domain-separated run ID drift")
        canonical = json.dumps(tagged(record), separators=(",", ":"), ensure_ascii=False).encode() + b"\n"
        require(canonical == raw, "manifest bytes not canonical")
        require(set(mapping) == {"mode_and_schema", "source", "strategy", "assumptions", "fills", "session_and_window", "resource_policy", "resource_policy_semantic_hash", "implementation"},
                "manifest input mapping has wrong keys")
        mode = as_map(mapping["mode_and_schema"], "invalid mode")
        require(mode == {"mode": "SCENARIO_RESEARCH", "schema": "scenario-manifest-v1", "simulator": "btc-ohlc-path-scenario-v1"}, "mode changed")
        ss = as_map(mapping["source"], "invalid manifest source")
        require(ss.get("dataset_id") == DATASET and ss.get("content_hash") == DATASET and ss.get("source_diagnostic_id") == PROVISIONAL,
                "source manifest identity differs")
        require(isinstance(ss.get("manifest"), dict), "missing actual source semantic manifest")
        source_manifest = as_map(ss["manifest"], "source semantic manifest invalid")
        require(source_manifest.get("canonical_row_count") == 525600 and
                source_manifest.get("provider") == "delta_exchange_india" and
                source_manifest.get("acquisition_adapter") == "sf095-protected-first-pass-read-only" and
                source_manifest.get("instrument_id") == "DELTA:BTCUSD" and
                source_manifest.get("price_basis") == "traded" and
                source_manifest.get("interval_minutes") == 1,
                "source semantic mapping identity/row count drift")
        require("acquired_at" not in source_manifest, "unexpected acquired-at manifest semantics")
        # Repository HistoricalDatasetManifest.semantic_mapping() expressly EXCLUDES
        # operational acquired_at; it must be separately attested, not invented
        # as an input run-ID field.
        five_digest = ss.get("five_minute_close_digest")
        require(isinstance(five_digest, str) and len(five_digest) == 64, "missing source-dependent digest")
        source_dependent_digests.add(five_digest)
        strategy = as_map(mapping["strategy"], "missing strategy")
        require(strategy.get("id") == "btc_momentum_baseline_v0" and strategy.get("version") == "0.1.0-experimental"
                and strategy.get("config_id") == CONFIG_HASH and strategy.get("config_hash") == CONFIG_HASH
                and strategy.get("engine_calculation_version") == "engine-v1" and strategy.get("synthetic_fixture_identity") is None,
                "strategy identity changed")
        assumptions = as_map(mapping["assumptions"], "missing assumption set")
        require(assumptions.get("scenario_id") == "BTC_OHLC_PATH_V1" and assumptions.get("scenario_version") == "0.1.0-proposal"
                and assumptions.get("semantic_hash") == ASSUMPTIONS_HASH,
                "scenario identity changed")
        for key, expected in FROZEN_RULES.items():
            require(assumptions.get(key) == {"id": expected, "version": "1.0.0-proposal"},
                    "scenario policy changed: " + key)
        require(config_hash({k: v for k, v in assumptions.items() if k != "semantic_hash"}) == ASSUMPTIONS_HASH,
                "scenario semantic preimage mismatch")
        fills = as_map(mapping["fills"], "missing fill profile")
        require(config_hash(fills) == expected_profile_sha, "profile hash mismatch")
        require(fills.get("profile_id") == profile and fills.get("version") == "1.0.0"
                and fills.get("price_mode") == "raw_diagnostic" and fills.get("tick_rule_version") == "unresolved",
                "fill identity changed")
        require(all(fills.get(k) == bps for k in ("entry_slippage_bps", "stop_slippage_bps", "target_slippage_bps"))
                and fills.get("forced_exit_slippage_bps") == Decimal(0), "RAW slippage changed")
        policy = as_map(mapping["resource_policy"], "invalid budget")
        require(config_hash(policy) == RESOURCE_HASH == mapping.get("resource_policy_semantic_hash"),
                "budget semantic hash drift")
        require(policy == {"policy_id": "FINITE_FAIL_CLOSED", "version": "1.0.0", "max_bars": MAX_BARS,
                           "max_events": 2096640, "max_outcomes": 104833, "max_trace_records": 2096640,
                           "max_states": 1, "exhaustion": "FAIL_CLOSED_UNRESOLVED"}, "budget changed")
        session = as_map(mapping["session_and_window"], "invalid session and window")
        require(session.get("session") == {"id": "continuous_utc", "version": "1.0.0"} and
                session.get("pre_roll_start") == "2025-10-30T00:00:00+00:00" and
                session.get("is_start") == "2025-10-31T00:00:00+00:00" and
                session.get("oos_start") == "2026-07-01T00:00:00+00:00" and
                session.get("measured_end") == "2026-10-30T00:00:00+00:00" and
                session.get("bounds") == "half-open UTC", "frozen windows differ")
        impl = as_map(mapping["implementation"], "invalid implementation")
        require(impl == {"revision": BASELINE, "canonical_serializer": "canonical-config-json-v1",
                         "scenario_calculation_version": "btc-ohlc-path-scenario-v1"},
                "implementation identity drift")
        prereg_runs.append([profile, run_id]); prereg_sha.append([profile, file_sha])
        details[profile] = {"run_id": run_id, "manifest_sha256": file_sha,
                            "profile_semantic_sha256": expected_profile_sha}
    require(len(source_dependent_digests) == 1, "source-dependent digest differs between profiles")
    candidate = config_hash({"domain": "sf261-stage6-preflight-inputs-v1", "execution_revision": BASELINE,
                             "profile_run_ids": prereg_runs, "manifest_bytes_sha256": prereg_sha})
    require(candidate == PREREG, "independent prereg hash mismatch")
    return details, source_dependent_digests.pop()


def hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1_048_576), b""):
            h.update(block)
    return h.hexdigest()


def inventory(root: Path) -> dict[str, object]:
    h = hashlib.sha256()
    count = size = 0
    for file in sorted(root.rglob("*")):
        mode = file.lstat().st_mode
        require(not stat.S_ISLNK(mode), "protected archive contains symlink")
        if stat.S_ISDIR(mode):
            continue
        require(stat.S_ISREG(mode), "protected archive has nonregular file")
        n = file.stat().st_size
        row = [file.relative_to(root).as_posix(), n, hash_file(file)]
        h.update(json.dumps(row, separators=(",", ":"), ensure_ascii=True).encode() + b"\n")
        count += 1; size += n
    return {"file_count": count, "total_bytes": size, "inventory_sha256_v1": h.hexdigest()}


def verify_raw_source(root: Path, expected_close_digest: str) -> dict[str, object]:
    """Second-parser independent raw OHLC *source* verification; no trading metrics."""
    require(root.name == "generation-0001" and tuple(root.parts[-5:]) ==
            (".signalforge-data", "sf088", "evidence", "evidence-only", "generation-0001"),
            "wrong protected SF-088 archive path")
    require(root.absolute() == root.resolve(strict=True), "symlink in source ancestors")
    before = inventory(root)
    require(before == {"file_count": 1057, "total_bytes": 101674328,
                       "inventory_sha256_v1": INVENTORY}, "source inventory differs from frozen")
    report = as_map(read_json(root / "evidence-only-report.json"), "source report invalid")
    report_identity = hashlib.sha256(json.dumps({k: v for k, v in report.items() if k != "report_sha256"},
                   sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()
    require(report.get("report_sha256") == report_identity, "source acquisition report self-hash mismatch")
    chunk_count = (525600 + 1999) // 2000
    five_minute_closes: list[Decimal] = []
    old_sha = hashlib.sha256()
    pass_semantics: list[list[str]] = []
    first_acquired_at: str | None = None
    for pass_no in (1, 2):
        chunk_sha: list[str] = []
        seen = 0
        for i in range(chunk_count):
            rawpath = root / f"pass-{pass_no}" / f"chunk-{i:06d}.json"
            metapath = root / f"pass-{pass_no}" / f"chunk-{i:06d}.meta.json"
            meta = as_map(read_json(metapath), "raw chunk sidecar missing")
            if pass_no == 1 and i == 0:
                stamp = meta.get("acquired_at")
                require(isinstance(stamp, str), "first protected acquisition timestamp missing")
                require(datetime.fromisoformat(stamp).tzinfo is not None,
                        "first acquisition timestamp is not timezone-aware")
                first_acquired_at = stamp
            raw = rawpath.read_bytes()
            content_sha = hashlib.sha256(raw).hexdigest()
            require(content_sha == meta.get("raw_sha256") and
                    content_sha == report[("first" if pass_no == 1 else "second")+"_pass_raw_sha256"][i],
                    "chunk raw content SHA mismatch")
            payload = as_map(json.loads(raw, parse_float=Decimal), "raw candle JSON invalid")
            require(payload.get("success") is True and isinstance(payload.get("result"), list),
                    "raw candle payload shape changed")
            rows = payload["result"]
            expected_count = min(2000, 525600 - i * 2000)
            require(len(rows) == expected_count, "chunk row-count mismatch")
            parsed: list[tuple[int, Decimal, Decimal, Decimal, Decimal, Decimal]] = []
            for item in rows:
                v = as_map(item, "candle not object")
                t = v.get("time")
                require(type(t) is int, "candle time not integer")
                parts = []
                for k in ("open", "high", "low", "close", "volume"):
                    original = v.get(k)
                    require(type(original) in (str, Decimal, int), "non-exact candle number")
                    d = Decimal(str(original))
                    require(d.is_finite(), "nonfinite candle")
                    parts.append(d)
                o, high, low, close, volume = parts
                require(o > 0 and close > 0 and low > 0 and high >= max(o, low, close)
                        and low <= min(o, high, close) and volume >= 0,
                        "candle OHLC/volume invalid")
                parsed.append((t, o, high, low, close, volume))
            parsed.sort(key=lambda r: r[0])
            expected_time = START + (i * 2000) * 60
            for t, _, _, _, close, _ in parsed:
                require(t == expected_time, "source minute missing/duplicated/misaligned")
                if pass_no == 1 and seen % 5 == 4:
                    five_minute_closes.append(close)
                    old_sha.update(f"{t-240}:{decimal_text(close)}\n".encode("ascii"))
                seen += 1
                expected_time += 60
            digest_map = [{"time": t, "open": decimal_text(o), "high": decimal_text(h),
                           "low": decimal_text(l), "close": decimal_text(c), "volume": decimal_text(v)}
                          for t, o, h, l, c, v in parsed]
            sem = hashlib.sha256(json.dumps(digest_map, sort_keys=True, separators=(",", ":"),
                                 ensure_ascii=True).encode("ascii")).hexdigest()
            require(sem == meta.get("semantic_sha256") and
                    sem == report[("first" if pass_no == 1 else "second")+"_pass_semantic_sha256"][i],
                    "raw semantic digest mismatch")
            chunk_sha.append(sem)
        require(seen == 525600 and expected_time == END, "incomplete frozen UTC grid")
        pass_semantics.append(chunk_sha)
    require(pass_semantics[0] == pass_semantics[1], "two-pass semantic mismatch")
    require(len(five_minute_closes) == 105120 and old_sha.hexdigest() == OLD_5M,
            "original independent 5m-close evidence SHA mismatch")
    computed = config_hash({"close": five_minute_closes})
    require(computed == expected_close_digest, "source-dependent scenario close digest mismatch")
    require(inventory(root) == before, "archive mutated during independent read")
    return {"two_pass_semantic_check": "PASS", "source_inventory_check": "PASS",
            "source_acquisition_report_sha256": report_identity,
            "first_pass_first_chunk_acquired_at": first_acquired_at,
            "acquired_at_identity_note": "operational provenance, excluded from current source semantic_mapping and run ID",
            "one_minute_candles": 525600, "five_minute_closes": 105120,
            "original_five_minute_close_sha256": OLD_5M,
            "scenario_five_minute_close_digest": computed}


def verify_checkout(path: Path) -> str:
    """Verify actual local Git checkout; never trust the report's SHA alone."""
    repo = path.resolve(strict=True)
    def git(*args: str) -> str:
        p = subprocess.run(["git", "-C", str(repo), *args],
                           capture_output=True, text=True, timeout=20, check=False)
        require(p.returncode == 0, "local repository command failed")
        return p.stdout.strip()
    require(git("rev-parse", "--show-toplevel") == str(repo), "wrong local Git root")
    require(git("symbolic-ref", "--short", "HEAD") == "develop", "local checkout not on develop")
    head = git("rev-parse", "HEAD")
    require(not git("status", "--porcelain", "--untracked-files=normal"), "local checkout dirty")
    # Input report records the ORIGINAL preflight checkout; this verifier must
    # continue working after its own PR is merged. Pin the calculation/strategy
    # tree to Gate C instead of incorrectly requiring a forever-frozen HEAD.
    ancestry = subprocess.run(["git", "-C", str(repo), "merge-base", "--is-ancestor",
                               BASELINE, "HEAD"], capture_output=True, timeout=20,
                              check=False)
    require(ancestry.returncode == 0, "frozen Gate C baseline not an ancestor")
    diff = subprocess.run(["git", "-C", str(repo), "diff", "--quiet", BASELINE, "HEAD", "--",
                           "signalforge", "docs/strategies/btc-momentum-baseline-v0.md",
                           "docs/validation/btc-momentum-baseline-v0-validation-v0.md",
                           "docs/validation/btc-momentum-baseline-v0-scenario-validation-v0-proposal.md",
                           "docs/architecture/decisions/ADR-011-historical-execution-and-ambiguity-semantics.md",
                           "docs/architecture/decisions/ADR-011-scenario-execution-proposed-amendment.md"],
                          capture_output=True, timeout=20, check=False)
    require(diff.returncode == 0, "frozen execution/contract tree differs from Gate C")
    return head


def environment() -> dict[str, str | int]:
    result: dict[str, str | int] = {"python_version": sys.version.split()[0]}
    try:
        freeze = subprocess.run([sys.executable, "-m", "pip", "freeze", "--disable-pip-version-check"],
                                capture_output=True, text=True, check=True, timeout=30)
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        result["current_dependency_fingerprint"] = "UNAVAILABLE"
    else:
        packages = sorted(line.strip() for line in freeze.stdout.splitlines() if line.strip())
        result["current_dependency_fingerprint_sha256"] = hashlib.sha256(("\n".join(packages)+"\n").encode()).hexdigest()
        result["current_dependency_count"] = len(packages)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--private-dir", type=Path,
                        default=Path.home() / "signalforge-private/stage6/gate-d-preregistration")
    parser.add_argument("--generation-dir", type=Path,
                        default=Path.cwd() / ".signalforge-data/sf088/evidence/evidence-only/generation-0001")
    a = parser.parse_args()
    try:
        verified_checkout = verify_checkout(a.repo_root)
        folder = private_dir(a.private_dir)
        require(not folder.is_relative_to(a.generation_dir.resolve(strict=True)),
                "manifests cannot reside inside protected generation")
        manifest_checks, close_digest = verify_manifests(folder)
        source = verify_raw_source(a.generation_dir, close_digest)
        result = {"status": "PASS_INPUT_ONLY_NO_PERFORMANCE", "authority": "GATE_D_WITHHELD",
                  "verification_kind": "solo-operator independent algorithmic verification, not separate human review",
                  "manifest_checks": manifest_checks, "source_checks": source,
                  "preregistration_id": PREREG, "execution_revision": BASELINE,
                  "verified_local_git_checkout": verified_checkout,
                  "verifier_script_sha256": hash_file(Path(__file__)),
                  "environment_at_verification": environment(),
                  "custody_approved": False, "gate_d_approved": False}
        print(json.dumps(result, sort_keys=True, indent=2))
        return 0
    except (Blocked, FileNotFoundError, OSError, ValueError, TypeError, KeyError, IndexError,
            json.JSONDecodeError, subprocess.TimeoutExpired) as exc:
        print("BLOCKED: independent input verification did not complete; " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())