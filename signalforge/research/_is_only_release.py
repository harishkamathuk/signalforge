"""Private SF-293 Slice 3 synthetic-only IS release projection.

Full canonical/producer/lifecycle admission is private. The public view uses
only facts observable by the IS cutoff, never the full SF-283/Slice-2 report.
This component proves a TEST_ONLY contract, not protected economic release.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from typing import Any

from scripts.sf296_guarded_v2 import _private, _read, _root
from signalforge.research._synthetic_cost_r import (
    _SyntheticCostBlocked,
    _aggregate,
    _cost_model,
    _decimal,
    _trade_math,
)
from signalforge.research.prospective_saved_verifier import (
    EvidenceBlocked,
    verify_v2_structure,
)
from signalforge.research.scenario_reportability import (
    ReportabilityError,
    _count,
    _decode_canonical,
    _economics,
    _items,
    _map,
    _number,
    _source_quality,
    _strict_reference,
    _utc,
)

_REPORT_CONTRACT = "sf293-slice3-synthetic-is-only-v1"
_GRANT_CONTRACT = "sf293-slice3-test-only-local-grant-v1"
_FILES = frozenset({
    "scenario-result.json", "source-quality.json", "strict-reference.json",
    "test-cost-assumptions.json", "test-only-grant.json",
})
_IS_SCOPE = frozenset({"IS"})
_SAFE_LABEL = re.compile(r"^[a-z0-9][a-z0-9_-]{0,47}$")


class _ReleaseDenied(ValueError):
    """A fixed external disposition without any private data."""

    def __init__(self, disposition: str = "RELEASE_BLOCKED") -> None:
        super().__init__(disposition)
        self.disposition = disposition


def _need(ok: bool) -> None:
    if not ok:
        raise _ReleaseDenied()


def _time(value: object) -> datetime:
    _need(type(value) is str)
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise _ReleaseDenied() from exc
    _need(parsed.tzinfo is not None and parsed.utcoffset() == timedelta(0))
    return parsed


def _load_json(raw: bytes) -> dict[str, Any]:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            _need(key not in value)
            value[key] = item
        return value

    try:
        result = json.loads(raw, object_pairs_hook=unique)
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise _ReleaseDenied() from exc
    _need(type(result) is dict)
    return result


def _admit_grant(
    grant: dict[str, Any], raw: tuple[bytes, bytes, bytes, bytes],
    recipient: str, document: dict[str, Any],
) -> None:
    """Exact independently rebound *local mock* study grant; never historical."""
    fields = {
        "contract", "grant_kind", "grant_id", "study_id", "matrix_revision",
        "approved", "revoked", "recipient", "scope", "not_before", "expires",
        "repository_revision", "profile_id", "scenario_result_id",
        "is_start", "oos_start", "cost_model_id", "cost_model_version",
        "result_sha256", "source_sha256", "strict_sha256", "cost_sha256",
    }
    _need(set(grant) == fields)
    _need(
        grant["contract"] == _GRANT_CONTRACT
        and grant["grant_kind"] == "SYNTHETIC_TEST_ONLY_LOCAL_FIXTURE"
        and grant["approved"] is True
        and grant["revoked"] is False
        and grant["scope"] == "IS_ONLY"
        and grant["recipient"] == recipient
        and all(type(grant[k]) is str and bool(_SAFE_LABEL.fullmatch(grant[k]))
                for k in ("grant_id", "study_id", "matrix_revision", "recipient"))
    )
    now = datetime.now(timezone.utc)
    _need(_time(grant["not_before"]) <= now < _time(grant["expires"]))
    _need(
        grant["result_sha256"] == sha256(raw[0]).hexdigest()
        and grant["source_sha256"] == sha256(raw[1]).hexdigest()
        and grant["strict_sha256"] == sha256(raw[2]).hexdigest()
        and grant["cost_sha256"] == sha256(raw[3]).hexdigest()
    )
    manifest = _map(document.get("manifest"), "manifest")
    fills = _map(manifest.get("fills"), "fills")
    implementation = _map(manifest.get("implementation"), "implementation")
    windows = _map(manifest.get("session_and_window"), "windows")
    _need(
        grant["scenario_result_id"] == document.get("scenario_result_id")
        and grant["repository_revision"] == implementation.get("revision")
        and grant["profile_id"] == fills.get("profile_id")
        and grant["is_start"] == windows.get("is_start")
        and grant["oos_start"] == windows.get("oos_start")
    )


def _is_projection(
    document: bytes, source_bytes: bytes, strict_bytes: bytes,
    cost_bytes: bytes, grant: dict[str, Any], recipient: str,
) -> dict[str, object]:
    """Release an explicit aggregate IS view after private full-set admission."""
    # The permit is bound to the *original* canonical bytes, not a derived
    # "IS-repaired" result. Each valid OOS variant needs a separate grant.
    envelope = _decode_canonical(document)
    _admit_grant(
        grant, (document, source_bytes, strict_bytes, cost_bytes), recipient,
        envelope,
    )
    assumptions = _load_json(cost_bytes)
    try:
        fees, _, valid_from, valid_until = _cost_model(assumptions)
    except _SyntheticCostBlocked as exc:
        if exc.disposition == "WITHHELD":
            raise _ReleaseDenied("WITHHELD") from exc
        raise _ReleaseDenied() from exc
    _need(
        grant["cost_model_id"] == assumptions.get("model_id")
        and grant["cost_model_version"] == assumptions.get("model_version")
    )

    # FULL is unchanged for existing SF-296 users. IS is a private opt-in:
    # validate original FULL canonical/companion hashes, independent producer
    # proof, complete lifecycle and trace, but qualify source/strict *science*
    # only for IS. Genuine OOS-only scientific deficits are not corruption.
    disposition = verify_v2_structure(
        document, source_bytes, strict_bytes, science_scope="IS",
    )
    if disposition == "WITHHELD":
        raise _ReleaseDenied("WITHHELD")
    _need(disposition == "COMPLETE")

    manifest = _map(envelope["manifest"], "manifest")
    result = _map(envelope["result"], "result")
    windows = _map(manifest["session_and_window"], "windows")
    start, split, finish = (
        _utc(windows[key])
        for key in ("is_start", "oos_start", "measured_end")
    )
    _need(valid_from <= start and valid_until >= finish)
    bounds = {"IS": (start, split), "OOS": (split, finish)}
    # These functions also check OOS mask/count/proof *structure*, without
    # using any OOS science outcome as the public IS qualification.
    companion_binding = _map(result["companion_sha256"], "companion_sha256")
    _need(set(companion_binding) == {"source_quality", "strict_reference"})
    source = _decode_canonical(source_bytes)
    strict = _decode_canonical(strict_bytes)
    source_counts = _source_quality(
        source, bounds, qualified_windows=_IS_SCOPE,
    )["IS"]
    strict_counts = _strict_reference(
        strict, bounds, manifest, qualified_windows=_IS_SCOPE,
    )["IS"]

    expected = int((split - start) / timedelta(minutes=5))
    observed = _count(result["is_observed"])
    _need(observed == expected)

    accepted = 0
    censored = Counter[str]()
    completed = Counter[str]()
    contained: list[dict[str, Any]] = []
    entry_count = 0
    exit_count = 0
    # Final state is a private full-run fact; the public state is reconstructed
    # at the IS cutoff. Never copy SF-283 lifecycle_by_signal_window.IS.
    for row in _items(result["outcomes"], "outcomes"):
        signaled = _utc(row["signal_interval_end"])
        if not start < signaled <= split:
            continue
        accepted += 1
        terminal = _utc(row["terminal_event_bucket"])
        entered = (None if row["entry_bucket"] is None
                   else _utc(row["entry_bucket"]))
        exited = (None if row["exit_bucket"] is None
                  else _utc(row["exit_bucket"]))
        if entered is not None and entered < split:
            entry_count += 1
        if exited is not None and exited < split:
            exit_count += 1
        if terminal >= split:
            censored["OPEN" if entered is not None and entered < split
                     else "ARMED"] += 1
            continue
        state = row["state"]
        _need(state in ("CLOSED", "EXPIRED", "REJECTED"))
        completed[state] += 1
        if state == "CLOSED":
            _need(entered is not None and exited is not None
                  and entered < split and exited < split)
            contained.append(row)

    blocked = sum(
        start < _utc(row["interval_end"]) <= split
        for row in _items(result["blocked_decisions"], "blocked")
    )
    # All CLOSED contained opportunities are cost-qualified identically in
    # gross and adjusted R. OOS-only missing funding is NOT an IS deficit.
    event_map: dict[str, list[dict[str, Any]]] = {}
    for record in assumptions["funding_events"]:
        _need(type(record) is dict)
        event_map.setdefault(record["opportunity_id"], []).append(record)

    adjusted: list[dict[str, Any]] = []
    for outcome in contained:
        oid = outcome["opportunity_id"]
        rows = event_map.get(oid, [])
        if not rows:
            raise _ReleaseDenied("WITHHELD")
        entry = _utc(outcome["entry_bucket"])
        exit_at = _utc(outcome["exit_bucket"])
        _need(all(
            entry <= _utc(event["bucket"]) <= exit_at
            for event in rows
        ))
        funding = sum((_decimal(e["signed_debit_quote"]) for e in rows),
                      Decimal(0))
        math = _trade_math(
            entry=_number(outcome["entry_price"]),
            stop=_number(outcome["modeled_stop_price"]),
            exit=_number(outcome["exit_price"]),
            entry_rate=fees["ENTRY_FEE"],
            exit_rate=fees["EXIT_FEE"],
            funding_debit=funding,
        )
        _need(math["gross_r"] == _number(outcome["r"]))
        adjusted.append({
            "exit_bucket": outcome["exit_bucket"],
            **{key: str(value) for key, value in math.items()},
        })

    gross = _economics(contained, expected, observed)
    net = _aggregate(adjusted, expected)
    # A fresh closed allowlist, with no generic dict projection of rich
    # full-window report, no trade array, and no OOS-derived identifier.
    return {
        "contract": _REPORT_CONTRACT,
        "status": "IS_ONLY_QUALIFIED",
        "window": "IS",
        "oos": "SEALED",
        "certainty": "SCENARIO_CONDITIONED",
        "execution_valid": False,
        "study_outcome": "NOT_PREREGISTERED",
        "source_kind": "SYNTHETIC_TEST_ONLY",
        "custody_tier": "LOCAL_SYNTHETIC_T1_NOT_T2",
        "study_id": grant["study_id"],
        "matrix_revision": grant["matrix_revision"],
        "profile_id": grant["profile_id"],
        "strategy_version": _map(manifest["strategy"], "strategy")["version"],
        "cost_model_id": grant["cost_model_id"],
        "cost_model_version": grant["cost_model_version"],
        "is_start": windows["is_start"],
        "is_end_exclusive_1m": windows["oos_start"],
        "expected_5m_decisions": expected,
        "observed_5m_decisions": observed,
        "accepted_signals": accepted,
        "blocked_signals": blocked,
        "accepted_entries_before_cutoff": entry_count,
        "modeled_exits_before_cutoff": exit_count,
        "closed_is_contained": len(contained),
        "cutoff_lifecycle": {
            "closed": completed["CLOSED"],
            "expired": completed["EXPIRED"],
            "rejected": completed["REJECTED"],
            "right_censored_open": censored["OPEN"],
            "right_censored_armed": censored["ARMED"],
        },
        "is_source_quality": source_counts,
        "is_strict_reference": strict_counts,
        "gross_r": {
            key: gross[key] for key in (
                "closed_contained", "wins", "sum_gross_r",
                "win_rate", "average_r_expectancy", "profit_factor_r",
                "maximum_cumulative_r_drawdown",
                "frequency_per_1000_expected_5m_decisions",
            )
        },
        "adjusted_r": {
            key: net[key] for key in (
                "count", "wins", "breakevens", "losses",
                "sum_gross_r", "sum_incremental_cost_r",
                "sum_adjusted_r", "mean_adjusted_r",
                "adjusted_win_rate", "adjusted_profit_factor_r",
                "max_cumulative_adjusted_r_drawdown",
                "frequency_per_1000_expected_5m_decisions",
                "component_totals_quote",
            )
        },
        "limitations": [
            "SYNTHETIC_TEST_ONLY_NOT_REAL_BTC_FEES",
            "MODELED_R_NOT_OBSERVED_PROFITABILITY",
            "NO_PROTECTED_OR_OOS_RELEASE",
        ],
    }


def _run_is_only(root: Path, set_name: str, recipient: str) -> dict[str, object]:
    """Load one private exact synthetic fixture; no file is written."""
    _need(bool(_SAFE_LABEL.fullmatch(set_name))
          and bool(_SAFE_LABEL.fullmatch(recipient)))
    base = _root(root)
    folder = _private(base / set_name, 0o700, root=base)
    _need({path.name for path in folder.iterdir()} == _FILES)
    result, source, strict, costs, grant_raw = (
        _read(folder / name, root=base) for name in (
            "scenario-result.json", "source-quality.json",
            "strict-reference.json", "test-cost-assumptions.json",
            "test-only-grant.json",
        )
    )
    grant = _load_json(grant_raw)
    return _is_projection(result, source, strict, costs, grant, recipient)


def _safe_run(root: Path, set_name: str, recipient: str) -> dict[str, object]:
    """Collapse all private exceptions to fixed non-economic dispositions."""
    try:
        return _run_is_only(root, set_name, recipient)
    except _ReleaseDenied as exc:
        status = exc.disposition
    except (EvidenceBlocked, ReportabilityError, _SyntheticCostBlocked,
            OSError, KeyError, ValueError, TypeError, AttributeError,
            OverflowError, ArithmeticError, AssertionError, RecursionError):
        status = "RELEASE_BLOCKED"
    return {"contract": _REPORT_CONTRACT, "status": status, "oos": "SEALED"}
