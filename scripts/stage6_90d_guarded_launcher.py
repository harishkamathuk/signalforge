"""One-at-a-time, guarded 90D distinct audited-source launcher (SF-260 B4).

Gate D authorises research, not an unbounded process. The parent invokes an
unchanged frozen runner only inside an independently limited systemd scope.
The default --probe never reads historical source or evaluates a strategy.
No trade metrics, OOS contents or result mappings are printed.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import resource
import shutil
import signal
import stat
import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# The guarded child starts by absolute script path; initialise the verified
# repository import root before the child calls the source-only verifier.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SCRIPT = Path(__file__).resolve()
BASELINE = "2dc6faef5aa00ef358f6c539c69aae8ec79493c6"
OWNER_WINDOW_DECISION = (
    "https://github.com/harishkamathuk/signalforge/issues/253#issuecomment-6864968129"
)
GIB = 1024**3
MIB = 1024**2
MAX_MEMORY = 3 * GIB
MAX_AS = 4 * GIB
MAX_OUTPUT = 512 * MIB
HOST_RESERVE = 3 * GIB // 4
CPU_SECONDS = 1200
WALL_SECONDS = 1200
MAX_PIDS = 64
RUNS = ("REFERENCE_RAW", "ADVERSE_RAW")
SOURCE_DIR = ROOT / ".signalforge-data/sf088/evidence/evidence-only/generation-0001"
PRIVATE_DIR = Path.home() / "signalforge-private/stage6/90d-v1/source-prereg"
OUTPUT_ROOT = Path.home() / "signalforge-private/stage6/90d-v1/historical-results"
GATE_RECORD = PRIVATE_DIR / "gate-d-90d-record.json"
SOURCE_BACKUP = PRIVATE_DIR / "verified-source-backup.json"

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
    """Require an exact clean, preregistered calculation revision on develop."""
    require(_git("symbolic-ref", "--short", "HEAD") == "develop",
            "90D operator checkout must be on develop")
    head = _git("rev-parse", "HEAD")
    require(len(head) == 40 and all(c in "0123456789abcdef" for c in head),
            "invalid checkout revision")
    require(not _git("status", "--porcelain", "--untracked-files=normal"),
            "90D operator checkout must be clean")
    _git("merge-base", "--is-ancestor", BASELINE, head)
    # BTC signal/config cannot drift relative to the original baseline.
    # The RAW historical_execution typing was additively extended for the
    # distinct audited source wrapper; exact prereg HEAD + later Gate D bind
    # the complete reviewed calculation tree, including that file.
    protected = subprocess.run([
        "git", "-C", str(ROOT), "diff", "--quiet", BASELINE, head, "--",
        "signalforge/runtime/btc_momentum_baseline_v0.py",
        "signalforge/config/btc_momentum_baseline_v0.py",
    ], check=False, capture_output=True, timeout=20)
    require(protected.returncode == 0, "frozen BTC strategy/RAW semantics drift")

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


def _registration(profile: str) -> tuple[str, str, str, str, str]:
    """Bind run ID and manifest SHA solely from private verified prereg bytes."""
    from scripts.stage6_90d_independent_verifier import read_canonical

    require(profile in RUNS, "unknown 90D profile")
    readiness, readiness_sha = read_canonical(PRIVATE_DIR / "source-only-readiness.json")
    independent, _ = read_canonical(PRIVATE_DIR / "independent-verification.json")
    revision = _git("rev-parse", "HEAD")
    require(
        readiness.get("revision") == revision
        and readiness.get("disposition") == "PREPARATION_ONLY_GATE_D_WITHHELD"
        and readiness.get("protected_scenario_executed") is False
        and readiness.get("execution_valid") is False
        and independent.get("revision") == revision
        and independent.get("status") == "SOURCE_ONLY_INDEPENDENTLY_VERIFIED_NO_GATE_D"
        and independent.get("receipt_sha256") == readiness_sha
        and independent.get("preregistration_id") ==
            readiness.get("input_preregistration_id")
        and independent.get("gate_d_approved") is False,
        "missing/mismatched independent 90D source prereg",
    )
    rows = readiness.get("profiles")
    require(type(rows) is list and len(rows) == 2, "missing 90D profile prereg")
    row = rows[RUNS.index(profile)]
    require(type(row) is dict and row.get("profile") == profile,
            "profile prereg order/identity mismatch")
    run_id, expected_sha, manifest_name = (
        row.get("run_id"), row.get("canonical_sha256"), row.get("filename"),
    )
    require(
        type(run_id) is str and len(run_id) == 64
        and type(expected_sha) is str and len(expected_sha) == 64
        and manifest_name == f"{profile.lower()}-manifest.json",
        "invalid registered 90D run or manifest identity",
    )
    require(_sha256(_private(PRIVATE_DIR / manifest_name, 0o600)) == expected_sha,
            "registered 90D canonical manifest SHA differs")
    return run_id, expected_sha, manifest_name, str(readiness["derivation_id"]), str(
        readiness["input_preregistration_id"]
    )


def verify_prelaunch(profile: str, attempt: int, *, existing: bool = False
                     ) -> tuple[Path, Path]:
    """Separate 90D Gate D + independently verified source/custody admission."""
    require(profile in RUNS and attempt in (1, 2), "invalid 90D profile/attempt")
    verify_checkout()
    source = _source_dir()
    _private(PRIVATE_DIR, 0o700)
    _private(OUTPUT_ROOT, 0o700)
    gate_path = _private(GATE_RECORD, 0o600)
    try:
        gate = json.loads(gate_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise LaunchBlocked("invalid separate 90D Gate D approval record") from exc
    run_id, manifest_sha, filename, derivation_id, prereg_id = _registration(profile)
    require(
        type(gate) is dict and gate.get("parent_issue") == 253
        and gate.get("variant") == "SF260_90D_AUDITED_V1"
        and gate.get("decision") == "GATE_D_90D_ACCEPT"
        and gate.get("execution_revision") == _git("rev-parse", "HEAD")
        and gate.get("input_preregistration_id") == prereg_id
        and gate.get("source_derivation_id") == derivation_id
        and gate.get("window_owner_decision") == OWNER_WINDOW_DECISION
        and type(gate.get("approval_url")) is str
        and gate["approval_url"].startswith(
            "https://github.com/harishkamathuk/signalforge/issues/253#issuecomment-"
        )
        and gate["approval_url"] != OWNER_WINDOW_DECISION,
        "unapproved 90D protected execution or input identity drift",
    )
    backup_path = _private(SOURCE_BACKUP, 0o600)
    backup = json.loads(backup_path.read_text(encoding="utf-8"))
    require(
        type(backup) is dict
        and backup.get("contract") == "sf260-90d-verified-encrypted-source-backup-v1"
        and backup.get("source_derivation_id") == derivation_id
        and backup.get("verified") is True
        and type(backup.get("encrypted_archive_sha256")) is str
        and len(backup["encrypted_archive_sha256"]) == 64
        and gate.get("source_backup_receipt_sha256") == _sha256(backup_path),
        "missing independently verified encrypted source backup receipt",
    )
    require(_available_ram() >= MAX_MEMORY + HOST_RESERVE,
            "insufficient initial host memory reserve")
    free = os.statvfs(OUTPUT_ROOT)
    require(free.f_bavail * free.f_frsize >= MAX_OUTPUT + 256 * MIB,
            "insufficient private result volume")
    attempt_dir = OUTPUT_ROOT / f"{profile.lower()}-attempt-{attempt}"
    if existing:
        _private(attempt_dir, 0o700)
    else:
        require(not attempt_dir.exists() and not attempt_dir.is_symlink(),
                "90D attempt evidence collision")
    require(run_id and manifest_sha and filename, "missing 90D prereg")
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
        pids = int((root / "pids.max").read_text(encoding="ascii").strip())
    except (ValueError, OSError) as exc:
        raise LaunchBlocked("effective cgroup memory/swap limits unavailable") from exc
    as_soft, _ = resource.getrlimit(resource.RLIMIT_AS)
    fs_soft, _ = resource.getrlimit(resource.RLIMIT_FSIZE)
    cpu_soft, _ = resource.getrlimit(resource.RLIMIT_CPU)
    require(0 < memory <= MAX_MEMORY and swap == 0 and 0 < pids <= MAX_PIDS,
            "missing hard memory/swap/pid cap")
    require(0 < as_soft <= MAX_AS, "missing address-space rlimit")
    require(0 < fs_soft <= MAX_OUTPUT, "missing output-file rlimit")
    require(0 < cpu_soft <= CPU_SECONDS, "missing CPU-time rlimit")
    return {
        "memory_max_bytes": memory, "memory_swap_max_bytes": swap,
        "pids_max": pids,
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
        "-p", f"TasksMax={MAX_PIDS}",
        timeout, "--signal=TERM", "--kill-after=5s", f"{WALL_SECONDS}s",
        prlimit, f"--as={MAX_AS}:{MAX_AS}",
        f"--fsize={MAX_OUTPUT}:{MAX_OUTPUT}",
        f"--cpu={CPU_SECONDS}:{CPU_SECONDS}", "--",
        sys.executable, str(SCRIPT), *worker_args,
    ]


def _probe() -> dict[str, object]:
    """Run a fabricated-data-free prelaunch check through the real scope command."""
    cmd = _scope_command(
        ["--internal-probe"], unit=f"sf260-90d-probe-{os.getpid()}.scope",
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
        "memory_max_bytes", "memory_swap_max_bytes", "pids_max",
        "as_soft_bytes", "file_soft_bytes", "cpu_soft_seconds",
    ):
        require(type(payload.get(name)) is int, "missing effective limit: " + name)
    require(payload["memory_max_bytes"] <= MAX_MEMORY
            and payload["memory_swap_max_bytes"] == 0
            and payload["pids_max"] <= MAX_PIDS
            and payload["as_soft_bytes"] <= MAX_AS
            and payload["file_soft_bytes"] <= MAX_OUTPUT
            and payload["cpu_soft_seconds"] <= CPU_SECONDS,
            "effective scope limits are outside the registered envelope")
    return payload


def _require_active_parent(profile: str, attempt: int) -> None:
    """Reject a hidden child lacking the actual parent's exclusive flock."""
    output = _private(OUTPUT_ROOT, 0o700)
    marker = _private(output / ".sf260-90d-active.json", 0o600)
    try:
        record = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise LaunchBlocked("missing parent-owned 90D scope marker") from exc
    require(
        type(record) is dict and record.get("schema") == "sf260-90d-active-scope-v1"
        and record.get("profile") == profile and record.get("attempt") == attempt
        and type(record.get("parent_pid")) is int and record["parent_pid"] > 1
        and type(record.get("scope")) is str
        and record["scope"].startswith(f"sf260-90d-{profile.lower()}-a{attempt}-")
        and record["scope"].endswith(".scope"),
        "unrelated or malformed parent-owned scope marker",
    )
    _private(output / ".sf260-90d-launch.lock", 0o600)
    fd = os.open(output / ".sf260-90d-launch.lock", os.O_RDONLY | os.O_NOFOLLOW)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return  # The parent still holds the exclusive flock.
        fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)
    raise LaunchBlocked("internal worker requires active parent launcher flock")


def _worker(profile: str, attempt: int) -> None:
    """Only after distinct Gate D: guarded, source-bound, sealed 90D execution."""
    _limits()  # No source read until cgroup swap/pid/RSS/VM/FSIZE verification.
    _require_active_parent(profile, attempt)
    os.umask(0o077)
    source_dir, attempt_dir = verify_prelaunch(profile, attempt, existing=True)
    attempt_dir = _private(attempt_dir, 0o700)
    sys.path.insert(0, str(ROOT))
    import gc

    from signalforge.config.identity import canonical_config_json
    from signalforge.config.strategy_registry import (
        DEFAULT_STRATEGY_REGISTRY,
        StrategySelection,
    )
    from signalforge.research.audited_source_slice_v1 import (
        IS_START,
        MEASURED_END,
        OOS_START,
        derive_audited_source_slice,
    )
    from signalforge.research.btc_raw_diagnostic_input import load_sf095_raw_diagnostic_source
    from signalforge.research.historical_bars import aggregate_one_minute_to_five_minute
    from signalforge.research.historical_execution import HistoricalExecutionAssumptionProfile
    from signalforge.research.scenario_execution import (
        SF260_90D_VARIANT,
        ScenarioAssumptionSet,
        ScenarioMode,
        ScenarioResearchRequest,
        ScenarioResearchRunner,
        ScenarioResourcePolicy,
        _manifest,
    )

    parent = load_sf095_raw_diagnostic_source(source_dir)
    source = derive_audited_source_slice(parent)
    del parent
    gc.collect()
    require(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024 < MAX_MEMORY,
            "audit-to-slice memory bound exceeded")
    expected_run, expected_sha, manifest_name, expected_source_id, _ = _registration(profile)
    require(source.derivation_id == expected_source_id, "derived source proof drift")
    selection = StrategySelection("btc_momentum_baseline_v0", "0.1.0-experimental", {})
    strategy = DEFAULT_STRATEGY_REGISTRY.resolve(selection)
    raw_profile = (
        HistoricalExecutionAssumptionProfile.reference_raw()
        if profile == "REFERENCE_RAW" else HistoricalExecutionAssumptionProfile.adverse_raw()
    )
    request = ScenarioResearchRequest(
        mode=ScenarioMode.SCENARIO_RESEARCH, source=source,
        strategy_selection=selection, engine_calculation_version="engine-v1",
        assumptions=ScenarioAssumptionSet.btc_ohlc_path_v1(), profile=raw_profile,
        resources=ScenarioResourcePolicy(
            "FINITE_FAIL_CLOSED", "1.0.0", 524160, 2096640, 104833, 2096640, 1,
        ),
        is_start=IS_START, oos_start=OOS_START, measured_end=MEASURED_END,
        repository_revision=_git("rev-parse", "HEAD"),
        study_variant=SF260_90D_VARIANT,
    )
    candles = aggregate_one_minute_to_five_minute(source.dataset)
    planned = _manifest(request, strategy, candles)
    encoded = (canonical_config_json({
        "input_mapping": planned.mapping(), "scenario_run_id": planned.run_id,
    }) + "\n").encode("utf-8")
    require(
        planned.run_id == expected_run
        and hashlib.sha256(encoded).hexdigest() == expected_sha
        and encoded == (PRIVATE_DIR / manifest_name).read_bytes(),
        "approved 90D profile manifest identity differs",
    )
    # Full result is private; OOS is not unsealed by this launcher.
    result = ScenarioResearchRunner().run_verified(request)
    require(result.manifest.run_id == expected_run and not result.execution_valid,
            "scenario evidence tier or prereg identity changed")
    pending = attempt_dir / "partial.json"
    result.write_new(pending)  # Exclusive write; leave partial quarantined on error.
    with pending.open("rb") as stream:
        os.fsync(stream.fileno())
    require(pending.stat().st_size <= MAX_OUTPUT, "canonical result exceeds output ceiling")
    receipt = {
        "status": "CANONICAL_WRITE_COMPLETED_METHOD_UNASSESSED",
        "variant": "SF260_90D_AUDITED_V1",
        "profile": profile, "attempt": attempt,
        "scenario_run_id": expected_run,
        "canonical_sha256": _sha256(pending),
        "canonical_bytes": pending.stat().st_size,
        "execution_valid": False,
        "oos_released": False,
    }
    _write_private_json(attempt_dir / "worker-receipt.json", receipt)

def _scope_inactive(unit: str) -> bool:
    """Trust only an explicitly readable inactive/removed systemd unit state."""
    try:
        check = subprocess.run(
            ["systemctl", "--user", "show", unit,
             "--property=ActiveState", "--property=LoadState", "--no-pager"],
            capture_output=True, text=True, check=False, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    if check.returncode != 0:
        return False
    states: dict[str, str] = {}
    for line in check.stdout.splitlines():
        if "=" not in line:
            return False
        key, value = line.split("=", 1)
        if key in states:
            return False
        states[key] = value
    return (set(states) == {"ActiveState", "LoadState"}
            and states["ActiveState"] in {"inactive", "failed"}
            and states["LoadState"] in {"loaded", "not-found"})


def _wait_scope_inactive(unit: str) -> bool:
    """Allow bounded asynchronous teardown after a successful scope client exit."""
    for attempt in range(10):
        if _scope_inactive(unit):
            return True
        if attempt != 9:
            time.sleep(0.2)
    return False


def _stop_scope(unit: str) -> bool:
    """Ask systemd to stop, then require a separately confirmed inactive state."""
    try:
        subprocess.run(
            ["systemctl", "--user", "stop", unit], capture_output=True,
            check=False, timeout=20,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    # Stop can report 'not found' for an already collected scope. A successful
    # explicit state query, not the stop return code, is the decisive evidence.
    return _scope_inactive(unit)


@contextmanager
def _exclusive_operator_launch() -> Iterator[Path]:
    """One cross-profile launch at a time; retain a crash/unknown-scope marker."""
    output = _private(OUTPUT_ROOT, 0o700)
    flags = os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW
    fd = os.open(output / ".sf260-90d-launch.lock", flags, 0o600)
    try:
        os.fchmod(fd, 0o600)
        require(stat.S_ISREG(os.fstat(fd).st_mode), "launch lock is not a file")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise LaunchBlocked("another Stage 6 attempt is in progress") from exc
        marker = output / ".sf260-90d-active.json"
        require(not marker.exists() and not marker.is_symlink(),
                "previous launch state unresolved; verify the scope before proceeding")
        yield marker
    finally:
        os.close(fd)


def _write_private_json(path: Path, record: dict[str, object]) -> None:
    """Exclusive 0600 JSON evidence even under a permissive parent umask."""
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
    fd = os.open(path, flags, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        os.fchmod(stream.fileno(), 0o600)
        json.dump(record, stream, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def _signal_abort(_signal: int, _frame: object) -> None:
    """Turn catchable parent termination into a quarantined failure."""
    raise KeyboardInterrupt


def _parent_run(profile: str, attempt: int) -> dict[str, object]:
    """Enforce cross-profile exclusivity before resource/headroom admission."""
    with _exclusive_operator_launch() as marker:
        return _parent_run_locked(profile, attempt, marker)


def _parent_run_locked(profile: str, attempt: int, marker: Path) -> dict[str, object]:
    """Launch exactly one scope, retaining uncertainty until manual resolution."""
    _, path = verify_prelaunch(profile, attempt)
    _probe()  # Actual scope command, with no source access, always checked first.
    unit = f"sf260-90d-{profile.lower()}-a{attempt}-{os.getpid()}.scope"
    command = _scope_command(
        ["--internal-worker", "--profile", profile, "--attempt", str(attempt)],
        unit=unit,
    )
    path.mkdir(mode=0o700)  # Exclusive; no reuse of a failed attempt.
    # If this parent dies unexpectedly, the marker survives flock release and
    # blocks a new attempt until the operator checks the named scope.
    _write_private_json(marker, {
        "schema": "sf260-90d-active-scope-v1", "scope": unit,
        "profile": profile, "attempt": attempt, "parent_pid": os.getpid(),
    })
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
    # Even a successful client exit is insufficient evidence of an empty scope.
    # Allow systemd's asynchronous cleanup briefly, then require an explicit stop.
    stopped = (_wait_scope_inactive(unit) or _stop_scope(unit)
               if exit_code == 0 else _stop_scope(unit))
    receipt_path = path / "worker-receipt.json"
    pending = path / "partial.json"
    if stopped and exit_code == 0 and receipt_path.is_file() and pending.is_file():
        try:
            _private(receipt_path, 0o600)
            _private(pending, 0o600)
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            expected_run = _registration(profile)[0]
            require(
                receipt == {
                    "status": "CANONICAL_WRITE_COMPLETED_METHOD_UNASSESSED",
                    "variant": "SF260_90D_AUDITED_V1",
                    "profile": profile, "attempt": attempt,
                    "scenario_run_id": expected_run,
                    "canonical_sha256": _sha256(pending),
                    "canonical_bytes": pending.stat().st_size,
                    "execution_valid": False, "oos_released": False,
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
            marker.unlink()  # Confirmed stopped and canonical receipt verified.
            return {
                "status": "CANONICAL_RESULT_PRIVATE_NOT_RELEASED",
                "profile": profile, "attempt": attempt,
                "sha256": receipt["canonical_sha256"],
                "bytes": receipt["canonical_bytes"],
                "result_file": str(completed),
                "gate_e_approved": False, "oos_released": False,
            }
        except (OSError, ValueError, LaunchBlocked):
            pass
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
    _write_private_json(path / "failure.json", failure)
    if stopped:
        marker.unlink()
    # On unknown scope state the marker persists after the flock is released,
    # blocking *all* further attempt launches rather than trusting a dead parent.
    return failure


def main(argv: list[str] | None = None) -> int:
    """Verify limits without historical access, or explicitly launch one attempt."""
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--probe", action="store_true", help="safe default, no protected access")
    mode.add_argument("--run", action="store_true",
                      help="protected attempt requires separate later 00.01 Gate D_90D_ACCEPT")
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
