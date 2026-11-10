"""One-at-a-time, guarded Stage 6 research launcher (SF-274).

Gate D authorises research, not an unbounded process. The parent invokes an
unchanged frozen runner only inside an independently limited systemd scope.
The default --probe never reads historical source or evaluates a strategy.
No trade metrics, OOS contents or result mappings are printed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import resource
import shutil
import signal
import stat
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = Path(__file__).resolve()
BASELINE = "5d2812d11f8f5f061a1b637726f9e73b488c6e43"
APPROVED_HEAD = "6b499a3a38a68e8735299025b21e6d417e7a9136"
GATE_D_URL = (
    "https://github.com/harishkamathuk/signalforge/issues/253"
    "#issuecomment-6778010311"
)
PREREG = "9f55f96b47d2f83c8231595769ad0e3aaede6ef17a599e68f6ea115d1d8252c2"
SOURCE_HASH = "85d89887078504385a5023eaba007ffcdeeb7f4c67689c79cd5db9a407c999f9"
CONFIG_HASH = "88e90c23cd635248385d820406ef2201badc59bfd9f99043a63e8823227de242"
SCENARIO_HASH = "b7d89c3bcdfda94eb7b489ff12c03ab313573445bbf558fa4d10ce58ff081dc6"
RESOURCES_HASH = "28ecfb2d956a60ffbc33d334aeb379fcbabe61e056e3e254112ec34b0310c9d6"
GIB = 1024**3
MIB = 1024**2
MAX_MEMORY = 3 * GIB
MAX_AS = 4 * GIB
MAX_OUTPUT = 512 * MIB
HOST_RESERVE = 3 * GIB // 4
CPU_SECONDS = 1800
WALL_SECONDS = 1200
RUNS = {
    "REFERENCE_RAW": (
        "84ac178645c49c0d53ff22c676cb36243ed340945019d46cea878acbe0825099",
        "6c9f388e1732110177108489350a49c8d8028e7507f3f69e516630d1b7f1a22f",
        "reference_raw-input-manifest.json",
    ),
    "ADVERSE_RAW": (
        "75cea6ced58247ad86adc4d16a9a41e02d442274e733b6a957a761b682f30dcf",
        "5ed7494f7faafb52e71935f27f062fc595f93f5e89fb83256068e0c18d518ff8",
        "adverse_raw-input-manifest.json",
    ),
}
SOURCE_DIR = ROOT / ".signalforge-data/sf088/evidence/evidence-only/generation-0001"
PRIVATE_DIR = Path.home() / "signalforge-private/stage6/gate-d-preregistration"
OUTPUT_ROOT = Path.home() / "signalforge-private/stage6/gate-d-historical-results"
GATE_RECORD = PRIVATE_DIR / "gate-d-record.json"


class LaunchBlocked(RuntimeError):
    """A missing safety, identity or provenance condition prevents a run."""


def require(condition: bool, reason: str) -> None:
    """Fail closed without displaying protected input contents."""
    if not condition:
        raise LaunchBlocked(reason)


def _git(*args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(ROOT), *args],
        capture_output=True, text=True, check=False, timeout=20,
    )
    require(proc.returncode == 0, "repository verification command failed")
    return proc.stdout.strip()


def verify_checkout() -> None:
    """Pin the calculation tree, allowing approved later documentation changes."""
    require(_git("symbolic-ref", "--short", "HEAD") == "develop",
            "operator checkout must be on develop")
    head = _git("rev-parse", "HEAD")
    require(len(head) == 40 and all(c in "0123456789abcdef" for c in head),
            "invalid operator checkout SHA")
    require(not _git("status", "--porcelain", "--untracked-files=normal"),
            "operator checkout must be clean")
    _git("merge-base", "--is-ancestor", APPROVED_HEAD, head)
    _git("merge-base", "--is-ancestor", BASELINE, head)
    # The Option A documentation revision is accepted; calculation code is frozen.
    changed = subprocess.run(
        ["git", "-C", str(ROOT), "diff", "--quiet", BASELINE, head, "--",
         "signalforge/", "docs/strategies/btc-momentum-baseline-v0.md",
         "docs/validation/btc-momentum-baseline-v0-validation-v0.md",
         "docs/architecture/decisions/ADR-011-scenario-execution-proposed-amendment.md",
         "docs/architecture/execution-scenario-modelling-contract-proposal.md"],
        check=False, capture_output=True, timeout=20,
    )
    require(changed.returncode == 0, "frozen calculation or strategy contract drift")


def _private(path: Path, mode: int, *, outside_repo: bool = True) -> Path:
    """Validate an existing private file or directory without following symlinks."""
    raw = path.absolute()
    real = raw.resolve(strict=True)
    require(raw == real, "private path or an ancestor is a symlink")
    require(stat.S_IMODE(real.stat().st_mode) == mode, "private permissions differ")
    require(real.is_dir() if mode == 0o700 else real.is_file(),
            "private path has the wrong type")
    if outside_repo:
        require(not real.is_relative_to(ROOT), "private result inside Git checkout")
        require(not any(p in (".signalforge-data", "sf088", "sf096") for p in real.parts),
                "private result in protected source tree")
        require(not any((ancestor / ".git").exists() for ancestor in (real, *real.parents)),
                "private result inside a Git worktree")
    return real


def _source_dir() -> Path:
    raw = SOURCE_DIR.absolute()
    real = raw.resolve(strict=True)
    require(raw == real and real.is_dir(), "frozen source path missing or redirected")
    require(real.parts[-5:] == (
        ".signalforge-data", "sf088", "evidence", "evidence-only", "generation-0001",
    ), "protected source identity path is not frozen")
    return real


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _available_ram() -> int:
    for line in Path("/proc/meminfo").read_text(encoding="ascii").splitlines():
        if line.startswith("MemAvailable:"):
            return int(line.split()[1]) * 1024
    raise LaunchBlocked("Linux MemAvailable is unavailable")


def verify_prelaunch(profile: str, attempt: int, *, existing: bool = False) -> tuple[Path, Path]:
    """Check operator input/authority and private output without reading market bars."""
    require(profile in RUNS and attempt in (1, 2), "unregistered profile or attempt")
    verify_checkout()
    source = _source_dir()
    _private(PRIVATE_DIR, 0o700)
    output = _private(OUTPUT_ROOT, 0o700)
    record = _private(GATE_RECORD, 0o600)
    try:
        approval = json.loads(record.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        raise LaunchBlocked("invalid private Gate D record") from exc
    require(
        type(approval) is dict
        and approval.get("parent_issue") == 253
        and approval.get("record_url") == GATE_D_URL
        and approval.get("decision") == "GATE_D_ACCEPT"
        and approval.get("preregistration_id") == PREREG
        and approval.get("execution_revision") == BASELINE,
        "Gate D record does not match accepted decision",
    )
    expected_run, expected_sha, manifest_name = RUNS[profile]
    manifest = _private(PRIVATE_DIR / manifest_name, 0o600)
    require(_sha256(manifest) == expected_sha, "frozen profile manifest SHA differs")
    # Do not assume an arbitrary 6 GiB RAM approval cutoff; reserve host headroom
    # against the actual configured hard cgroup bound.
    require(_available_ram() >= MAX_MEMORY + HOST_RESERVE,
            "insufficient host headroom for bounded attempt")
    free = os.statvfs(output)
    require(free.f_bavail * free.f_frsize >= MAX_OUTPUT + 256 * MIB,
            "insufficient output filesystem reserve")
    attempt_dir = output / f"{profile.lower()}-attempt-{attempt}"
    if existing:
        _private(attempt_dir, 0o700)
    else:
        require(not attempt_dir.exists() and not attempt_dir.is_symlink(),
                "existing attempt evidence would be overwritten")
    require(len(expected_run) == 64, "invalid registered run identity")
    return source, attempt_dir


def _limits() -> dict[str, int]:
    """Read effective cgroup and rlimits inside the guarded process."""
    cg = next(
        (line.split("::", 1)[1] for line in
         Path("/proc/self/cgroup").read_text(encoding="ascii").splitlines()
         if line.startswith("0::")), None,
    )
    require(isinstance(cg, str), "cgroup v2 is unavailable")
    root = Path("/sys/fs/cgroup") / cg.lstrip("/")
    try:
        memory = int((root / "memory.max").read_text(encoding="ascii").strip())
        swap = int((root / "memory.swap.max").read_text(encoding="ascii").strip())
    except (ValueError, OSError) as exc:
        raise LaunchBlocked("effective cgroup memory/swap limits unavailable") from exc
    as_soft, _ = resource.getrlimit(resource.RLIMIT_AS)
    fs_soft, _ = resource.getrlimit(resource.RLIMIT_FSIZE)
    cpu_soft, _ = resource.getrlimit(resource.RLIMIT_CPU)
    require(0 < memory <= MAX_MEMORY and swap == 0, "missing hard memory/swap cap")
    require(0 < as_soft <= MAX_AS, "missing address-space rlimit")
    require(0 < fs_soft <= MAX_OUTPUT, "missing output-file rlimit")
    require(0 < cpu_soft <= CPU_SECONDS, "missing CPU-time rlimit")
    return {
        "memory_max_bytes": memory, "memory_swap_max_bytes": swap,
        "as_soft_bytes": as_soft, "file_soft_bytes": fs_soft,
        "cpu_soft_seconds": cpu_soft,
    }


def _scope_command(worker_args: list[str], *, unit: str | None = None) -> list[str]:
    """Apply identical external limits to a harmless probe and protected worker."""
    required = ("systemd-run", "timeout", "prlimit")
    resolved = [shutil.which(name) for name in required]
    require(all(resolved), "required Linux resource-control tool is missing")
    systemd, timeout, prlimit = resolved
    assert systemd and timeout and prlimit
    return [
        systemd, "--user", "--scope", "--quiet", "--collect",
        *([] if unit is None else [f"--unit={unit}"]),
        "-p", f"MemoryMax={MAX_MEMORY}", "-p", "MemorySwapMax=0",
        timeout, "--signal=TERM", "--kill-after=5s", f"{WALL_SECONDS}s",
        prlimit, f"--as={MAX_AS}:{MAX_AS}",
        f"--fsize={MAX_OUTPUT}:{MAX_OUTPUT}",
        f"--cpu={CPU_SECONDS}:{CPU_SECONDS}", "--",
        sys.executable, str(SCRIPT), *worker_args,
    ]


def _probe() -> dict[str, object]:
    """Run a fabricated-data-free prelaunch check through the real scope command."""
    cmd = _scope_command(
        ["--internal-probe"], unit=f"sf274-probe-{os.getpid()}.scope",
    )
    proc = subprocess.run(
        cmd, capture_output=True, text=True, check=False, timeout=40,
    )
    require(proc.returncode == 0, "bounded systemd scope probe failed")
    try:
        payload = json.loads(proc.stdout.strip())
    except ValueError as exc:
        raise LaunchBlocked("bounded scope returned invalid probe receipt") from exc
    require(type(payload) is dict and payload.get("status") == "LIMITS_VERIFIED",
            "bounded scope did not attest effective limits")
    for name in (
        "memory_max_bytes", "memory_swap_max_bytes",
        "as_soft_bytes", "file_soft_bytes", "cpu_soft_seconds",
    ):
        require(type(payload.get(name)) is int, "missing effective limit: " + name)
    require(payload["memory_max_bytes"] <= MAX_MEMORY
            and payload["memory_swap_max_bytes"] == 0
            and payload["as_soft_bytes"] <= MAX_AS
            and payload["file_soft_bytes"] <= MAX_OUTPUT
            and payload["cpu_soft_seconds"] <= CPU_SECONDS,
            "effective scope limits are outside the registered envelope")
    return payload


def _worker(profile: str, attempt: int) -> None:
    """Build the exact frozen request and write a private non-published result."""
    _limits()  # Before any protected source is read.
    os.umask(0o077)
    source_dir, attempt_dir = verify_prelaunch(profile, attempt, existing=True)
    attempt_dir = _private(attempt_dir, 0o700)  # Created only by parent.
    sys.path.insert(0, str(ROOT))
    from signalforge.config.identity import canonical_config_json, config_hash
    from signalforge.config.strategy_registry import (
        DEFAULT_STRATEGY_REGISTRY,
        StrategySelection,
    )
    from signalforge.research.btc_raw_diagnostic_input import (
        load_sf095_raw_diagnostic_source,
    )
    from signalforge.research.historical_bars import aggregate_one_minute_to_five_minute
    from signalforge.research.historical_execution import HistoricalExecutionAssumptionProfile
    from signalforge.research.scenario_execution import (
        ScenarioAssumptionSet,
        ScenarioMode,
        ScenarioResearchRequest,
        ScenarioResearchRunner,
        ScenarioResourcePolicy,
        _manifest,
    )

    source = load_sf095_raw_diagnostic_source(source_dir)
    require(source.dataset.content_hash == SOURCE_HASH and not source.execution_valid,
            "protected source data identity is not frozen")
    selection = StrategySelection("btc_momentum_baseline_v0", "0.1.0-experimental", {})
    strategy = DEFAULT_STRATEGY_REGISTRY.resolve(selection)
    require(strategy.config_identity.config_hash == CONFIG_HASH,
            "frozen BTC strategy config differs")
    assumptions = ScenarioAssumptionSet.btc_ohlc_path_v1()
    require(assumptions.semantic_hash == SCENARIO_HASH, "scenario assumptions differ")
    resources = ScenarioResourcePolicy(
        "FINITE_FAIL_CLOSED", "1.0.0", 524160, 2096640, 104833, 2096640, 1,
    )
    require(config_hash(resources.mapping()) == RESOURCES_HASH,
            "registered finite budget differs")
    raw_profile = (
        HistoricalExecutionAssumptionProfile.reference_raw()
        if profile == "REFERENCE_RAW"
        else HistoricalExecutionAssumptionProfile.adverse_raw()
    )
    request = ScenarioResearchRequest(
        mode=ScenarioMode.SCENARIO_RESEARCH, source=source,
        strategy_selection=selection, engine_calculation_version="engine-v1",
        assumptions=assumptions, profile=raw_profile, resources=resources,
        is_start=datetime(2025, 10, 31, tzinfo=UTC),
        oos_start=datetime(2026, 7, 1, tzinfo=UTC),
        measured_end=datetime(2026, 10, 30, tzinfo=UTC),
        repository_revision=BASELINE,
    )
    candles = aggregate_one_minute_to_five_minute(source.dataset)
    expected_run, expected_sha, manifest_name = RUNS[profile]
    planned = _manifest(request, strategy, candles)
    encoded = (canonical_config_json({
        "input_mapping": planned.mapping(), "scenario_run_id": planned.run_id,
    }) + "\n").encode("utf-8")
    require(planned.run_id == expected_run
            and hashlib.sha256(encoded).hexdigest() == expected_sha,
            "calculated frozen input manifest differs")
    require(encoded == (PRIVATE_DIR / manifest_name).read_bytes(),
            "original private canonical manifest differs")
    # Do not inspect or publish IS/OOS outcomes. The result is a sealed-output
    # candidate even if its eventual methodology verdict is inconclusive.
    result = ScenarioResearchRunner().run_verified(request)
    require(result.manifest.run_id == expected_run and not result.execution_valid,
            "scenario result changed frozen identity or evidence status")
    pending = attempt_dir / "partial.json"
    result.write_new(pending)  # Exclusive creation; may leave a quarantined partial.
    with pending.open("rb") as stream:
        os.fsync(stream.fileno())
    require(pending.stat().st_size <= MAX_OUTPUT, "canonical file exceeds cap")
    receipt = {
        "status": "CANONICAL_WRITE_COMPLETED_METHOD_UNASSESSED",
        "profile": profile, "attempt": attempt, "scenario_run_id": expected_run,
        "canonical_sha256": _sha256(pending), "canonical_bytes": pending.stat().st_size,
        "execution_valid": False,
    }
    with (attempt_dir / "worker-receipt.json").open("x", encoding="utf-8") as output:
        json.dump(receipt, output, sort_keys=True)
        output.write("\n")
        output.flush()
        os.fsync(output.fileno())


def _stop_scope(unit: str) -> bool:
    """Stop the named unit and independently verify it is not still active."""
    try:
        subprocess.run(
            ["systemctl", "--user", "stop", unit], capture_output=True,
            check=False, timeout=20,
        )
        check = subprocess.run(
            ["systemctl", "--user", "is-active", "--quiet", unit],
            capture_output=True, check=False, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return check.returncode != 0


def _signal_abort(_signal: int, _frame: object) -> None:
    """Turn catchable parent termination into a quarantined failure."""
    raise KeyboardInterrupt


def _parent_run(profile: str, attempt: int) -> dict[str, object]:
    """Launch exactly one process and quarantine any incomplete attempt."""
    _, path = verify_prelaunch(profile, attempt)
    _probe()  # Actual scope command, with no source access, always checked first.
    unit = f"sf274-{profile.lower()}-a{attempt}-{os.getpid()}.scope"
    command = _scope_command(
        ["--internal-worker", "--profile", profile, "--attempt", str(attempt)],
        unit=unit,
    )
    path.mkdir(mode=0o700)  # Exclusive; no reuse of a failed attempt.
    old_handler = signal.signal(signal.SIGTERM, _signal_abort)
    try:
        try:
            with open(os.devnull, "wb") as quiet:
                proc = subprocess.run(
                    command, stdout=quiet, stderr=quiet, check=False,
                    timeout=WALL_SECONDS + 45,
                )
            exit_code = proc.returncode
        except subprocess.TimeoutExpired:
            exit_code = 124
        except OSError:
            exit_code = 127
        except KeyboardInterrupt:
            exit_code = 130
    finally:
        signal.signal(signal.SIGTERM, old_handler)
    # Killing the systemd-run *client* alone need not stop its scope.
    stopped = True if exit_code == 0 else _stop_scope(unit)
    receipt_path = path / "worker-receipt.json"
    pending = path / "partial.json"
    if stopped and exit_code == 0 and receipt_path.is_file() and pending.is_file():
        try:
            _private(receipt_path, 0o600)
            _private(pending, 0o600)
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            expected_run = RUNS[profile][0]
            require(
                receipt == {
                    "status": "CANONICAL_WRITE_COMPLETED_METHOD_UNASSESSED",
                    "profile": profile, "attempt": attempt,
                    "scenario_run_id": expected_run,
                    "canonical_sha256": _sha256(pending),
                    "canonical_bytes": pending.stat().st_size,
                    "execution_valid": False,
                },
                "worker success receipt does not match canonical bytes",
            )
            require(0 < pending.stat().st_size <= MAX_OUTPUT,
                    "canonical result exceeds file cap")
            # Hard link is non-overwriting and same-filesystem; partial file is
            # unlinked only after success. On crash, both private names remain
            # visible, and the attempt cannot be reused.
            completed = path / "canonical-result.json"
            os.link(pending, completed, follow_symlinks=False)
            pending.unlink()
            return {
                "status": "CANONICAL_RESULT_PRIVATE_NOT_RELEASED",
                "profile": profile, "attempt": attempt,
                "sha256": receipt["canonical_sha256"],
                "bytes": receipt["canonical_bytes"],
                "result_file": str(completed),
                "gate_e_approved": False,
            }
        except (OSError, ValueError, LaunchBlocked):
            pass
    if exit_code == 0:
        stopped = _stop_scope(unit)
    failure = {
        "status": ("ATTEMPT_QUARANTINED_NO_PERFORMANCE" if stopped
                   else "SCOPE_STOP_UNVERIFIED_NO_PERFORMANCE"),
        "profile": profile, "attempt": attempt,
        "launcher_exit_code": exit_code,
        "reason": "LIMIT_OR_INTEGRITY_STOP",
        "partial_file_retained": pending.exists(),
        "scope_confirmed_stopped": stopped,
    }
    # No deletion, retry, result mapping or OOS disclosure on failure.
    with (path / "failure.json").open("x", encoding="utf-8") as output:
        json.dump(failure, output, sort_keys=True)
        output.write("\n")
    return failure


def main(argv: list[str] | None = None) -> int:
    """Verify limits without historical access, or explicitly launch one attempt."""
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--probe", action="store_true", help="safe default, no protected access")
    mode.add_argument("--run", action="store_true", help="explicit protected attempt after FIN")
    mode.add_argument("--internal-probe", action="store_true", help=argparse.SUPPRESS)
    mode.add_argument("--internal-worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--profile", choices=tuple(RUNS))
    parser.add_argument("--attempt", type=int, choices=(1, 2))
    args = parser.parse_args(argv)
    if args.run or args.internal_worker:
        if args.profile is None or args.attempt is None:
            parser.error("--profile and --attempt are required for a protected attempt")
    elif args.profile is not None or args.attempt is not None:
        parser.error("profile and attempt are only valid for an explicit run")
    try:
        if args.internal_probe:
            print(json.dumps({"status": "LIMITS_VERIFIED", **_limits()}, sort_keys=True))
            return 0
        if args.internal_worker:
            _worker(args.profile, args.attempt)
            return 0
        if args.run:
            report = _parent_run(args.profile, args.attempt)
            print(json.dumps(report, sort_keys=True))
            return 0 if report["status"] == "CANONICAL_RESULT_PRIVATE_NOT_RELEASED" else 2
        # No source/private manifest reads in the default probe.
        verify_checkout()
        print(json.dumps({"status": "GUARDED_SCOPE_PROBE",
                          "limits": _probe(), "protected_access": False},
                         sort_keys=True))
        return 0
    except (LaunchBlocked, OSError, subprocess.SubprocessError) as exc:
        # This is an operator diagnostic. Never display protected bars or outcomes.
        print(json.dumps({"status": "GUARDED_LAUNCH_BLOCKED",
                          "reason": type(exc).__name__}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
