"""SF-260 90D v1 source-only preregistration; NEVER runs scenario research.

Requires an externally constrained cgroup/rlimit before any protected read.
Canonical manifests/run IDs are derived from actual audited bars, never from
operator-supplied hashes or fabricated historical placeholders.
"""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import os
import resource
import stat
import subprocess
import sys
from pathlib import Path

# Direct absolute-path invocation otherwise exposes scripts/, not its parent.
# The import root is derived from this checked-out file, never operator input.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from signalforge.config.identity import canonical_config_json, config_hash  # noqa: E402
from signalforge.config.strategy_registry import DEFAULT_STRATEGY_REGISTRY, StrategySelection  # noqa: E402
from signalforge.research.audited_source_slice_v1 import (  # noqa: E402
    IS_START,
    MEASURED_END,
    OOS_START,
    AuditedSourceSliceV1,
    derive_audited_source_slice,
)
from signalforge.research.btc_raw_diagnostic_input import load_sf095_raw_diagnostic_source  # noqa: E402
from signalforge.research.historical_bars import aggregate_one_minute_to_five_minute  # noqa: E402
from signalforge.research.historical_execution import HistoricalExecutionAssumptionProfile  # noqa: E402
from signalforge.research.scenario_execution import (  # noqa: E402
    SF260_90D_VARIANT,
    ScenarioAssumptionSet,
    ScenarioMode,
    ScenarioResearchRequest,
    ScenarioResourcePolicy,
    _manifest,
)

SOURCE = ROOT / ".signalforge-data/sf088/evidence/evidence-only/generation-0001"
PRIVATE = Path.home() / "signalforge-private/stage6/90d-v1/source-prereg"
PROFILES = ("REFERENCE_RAW", "ADVERSE_RAW")
MEMORY_LIMIT = 3 * 1024**3
ADDRESS_LIMIT = 4 * 1024**3
FILE_LIMIT = 512 * 1024**2
WALL_LIMIT = 1200
RESERVE = 3 * 1024**3 // 4


class PreflightBlocked(RuntimeError):
    """Source-only preflight must stop without minting evidence."""


def require(ok: bool, reason: str) -> None:
    if not ok:
        raise PreflightBlocked(reason)


def require_limits() -> None:
    """Fail closed before materialising the 525,600-minute authenticated parent."""
    from scripts.stage6_90d_guarded_launcher import _available_ram, _limits

    observed = _limits()  # cgroup memory/swap + RLIMIT_AS/CPU/FSIZE
    require(observed["memory_max_bytes"] <= MEMORY_LIMIT, "memory ceiling exceeded")
    require(observed["as_soft_bytes"] <= ADDRESS_LIMIT, "virtual memory ceiling exceeded")
    require(observed["file_soft_bytes"] <= FILE_LIMIT, "output ceiling exceeded")
    require(observed["memory_swap_max_bytes"] == 0, "swap is not disabled")
    require(_available_ram() >= MEMORY_LIMIT + RESERVE, "host headroom unavailable")


def git_revision() -> str:
    branch_name = subprocess.run(
        ["git", "-C", str(ROOT), "symbolic-ref", "--short", "HEAD"],
        capture_output=True, text=True, check=True, timeout=10,
    ).stdout.strip()
    require(branch_name == "develop", "source-only attestation requires merged develop")
    revision = subprocess.run(
        ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True, timeout=10,
    ).stdout.strip()
    require(
        len(revision) == 40 and all(c in "0123456789abcdef" for c in revision),
        "unbound source-only checkout revision",
    )
    status = subprocess.run(
        ["git", "-C", str(ROOT), "status", "--porcelain", "--untracked-files=normal"],
        capture_output=True, text=True, check=True, timeout=10,
    )
    require(not status.stdout.strip(), "dirty source-only checkout")
    return revision


def private_destination(path: Path) -> Path:
    """Existing private directory, never a Git/protected/archive destination."""
    require(path == PRIVATE and path.is_dir() and not path.is_symlink(),
            "unexpected source-only destination")
    home = Path.home().resolve(strict=True)
    actual = path.resolve(strict=True)
    require(
        actual == path.absolute() and actual.is_relative_to(home)
        and any(p.name == "signalforge-private" for p in actual.parents),
        "source-only destination escapes private home",
    )
    for ancestor in (path, *path.parents):
        if ancestor == home:
            break
        require(not ancestor.is_symlink(), "symlinked destination ancestor")
    require(stat.S_IMODE(path.stat().st_mode) == 0o700, "private directory mode must be 0700")
    require(path.stat().st_uid == os.getuid(), "destination not owned by operator")
    require(not any(path.iterdir()), "source-only preregistration is write-once")
    free = os.statvfs(path)
    require(free.f_bavail * free.f_frsize >= FILE_LIMIT + 256 * 1024**2,
            "insufficient private free disk")
    return actual


def planned_manifests(source: AuditedSourceSliceV1, revision: str
                      ) -> tuple[list[tuple[str, str, bytes, str]], str]:
    """Build input-only canonical manifests, without runner/signal evaluation."""
    selection = StrategySelection("btc_momentum_baseline_v0", "0.1.0-experimental", {})
    strategy = DEFAULT_STRATEGY_REGISTRY.resolve(selection)
    require(
        strategy.config_identity.config_hash
        == "88e90c23cd635248385d820406ef2201badc59bfd9f99043a63e8823227de242",
        "frozen strategy config differs",
    )
    assumptions = ScenarioAssumptionSet.btc_ohlc_path_v1()
    resources = ScenarioResourcePolicy(
        "FINITE_FAIL_CLOSED", "1.0.0", 524160, 2096640, 104833, 2096640, 1,
    )
    candles = aggregate_one_minute_to_five_minute(source.dataset)
    records: list[tuple[str, str, bytes, str]] = []
    for profile_id, profile in (
        ("REFERENCE_RAW", HistoricalExecutionAssumptionProfile.reference_raw()),
        ("ADVERSE_RAW", HistoricalExecutionAssumptionProfile.adverse_raw()),
    ):
        request = ScenarioResearchRequest(
            mode=ScenarioMode.SCENARIO_RESEARCH, source=source,
            strategy_selection=selection, engine_calculation_version="engine-v1",
            assumptions=assumptions, profile=profile, resources=resources,
            is_start=IS_START, oos_start=OOS_START, measured_end=MEASURED_END,
            repository_revision=revision, study_variant=SF260_90D_VARIANT,
        )
        manifest = _manifest(request, strategy, candles)
        canonical = (
            canonical_config_json({
                "input_mapping": manifest.mapping(), "scenario_run_id": manifest.run_id,
            }) + "\n"
        ).encode("utf-8")
        records.append((
            profile_id, manifest.run_id, canonical, hashlib.sha256(canonical).hexdigest(),
        ))
    prereg = config_hash({
        "domain": "sf260-90d-source-only-prereg-v1",
        "revision": revision, "slice_derivation_id": source.derivation_id,
        "profiles": [[p, run, digest] for p, run, _, digest in records],
    })
    return records, prereg


def _write_private_payloads(payloads: list[tuple[str, bytes]]) -> None:
    """Exclusive, no-follow, 0600 source-only receipts. Never overwrite."""
    for name, payload in payloads:
        fd = os.open(
            PRIVATE / name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
        )
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
        except BaseException:
            # Interrupted evidence stays quarantined, never retried by overwrite.
            raise


def source_only_preflight() -> dict[str, object]:
    require_limits()
    revision = git_revision()
    private_destination(PRIVATE)
    parent = load_sf095_raw_diagnostic_source(SOURCE)
    child = derive_audited_source_slice(parent)
    del parent
    gc.collect()
    records, prereg = planned_manifests(child, revision)
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
    require(peak < MEMORY_LIMIT, "source-audit-to-derivation RSS exceeded ceiling")
    summary: dict[str, object] = {
        "contract": "sf260-90d-source-only-prereg-v1",
        "disposition": "PREPARATION_ONLY_GATE_D_WITHHELD",
        "gate_d_approved": False, "protected_scenario_executed": False,
        "execution_valid": False, "historical_metadata_status":
            "UNQUALIFIED_HISTORICAL_METADATA",
        "revision": revision, "source_lineage": child.lineage_preimage(),
        "sample_status": "REPEATED_SAMPLE",
        "window_selection": "EARLIEST_90_MEASURED_UTC_DAYS",
        "derivation_id": child.derivation_id, "input_preregistration_id": prereg,
        "source_only_peak_rss_bytes": peak,
        "profiles": [
            {"profile": p, "run_id": run, "filename": f"{p.lower()}-manifest.json",
             "canonical_sha256": digest}
            for p, run, _, digest in records
        ],
    }
    payloads = [(f"{p.lower()}-manifest.json", content) for p, _, content, _ in records]
    payloads.append((
        "source-only-readiness.json",
        (canonical_config_json(summary) + "\n").encode("utf-8"),
    ))
    _write_private_payloads(payloads)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-only-attestation", action="store_true")
    args = parser.parse_args(argv)
    if not args.source_only_attestation:
        parser.error("explicit --source-only-attestation is required; no scenario execution")
    try:
        info = source_only_preflight()
    except (OSError, ValueError, PreflightBlocked) as error:
        parser.exit(2, f"SF260 SOURCE-ONLY BLOCKED: {type(error).__name__}: {error}\n")
    print(json.dumps({
        "status": "SOURCE_ONLY_PREREG_CREATED_NEEDS_INDEPENDENT_VERIFICATION",
        "revision": info["revision"], "input_preregistration_id":
            info["input_preregistration_id"], "protected_scenario_executed": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
