"""SF-296 prospective guarded synthetic-only v2 evidence operator.

NO PROTECTED SOURCE MODE. NO economic reporting, OOS publication, or Gate D.
All result and companion bytes remain private. Real systemd-scoped execution is
mandatory for an admitted synthetic attempt; a CI mock is not operational proof.
"""

from __future__ import annotations

import argparse
import ctypes
import fcntl
import hashlib
import json
import os
import resource
import secrets
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from signalforge.research.scenario_execution import ScenarioResearchRequest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = Path(__file__).resolve()
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CONTRACT = "sf293-slice1-evidence-status-v1"
TIER = "CONTROLLED_SYNTHETIC_T1_T2_NOT_HISTORICAL"
MEMORY = 3 * 1024**3
ADDRESS = 4 * 1024**3
FILE_LIMIT = 512 * 1024**2
PIDS = 64
SECONDS = 1200
PROFILES = ("REFERENCE_RAW", "ADVERSE_RAW")
FILES = ("source-quality.json", "strict-reference.json", "scenario-result.json")
WORKER_RECEIPT = "worker-receipt.json"
COMMIT_SCHEMA = "sf296-complete-set-v1"
MARKER = ".sf296-active.json"
LOCK = ".sf296-launch.lock"


class SafeArgumentParser(argparse.ArgumentParser):
    """Normalize bad arguments to one non-sensitive status response."""

    def error(self, message: str) -> None:
        raise OperatorBlocked("INVALID_ARGUMENT")


class OperatorBlocked(RuntimeError):
    """Unsafe admission, incomplete custody or failed trusted invocation."""


def require(ok: bool) -> None:
    """Reject without exposing a dynamic value in any user-facing channel."""
    if not ok:
        raise OperatorBlocked("BLOCKED")


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _git(*args: str) -> str:
    done = subprocess.run(
        ["git", "-C", str(ROOT), *args], capture_output=True, check=False,
        timeout=20,
    )
    require(done.returncode == 0)
    return done.stdout.decode("utf-8").strip()


def _checkout() -> str:
    head = _git("rev-parse", "HEAD")
    require(not _git("status", "--porcelain"))
    require(_git("rev-parse", "--show-toplevel") == str(ROOT))
    return head


def _private(path: Path, mode: int, *, root: Path | None = None) -> Path:
    """Require existing private path and reject symlink aliases and hardlinks."""
    raw = path.absolute()
    resolved = raw.resolve(strict=True)
    require(raw == resolved and stat.S_IMODE(resolved.stat().st_mode) == mode)
    require(resolved.is_dir() if mode == 0o700 else resolved.is_file())
    if mode == 0o600:
        require(resolved.stat().st_nlink == 1)
    require(not resolved.is_relative_to(ROOT))
    require(not any(token in (".signalforge-data", "sf088", "sf096", "stage6")
                    for token in resolved.parts))
    if root is not None:
        require(resolved.is_relative_to(root))
    return resolved


def _root(path: Path) -> Path:
    return _private(path, 0o700)


def _name(profile: str, attempt: int) -> str:
    require(profile in PROFILES and attempt in (1, 2))
    return f"{profile.lower()}-attempt-{attempt}"


def _write(path: Path, data: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        os.fchmod(stream.fileno(), 0o600)
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def _json(path: Path, value: dict[str, object]) -> None:
    _write(path, (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode())


def _read(path: Path, *, root: Path) -> bytes:
    _private(path, 0o600, root=root)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        before = os.fstat(fd)
        require(before.st_nlink == 1 and 0 < before.st_size <= FILE_LIMIT)
        with os.fdopen(fd, "rb", closefd=False) as stream:
            raw = stream.read(FILE_LIMIT + 1)
        after = os.fstat(fd)
        require(before.st_ino == after.st_ino and before.st_size == after.st_size
                and before.st_mtime_ns == after.st_mtime_ns
                and len(raw) == before.st_size)
        return raw
    finally:
        os.close(fd)


def _record(path: Path, *, root: Path) -> dict[str, Any]:
    raw = _read(path, root=root)
    value = json.loads(raw)
    require(type(value) is dict)
    return value


def _sync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _no_replace_directory(source: Path, target: Path) -> None:
    """Linux atomic same-filesystem rename without destination replacement."""
    require(source.parent == target.parent and not target.exists())
    libc = ctypes.CDLL(None, use_errno=True)
    syscall = libc.renameat2
    syscall.argtypes = [
        ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p,
        ctypes.c_uint,
    ]
    syscall.restype = ctypes.c_int
    result = syscall(-100, os.fsencode(source), -100, os.fsencode(target), 1)
    if result != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))


def _limits() -> None:
    """Verify actual in-scope Linux controls, not requested command flags."""
    cg = next((
        line.split("::", 1)[1] for line in
        Path("/proc/self/cgroup").read_text(encoding="ascii").splitlines()
        if line.startswith("0::")
    ), None)
    require(isinstance(cg, str))
    directory = Path("/sys/fs/cgroup") / cg.lstrip("/")
    require(0 < int((directory / "memory.max").read_text()) <= MEMORY)
    require(int((directory / "memory.swap.max").read_text()) == 0)
    require(0 < int((directory / "pids.max").read_text()) <= PIDS)
    require(0 < resource.getrlimit(resource.RLIMIT_AS)[0] <= ADDRESS)
    require(0 < resource.getrlimit(resource.RLIMIT_FSIZE)[0] <= FILE_LIMIT)
    require(0 < resource.getrlimit(resource.RLIMIT_CPU)[0] <= SECONDS)


def _command(profile: str, attempt: int, root: Path, scope: str) -> list[str]:
    tools = [shutil.which(x) for x in ("systemd-run", "timeout", "prlimit")]
    require(all(tools))
    systemd, timeout, prlimit = tools
    assert systemd and timeout and prlimit
    return [
        systemd, "--user", "--scope", "--quiet", "--collect",
        "--slice=sf296.slice", f"--unit={scope}", "-p", f"MemoryMax={MEMORY}",
        "-p", "MemorySwapMax=0", "-p", f"TasksMax={PIDS}",
        timeout, "--signal=TERM", "--kill-after=5s", f"{SECONDS}s",
        prlimit, f"--as={ADDRESS}:{ADDRESS}",
        f"--fsize={FILE_LIMIT}:{FILE_LIMIT}",
        f"--cpu={SECONDS}:{SECONDS}", "--",
        sys.executable, str(SCRIPT), "--internal-worker",
        "--root", str(root), "--profile", profile, "--attempt", str(attempt),
    ]


def _inactive(scope: str) -> bool:
    """Positive explicit inactivity confirmation; command failure is not success."""
    done = subprocess.run(
        ["systemctl", "--user", "show", scope, "--property=ActiveState",
         "--property=SubState", "--no-pager"],
        capture_output=True, timeout=15, check=False,
    )
    if done.returncode != 0:
        # Removed transient scope has no active process only when show confirms
        # the unit is unknown, not merely when systemctl fails.
        return False
    fields = dict(line.split("=", 1) for line in done.stdout.decode().splitlines()
                  if "=" in line)
    return fields.get("ActiveState") == "inactive" and fields.get("SubState") in (
        "dead", "failed",
    )


def _stop(scope: str) -> bool:
    subprocess.run(
        ["systemctl", "--user", "stop", scope],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        timeout=15, check=False,
    )
    for _ in range(5):
        if _inactive(scope):
            return True
    return False


def _fixture_and_request(profile: str, revision: str) -> ScenarioResearchRequest:
    """Generate only embedded artificial bars; do not accept a source path."""
    from dataclasses import replace
    from datetime import UTC, datetime, timedelta
    from decimal import Decimal

    from signalforge.config.strategy_registry import StrategySelection
    from signalforge.domain.ids import InstrumentId
    from signalforge.domain.money import Price
    from signalforge.domain.time import CandleInterval
    from signalforge.research.btc_raw_diagnostic_input import RawDiagnosticSource
    from signalforge.research.historical_bars import (
        HistoricalBarDataset,
        HistoricalPriceBasis,
        load_historical_bar_fixture,
    )
    from signalforge.research.historical_execution import (
        HistoricalExecutionAssumptionProfile,
    )
    from signalforge.research.historical_grid import HistoricalBarGrid
    from signalforge.research.scenario_execution import (
        ScenarioAssumptionSet,
        ScenarioMode,
        ScenarioResearchRequest,
        ScenarioResourcePolicy,
    )

    public = ROOT / "examples/research/historical-bars-one-session.json"
    require(public.is_file() and public.resolve().is_relative_to(ROOT / "examples"))
    legacy = load_historical_bar_fixture(public)
    original = legacy.bars[0]
    start = datetime(2026, 11, 1, 2, 55, tzinfo=UTC)
    minutes = 1300
    instrument = InstrumentId("DELTA:BTCUSD")
    bars = tuple(
        replace(
            original, instrument_id=instrument,
            interval=CandleInterval(
                start + timedelta(minutes=i), start + timedelta(minutes=i + 1),
            ),
            open=Price(Decimal("100")), high=Price(Decimal("100.05")),
            low=Price(Decimal("99.95")), close=Price(Decimal("100")),
            provider_timestamp_raw=(start + timedelta(minutes=i)).isoformat(),
            provider_timestamp_interpreted=start + timedelta(minutes=i),
        )
        for i in range(minutes)
    )
    manifest = replace(
        legacy.manifest, instrument_id=instrument,
        requested_instrument="BTCUSD", resolved_provider_instrument="BTCUSD",
        expected_session_dates=(), price_basis=HistoricalPriceBasis.TRADED,
        limitations=("UNQUALIFIED_HISTORICAL_METADATA", "SYNTHETIC_TEST_ONLY"),
        grid=HistoricalBarGrid(
            "scenario-synthetic", "1",
            (CandleInterval(start, start + timedelta(minutes=minutes)),),
        ),
        requested_start=start, requested_end=start + timedelta(minutes=minutes),
        returned_start=start, returned_end=start + timedelta(minutes=minutes),
        raw_row_count=minutes, canonical_row_count=minutes,
        missing_interval_count=0, duplicate_observation_count=0,
        corrupt_rejected_count=0,
    )
    source = RawDiagnosticSource(
        HistoricalBarDataset(manifest, bars), "synthetic-sf296",
    )
    execution_profile = (
        HistoricalExecutionAssumptionProfile.reference_raw()
        if profile == "REFERENCE_RAW"
        else HistoricalExecutionAssumptionProfile.adverse_raw()
    )
    return ScenarioResearchRequest(
        mode=ScenarioMode.SCENARIO_RESEARCH, source=source,
        strategy_selection=StrategySelection(
            "btc_momentum_baseline_v0", "0.1.0-experimental", {},
        ),
        engine_calculation_version="engine-v1",
        assumptions=ScenarioAssumptionSet.btc_ohlc_path_v1(),
        profile=execution_profile,
        resources=ScenarioResourcePolicy(
            "FINITE_FAIL_CLOSED", "1.0.0", 100, 1000, 1000, 1000, 1,
        ),
        is_start=start + timedelta(minutes=1250),
        oos_start=start + timedelta(minutes=1255),
        measured_end=start + timedelta(minutes=minutes),
        repository_revision=revision,
        synthetic_fixture_identity="synthetic-sf296-flat-v1",
    )


def _saved_ids(raw: bytes) -> dict[str, object]:
    """Re-derive private content identities from canonical bytes, not memory."""
    from signalforge.research.scenario_reportability import (
        FUTURE_FIELDS,
        _decode_canonical,
        _identity,
        _items,
        _map,
    )

    envelope = _decode_canonical(raw)
    manifest = _map(envelope.get("manifest"), "manifest")
    result = _map(envelope.get("result"), "result")
    legacy = dict(result)
    legacy["schema_version"] = "scenario-result-v1"
    del legacy["report_contract"]
    del legacy["companion_sha256"]
    legacy["outcomes"] = [
        {key: val for key, val in row.items() if key not in FUTURE_FIELDS}
        for row in _items(result.get("outcomes"), "outcomes")
    ]
    source = _map(manifest.get("source"), "source")
    return {
        "scenario_run_id": _identity({"domain": "scenario-run-v1", "inputs": manifest}),
        "scenario_result_v1_id": _identity(
            {"domain": "scenario-result-v1", "result": legacy},
        ),
        "scenario_result_v2_id": envelope.get("scenario_result_id"),
        "source_diagnostic_id": source.get("source_diagnostic_id"),
    }


def _worker(root: Path, profile: str, attempt: int) -> None:
    """Run only when active parent owns live lock under the real cgroup."""
    _limits()
    name = _name(profile, attempt)
    root = _root(root)
    marker = _record(root / MARKER, root=root)
    require(marker.get("profile") == profile and marker.get("attempt") == attempt)
    require(marker.get("revision") == _checkout())
    require(type(marker.get("nonce")) is str and len(marker["nonce"]) == 32)
    require(type(marker.get("scope")) is str and marker["scope"].startswith("sf296-"))
    lockfd = os.open(root / LOCK, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        try:
            fcntl.flock(lockfd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            pass
        else:
            fcntl.flock(lockfd, fcntl.LOCK_UN)
            raise OperatorBlocked("NO_GUARDED_PARENT")
    finally:
        os.close(lockfd)
    os.umask(0o077)
    stage = _private(root / (name + ".staging"), 0o700, root=root)
    from signalforge.research.scenario_execution import ScenarioResearchRunner
    from signalforge.research.scenario_report_evidence import write_source_quality_evidence
    from signalforge.research.strict_reference_producer import produce_strict_reference_evidence

    request = _fixture_and_request(profile, marker["revision"])
    result = ScenarioResearchRunner().run_verified(request)
    require(not result.execution_valid)
    source = stage / FILES[0]
    strict = stage / FILES[1]
    canonical = stage / FILES[2]
    write_source_quality_evidence(request, result, source)
    produce_strict_reference_evidence(request, result, strict)
    result.write_reportable_new(
        canonical, source_companion=source, strict_companion=strict,
    )
    for item in FILES:
        fd = os.open(stage / item, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    from signalforge.research.prospective_saved_verifier import verify_v2_structure
    blobs = [_read(stage / item, root=root) for item in FILES]
    disposition = verify_v2_structure(blobs[2], blobs[0], blobs[1])
    receipt = {
        "schema": "sf296-worker-receipt-v1",
        "nonce": marker["nonce"], "scope": marker["scope"],
        "revision": marker["revision"], "profile": profile,
        "attempt": attempt, "source_kind": "SYNTHETIC_TEST_ONLY",
        "source_producer": "canonical-source-grid-classifier-v1",
        "strict_producer": "adr011-fail-closed-independent-strict-v1",
        "writer": "scenario-result-v2",
        "identities": _saved_ids(blobs[2]),
        "disposition": disposition,
        "files": {
            item: {"sha256": _sha(raw), "bytes": len(raw)}
            for item, raw in zip(FILES, blobs, strict=True)
        },
    }
    _json(stage / WORKER_RECEIPT, receipt)
    _sync_dir(stage)


def _verify_set(root: Path, name: str) -> str:
    """T1 bytes plus T2 parent-committed controlled lineage; no economics."""
    from signalforge.research.prospective_saved_verifier import verify_v2_structure

    root = _root(root)
    require(not (root / MARKER).exists())
    completed = _private(root / name, 0o700, root=root)
    require({x.name for x in completed.iterdir()} == set(FILES) | {WORKER_RECEIPT})
    ack = _record(root / (name + ".complete.json"), root=root)
    receipt_raw = _read(completed / WORKER_RECEIPT, root=root)
    receipt = json.loads(receipt_raw)
    require(type(receipt) is dict)
    require(receipt.get("schema") == "sf296-worker-receipt-v1"
            and ack.get("schema") == COMMIT_SCHEMA
            and ack.get("receipt_sha256") == _sha(receipt_raw)
            and ack.get("name") == name
            and ack.get("scope_confirmed_inactive") is True
            and ack.get("revision") == _checkout()
            and receipt.get("revision") == ack["revision"]
            and receipt.get("nonce") == ack.get("nonce")
            and receipt.get("scope") == ack.get("scope")
            and receipt.get("source_kind") == "SYNTHETIC_TEST_ONLY"
            and receipt.get("writer") == "scenario-result-v2"
            and receipt.get("source_producer") == "canonical-source-grid-classifier-v1"
            and receipt.get("strict_producer") ==
                "adr011-fail-closed-independent-strict-v1")
    require(name == _name(receipt["profile"], receipt["attempt"]))
    records = receipt.get("files")
    require(type(records) is dict and set(records) == set(FILES))
    blobs = []
    for filename in FILES:
        raw = _read(completed / filename, root=root)
        require(records[filename] == {"sha256": _sha(raw), "bytes": len(raw)})
        blobs.append(raw)
    actual = verify_v2_structure(blobs[2], blobs[0], blobs[1])
    require(receipt.get("identities") == _saved_ids(blobs[2]))
    require(actual == receipt["disposition"])
    return actual


def _parent(root: Path, profile: str, attempt: int) -> str:
    root = _root(root)
    revision = _checkout()
    name = _name(profile, attempt)
    lockfd = os.open(root / LOCK, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        os.fchmod(lockfd, 0o600)
        fcntl.flock(lockfd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        require(not (root / MARKER).exists())
        require(not any((root / x).exists() for x in (
            name, name + ".staging", name + ".complete.json",
        )))
        scope = f"sf296-{profile.lower()}-a{attempt}-{os.getpid()}.scope"
        command = _command(profile, attempt, root, scope)
        nonce = secrets.token_hex(16)
        stage = root / (name + ".staging")
        stage.mkdir(mode=0o700)
        _json(root / MARKER, {
            "schema": "sf296-active-parent-v1", "nonce": nonce,
            "scope": scope, "profile": profile, "attempt": attempt,
            "revision": revision, "parent_pid": os.getpid(),
        })
        _sync_dir(root)
        exit_code = 127
        try:
            with open(os.devnull, "wb") as quiet:
                process = subprocess.run(
                    command, stdout=quiet, stderr=quiet, timeout=SECONDS + 45,
                    check=False,
                )
            exit_code = process.returncode
        except (OSError, subprocess.TimeoutExpired):
            pass
        inactive = _stop(scope)
        if exit_code != 0 or not inactive:
            # Preserve active marker when scope status cannot be established.
            if inactive:
                (root / MARKER).unlink()
                _sync_dir(root)
            raise OperatorBlocked("WORKER_OR_SCOPE_FAILED")
        worker_raw = _read(stage / WORKER_RECEIPT, root=root)
        receipt = json.loads(worker_raw)
        require(receipt.get("nonce") == nonce
                and receipt.get("scope") == scope
                and receipt.get("revision") == revision
                and receipt.get("profile") == profile
                and receipt.get("attempt") == attempt)
        blobs = [_read(stage / x, root=root) for x in FILES]
        require(receipt["files"] == {
            item: {"sha256": _sha(raw), "bytes": len(raw)}
            for item, raw in zip(FILES, blobs, strict=True)
        })
        from signalforge.research.prospective_saved_verifier import verify_v2_structure
        disposition = verify_v2_structure(blobs[2], blobs[0], blobs[1])
        require(disposition == receipt["disposition"])
        require(receipt.get("identities") == _saved_ids(blobs[2]))
        _sync_dir(stage)
        _no_replace_directory(stage, root / name)
        _sync_dir(root)
        # Completion ack is a distinct durable parent assertion, never written
        # by the worker. It is necessary *in addition* to the renamed set.
        _json(root / (name + ".complete.json"), {
            "schema": COMMIT_SCHEMA, "name": name,
            "nonce": nonce, "scope": scope, "revision": revision,
            "scope_confirmed_inactive": True,
            "receipt_sha256": _sha(worker_raw),
        })
        _sync_dir(root)
        # The no-replace set and completion acknowledgement are now durable.
        # Removing the in-progress marker is post-commit housekeeping, not an
        # additional commit boundary. A failed cleanup fsync must not turn a
        # confirmed commit into an apparently failed (later verifiable) run.
        (root / MARKER).unlink()
        try:
            _sync_dir(root)
        except OSError:
            # Marker removal may be durable or not after a crash. The current
            # process can verify the committed bytes, but restart admission
            # still fails closed if the marker reappears.
            pass
        return _verify_set(root, name)
    finally:
        os.close(lockfd)


def _status(status: str) -> dict[str, object]:
    return {
        "contract": CONTRACT,
        "status": status, "source_kind": "SYNTHETIC_TEST_ONLY",
        "verification_tier": TIER if status == "NON_ECONOMIC_EVIDENCE_VERIFIED"
        else "NOT_VERIFIED",
        "economics": "WITHHELD", "oos": "SEALED",
        "gate_d_approved": False, "gate_e_approved": False,
        "execution_valid": False,
    }


def main(argv: list[str] | None = None) -> int:
    """Emit exactly one restricted, fixed-shape JSON record; never partial data."""
    parser = SafeArgumentParser(description=__doc__, add_help=False)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--run-synthetic", action="store_true")
    modes.add_argument("--verify", action="store_true")
    modes.add_argument("--internal-worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--root", type=Path)
    parser.add_argument("--profile", choices=PROFILES)
    parser.add_argument("--attempt", type=int, choices=(1, 2))
    try:
        args = parser.parse_args(argv)
        if args.run_synthetic or args.verify or args.internal_worker:
            require(args.root is not None and args.profile is not None
                    and args.attempt is not None)
            if args.internal_worker:
                _worker(args.root, args.profile, args.attempt)
                return 0  # Child stdout is swallowed by guarded parent.
            if args.run_synthetic:
                result = _parent(args.root, args.profile, args.attempt)
            else:
                result = _verify_set(
                    args.root, _name(args.profile, args.attempt),
                )
            status = (
                "NON_ECONOMIC_EVIDENCE_VERIFIED" if result == "COMPLETE" else "WITHHELD"
            )
        else:
            require(not any((
                args.root is not None, args.profile is not None,
                args.attempt is not None,
            )))
            _checkout()
            # A probe never loads bars or accesses any protected root.
            status = "WITHHELD"
    except Exception:
        # No exception, path, hash, profile, source, OOS or metric escapes.
        status = "VALIDATION_BLOCKED"
    print(json.dumps(_status(status), sort_keys=True, separators=(",", ":")))
    return {"NON_ECONOMIC_EVIDENCE_VERIFIED": 0, "WITHHELD": 2,
            "VALIDATION_BLOCKED": 1}[status]


if __name__ == "__main__":
    sys.exit(main())
