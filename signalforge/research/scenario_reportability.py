"""SF-283 future-only scenario research report from persisted canonical bytes.

No strategy, source bars, private custody, or retained runner objects are read.
Companion producers are independent; their bytes are bound by the v2 result hash.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timedelta
from decimal import Decimal, localcontext
from hashlib import sha256
from typing import Any

from signalforge.config.identity import canonical_config_json, config_hash

CONTRACT = "sf283-contained-gross-r-v1"
QUALITY = ("VALID", "MISSING", "CORRUPT", "REPAIRED", "SUBSTITUTED")
FUTURE_FIELDS = (
    "signal_interval_start", "signal_interval_end", "valid_until_boundary",
    "strategy_cutoff_boundary", "terminal_event_bucket", "attempted_entry_bucket",
    "modeled_stop_price", "modeled_target_price",
)
STATES = ("CLOSED", "OPEN", "ARMED", "REJECTED", "EXPIRED")
EXPIRY = ("VALIDITY_WINDOW_END", "STRATEGY_CUTOFF", "PRE_ENTRY_INVALIDATION")


class ReportabilityError(ValueError):
    """Missing, invalid or unbound persisted evidence prevents whole-report use."""


def _decode_canonical(raw: bytes) -> dict[str, Any]:
    """Decode the repository's type-tagged JSON, verifying exact bytes.

    Type tags preserve Decimal, integer, null and boolean distinctions. Plain
    JSON decoding is not sufficient and would destroy canonical identity.
    """
    def untag(node: object) -> object:
        if not isinstance(node, list) or len(node) not in (1, 2):
            raise ReportabilityError("INVALID_CANONICAL_NODE")
        if not isinstance(node[0], str):
            raise ReportabilityError("INVALID_CANONICAL_TAG")
        kind = node[0]
        if kind == "null":
            if len(node) != 1:
                raise ReportabilityError("INVALID_CANONICAL_NULL")
            return None
        if len(node) != 2:
            raise ReportabilityError("INVALID_CANONICAL_ARITY")
        value = node[1]
        if kind == "bool" and type(value) is bool:
            return value
        if kind == "str" and type(value) is str:
            return value
        if kind == "int" and type(value) is str:
            try:
                return int(value)
            except ValueError as exc:
                raise ReportabilityError("INVALID_CANONICAL_INT") from exc
        if kind == "decimal" and type(value) is str:
            try:
                number = Decimal(value)
            except ArithmeticError as exc:
                raise ReportabilityError("INVALID_CANONICAL_DECIMAL") from exc
            if not number.is_finite():
                raise ReportabilityError("NONFINITE_CANONICAL_DECIMAL")
            return number
        if kind == "list" and isinstance(value, list):
            return [untag(item) for item in value]
        if kind == "map" and isinstance(value, list):
            out: dict[str, object] = {}
            previous: str | None = None
            for entry in value:
                if not isinstance(entry, list) or len(entry) != 2:
                    raise ReportabilityError("INVALID_CANONICAL_MAP_ENTRY")
                key = entry[0]
                if not isinstance(key, str) or (previous is not None and key <= previous):
                    raise ReportabilityError("DUPLICATE_OR_UNSORTED_CANONICAL_KEY")
                previous = key
                out[key] = untag(entry[1])
            return out
        raise ReportabilityError("UNKNOWN_CANONICAL_TAG")

    try:
        parsed = json.loads(raw)
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise ReportabilityError("INVALID_CANONICAL_JSON") from exc
    try:
        decoded = untag(parsed)
        if not isinstance(decoded, dict):
            raise ReportabilityError("CANONICAL_ROOT_NOT_MAPPING")
        with localcontext() as ctx:
            ctx.prec = 28
            expected = (canonical_config_json(decoded) + "\n").encode("utf-8")
    except RecursionError as exc:
        raise ReportabilityError("INVALID_CANONICAL_NESTING") from exc
    if raw != expected:
        raise ReportabilityError("NONCANONICAL_SAVED_BYTES")
    return decoded


def _identity(mapping: dict[str, object]) -> str:
    """Keep future identity verification independent of ambient Decimal context."""
    with localcontext() as ctx:
        ctx.prec = 28
        return config_hash(mapping)


def _require(ok: bool, reason: str) -> None:
    if not ok:
        raise ReportabilityError(reason)


def _map(value: object, name: str) -> dict[str, Any]:
    _require(type(value) is dict, "INVALID_" + name.upper())
    return value  # type: ignore[return-value]


def _items(value: object, name: str) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ReportabilityError("INVALID_" + name.upper())
    if not all(type(x) is dict for x in value):
        raise ReportabilityError("INVALID_" + name.upper())
    return value


def _utc(value: object) -> datetime:
    _require(type(value) is str, "INVALID_UTC_TIME")
    try:
        parsed = datetime.fromisoformat(value)  # type: ignore[arg-type]
    except ValueError as exc:
        raise ReportabilityError("INVALID_UTC_TIME") from exc
    _require(parsed.tzinfo is not None and parsed.utcoffset() == timedelta(0), "NON_UTC_TIME")
    _require(parsed.second == 0 and parsed.microsecond == 0, "NON_BUCKET_TIME")
    return parsed


def _number(value: object) -> Decimal:
    _require(type(value) in (str, int, float, Decimal), "INVALID_DECIMAL")
    try:
        result = Decimal(str(value))
    except ArithmeticError as exc:
        raise ReportabilityError("INVALID_DECIMAL") from exc
    _require(result.is_finite(), "NONFINITE_DECIMAL")
    return result


def _count(value: object) -> int:
    _require(type(value) is int and value >= 0, "INVALID_COUNT")
    return value  # type: ignore[return-value]


def _sum(values: list[Decimal]) -> Decimal:
    if not values:
        return Decimal(0)
    precision = max(64, max(v.adjusted() for v in values if v != 0) + 2 -
                    min(int(v.as_tuple().exponent) for v in values) +
                    len(str(len(values))) + 2) if any(values) else 64
    with localcontext() as ctx:
        ctx.prec = precision
        return sum(values, Decimal(0))


def _ratio(top: Decimal, bottom: Decimal) -> str:
    _require(bottom != 0, "ZERO_DENOMINATOR")
    with localcontext() as ctx:
        ctx.prec = 28
        return str(top / bottom)


def _metric(value: Decimal | None, reason: str) -> dict[str, object]:
    if value is None:
        return {"status": "UNDEFINED", "reason": reason, "value": None}
    return {"status": "DEFINED", "value": str(value)}


def _window_for_signal(end: datetime, start: datetime, split: datetime,
                       finish: datetime) -> str:
    if start < end <= split:
        return "IS"
    if split < end <= finish:
        return "OOS"
    raise ReportabilityError("SIGNAL_OUTSIDE_MEASURED_GRID")


def _window_for_bucket(bucket: datetime, start: datetime, split: datetime,
                       finish: datetime) -> str:
    if start <= bucket < split:
        return "IS"
    if split <= bucket < finish:
        return "OOS"
    raise ReportabilityError("EVENT_OUTSIDE_MEASURED_GRID")


def _companion(raw: bytes, digest: object, kind: str, run_id: str,
               legacy_id: str) -> dict[str, Any]:
    _require(type(digest) is str and sha256(raw).hexdigest() == digest,
             "COMPANION_HASH_MISMATCH")
    evidence = _decode_canonical(raw)
    _require(evidence.get("schema_version") == "scenario-" + kind + "-v1",
             "COMPANION_VERSION_MISMATCH")
    _require(evidence.get("scenario_run_id") == run_id
             and evidence.get("scenario_result_v1_id") == legacy_id,
             "COMPANION_IDENTITY_MISMATCH")
    _require(type(evidence.get("producer_id")) is str
             and bool(evidence["producer_id"]), "MISSING_EVIDENCE_PRODUCER")
    return evidence


def _source_quality(companion: dict[str, Any],
                    bounds: dict[str, tuple[datetime, datetime]]) -> dict[str, object]:
    _require(companion.get("unit") == "CANONICAL_1M_SOURCE_BUCKET"
             and companion.get("assessment") == "ASSESSED",
             "SOURCE_NOT_ASSESSED")
    windows = _map(companion.get("windows"), "source_windows")
    result: dict[str, object] = {}
    for name, (start, end) in bounds.items():
        record = _map(windows.get(name), "source_window")
        expected = int((end - start) / timedelta(minutes=1))
        _require(_count(record.get("expected_intervals")) == expected,
                 "SOURCE_GRID_MISMATCH")
        categories = _map(record.get("primary_disposition_counts"),
                          "quality_counts")
        _require(set(categories) == set(QUALITY), "MISSING_SOURCE_CLASSIFICATION")
        counts = {k: _count(categories[k]) for k in QUALITY}
        # Canonical grid position, not a summary count, owns each 1m classification.
        sequence = record.get("primary_dispositions_1m")
        if not isinstance(sequence, str) or len(sequence) != expected:
            raise ReportabilityError("MISSING_SOURCE_INTERVAL_CLASSIFICATIONS")
        alphabet = dict(zip("VMCRS", QUALITY, strict=True))
        _require(set(sequence).issubset(alphabet), "INVALID_SOURCE_DISPOSITION")
        recomputed = Counter(alphabet[ch] for ch in sequence)
        _require(all(recomputed[k] == counts[k] for k in QUALITY),
                 "SOURCE_COUNT_MISMATCH")
        _require(all(counts[k] == 0 for k in QUALITY if k != "VALID"),
                 "UNQUALIFIED_SOURCE")
        result[name] = {"unit": "CANONICAL_1M_SOURCE_BUCKET",
                        "expected_intervals": expected,
                        "primary_disposition_counts": counts,
                        "assessment": "ASSESSED"}
    return result


def _strict_reference(companion: dict[str, Any],
                      bounds: dict[str, tuple[datetime, datetime]]) -> dict[str, object]:
    _require(companion.get("unit") == "CANONICAL_1M_SOURCE_BUCKET"
             and companion.get("assessment") == "ASSESSED", "STRICT_NOT_ASSESSED")
    windows = _map(companion.get("windows"), "strict_windows")
    result: dict[str, object] = {}
    for name, (start, end) in bounds.items():
        row = _map(windows.get(name), "strict_window")
        eligible = _count(row.get("eligible_intervals"))
        expected = int((end - start) / timedelta(minutes=1))
        mask = row.get("assessed_1m_mask")
        if not isinstance(mask, str) or len(mask) != expected:
            raise ReportabilityError("MISSING_STRICT_INTERVAL_MASK")
        _require(set(mask).issubset({"0", "1"}), "INVALID_STRICT_INTERVAL_MASK")
        _require(mask.count("1") == eligible, "STRICT_DENOMINATOR_MISMATCH")
        intervals = row.get("ambiguous_interval_starts")
        if not isinstance(intervals, list) or not all(
            type(x) is str for x in intervals
        ):
            raise ReportabilityError("INVALID_STRICT_INTERVALS")
        times = [_utc(x) for x in intervals]
        _require(len(set(times)) == len(times) and len(times) <= eligible
                 and all(start <= t < end and
                         mask[int((t - start) / timedelta(minutes=1))] == "1"
                         for t in times),
                 "CONTRADICTORY_STRICT_CLASSIFICATION")
        result[name] = {"assessment": "ASSESSED",
                        "eligible_intervals": eligible,
                        "ambiguous_count": len(times),
                        "unit": "CANONICAL_1M_SOURCE_BUCKET"}
    return result


def _economics(closed: list[dict[str, Any]], expected: int,
               observed: int) -> dict[str, object]:
    # Exit buckets must uniquely order modeled closings under the one-active rule.
    ordered = sorted(closed, key=lambda o: _utc(o["exit_bucket"]))
    buckets = [_utc(o["exit_bucket"]) for o in ordered]
    _require(len(set(buckets)) == len(buckets), "DUPLICATE_MODELED_CLOSE_BUCKET")
    rs = [_number(o["r"]) for o in ordered]
    n = len(rs)
    profit = _sum([r for r in rs if r > 0])
    loss = _sum([r for r in rs if r < 0]).copy_negate()
    total = _sum(rs)
    with localcontext() as ctx:
        ctx.prec = max(64, len(rs) * 3 + 32)
        cumulative = Decimal(0)
        peak = Decimal(0)
        drawdown = Decimal(0)
        for r in rs:
            cumulative += r
            peak = max(peak, cumulative)
            drawdown = max(drawdown, peak - cumulative)
    wins = sum(r > 0 for r in rs)
    reasons = dict(sorted(Counter(o["reason"] for o in ordered).items()))
    _require(all(k in ("STOP", "TARGET") for k in reasons), "INVALID_CLOSED_REASON")
    spans = sorted(_count(o["holding_span_1m_buckets"]) for o in ordered)
    _require(all(s > 0 for s in spans), "INVALID_HOLDING_SPAN")
    return {
        "closed_contained": n, "wins": wins,
        "win_rate": {"status": "DEFINED", "value": _ratio(Decimal(wins), Decimal(n))}
            if n else _metric(None, "NO_CLOSED_TRADES"),
        "average_r_expectancy": {"status": "DEFINED",
                                  "value": _ratio(total, Decimal(n))}
            if n else _metric(None, "NO_CLOSED_TRADES"),
        "profit_factor_r": {"status": "DEFINED", "value": _ratio(profit, loss)}
            if loss else _metric(None, "NO_CLOSED_TRADES" if n == 0 else "NO_LOSING_R"),
        "maximum_cumulative_r_drawdown": {"value": str(drawdown),
                                          "basis": "MODELED_CLOSE_BUCKET_ORDER",
                                          "reason": "EMPTY_COHORT" if n == 0 else None},
        "frequency_per_1000_expected_5m_decisions": {
            "status": "DEFINED", "value": _ratio(Decimal(n * 1000), Decimal(expected)),
            "unit": "CLOSED_CONTAINED_PER_1000_EXPECTED_5M_DECISIONS",
        } if expected else _metric(None, "NO_MEASURED_DECISIONS"),
        "realised_r_sorted": [str(r) for r in sorted(rs)],
        "holding_span_1m_buckets_sorted": spans,
        "exit_reason_counts": reasons,
        "sum_gross_r": str(total),
        "expected_completed_5m_decisions": expected,
        "observed_completed_5m_decisions": observed,
    }


def _difference(left: dict[str, object],
                right: dict[str, object]) -> dict[str, object]:
    """Calculate only comparable, individually defined modeled statistics."""
    keys = (
        "win_rate", "average_r_expectancy", "profit_factor_r",
        "frequency_per_1000_expected_5m_decisions",
    )
    result: dict[str, object] = {}
    for key in keys:
        a = _map(left[key], "comparison_left")
        b = _map(right[key], "comparison_right")
        if a.get("status") != "DEFINED" or b.get("status") != "DEFINED":
            result[key] = {"status": "UNDEFINED",
                           "reason": "CONSTITUENT_UNDEFINED"}
            continue
        result[key] = {"status": "DEFINED", "value": str(
            _sum([_number(a["value"]), _number(b["value"]).copy_negate()])
        )}
    for key in ("maximum_cumulative_r_drawdown",):
        a = _map(left[key], "left_drawdown")
        b = _map(right[key], "right_drawdown")
        result[key] = {"status": "DEFINED", "value": str(
            _sum([_number(a["value"]), _number(b["value"]).copy_negate()])
        )}
    result["closed_contained_difference"] = (
        _count(left["closed_contained"]) - _count(right["closed_contained"])
    )
    result["sum_gross_r_difference"] = str(_sum([
        _number(left["sum_gross_r"]), _number(right["sum_gross_r"]).copy_negate()
    ]))
    return result


def compare_profile_reports(reference: dict[str, object],
                            adverse: dict[str, object]) -> dict[str, object]:
    """Compare two independently reportable profiles without pooling repeats.

    Both reports must share exact source, strategy, windows and metric contract
    identities, except for the explicitly distinct model-fill profile.
    """
    _require(reference.get("status") == "COMPLETE_PERSISTED_REPORTABILITY"
             and adverse.get("status") == "COMPLETE_PERSISTED_REPORTABILITY",
             "UNQUALIFIED_PROFILE_COMPARISON")
    _require(reference.get("profile_id") == "REFERENCE_RAW"
             and adverse.get("profile_id") == "ADVERSE_RAW",
             "PROFILE_ISOLATION_REQUIRED")
    _require(reference.get("comparison_base_identity")
             == adverse.get("comparison_base_identity"),
             "INCOMPATIBLE_PROFILE_IDENTITIES")
    results: dict[str, object] = {}
    for name in ("IS", "OOS"):
        a = _map(_map(reference["windows"], "reference_windows")[name], "ref_window")
        b = _map(_map(adverse["windows"], "adverse_windows")[name], "adv_window")
        results[name] = _difference(_map(a["economics"], "ref_economics"),
                                    _map(b["economics"], "adv_economics"))
    return {
        "status": "SCENARIO_CONDITIONED_PROFILE_COMPARISON",
        "certainty": "SCENARIO_CONDITIONED",
        "execution_valid": False,
        "basis": "REFERENCE_RAW_MINUS_ADVERSE_RAW",
        "comparison_base_identity": reference["comparison_base_identity"],
        "windows": results,
        "reference": reference,
        "adverse": adverse,
        "limitations": ["NO_PROFILE_POOLING", "NO_REPEAT_AS_NEW_SAMPLE",
                        "NOT_NET_OR_OBSERVED_HISTORICAL_PROFITABILITY"],
    }


def report_from_saved_bytes(document: bytes, source_bytes: bytes,
                            strict_bytes: bytes) -> dict[str, object]:
    """Rebuild a complete qualified conditional report from saved bytes alone.

    Raises:
        ReportabilityError: Any mandatory data or evidence binding is absent,
            contradictory or unqualified. No partial metrics are returned.
    """
    envelope = _decode_canonical(document)
    manifest = _map(envelope.get("manifest"), "manifest")
    result = _map(envelope.get("result"), "result")
    _require(result.get("schema_version") == "scenario-result-v2"
             and result.get("report_contract") == CONTRACT, "UNKNOWN_REPORT_CONTRACT")
    _require(result.get("execution_valid") is False
             and result.get("certainty") == "SCENARIO_CONDITIONED",
             "WRONG_EVIDENCE_TIER")
    run_id = _identity({"domain": "scenario-run-v1", "inputs": manifest})
    _require(result.get("scenario_run_id") == run_id, "RUN_ID_MISMATCH")
    _require(envelope.get("scenario_result_id") ==
             _identity({"domain": "scenario-result-v2", "result": result}),
             "RESULT_ID_MISMATCH")
    legacy = dict(result)
    legacy["schema_version"] = "scenario-result-v1"
    del legacy["report_contract"]
    del legacy["companion_sha256"]
    outcomes = _items(result.get("outcomes"), "outcomes")
    legacy["outcomes"] = [{k: v for k, v in o.items() if k not in FUTURE_FIELDS}
                           for o in outcomes]
    legacy_id = _identity({"domain": "scenario-result-v1", "result": legacy})
    companions = _map(result.get("companion_sha256"), "companion_binding")
    _require(set(companions) == {"source_quality", "strict_reference"},
             "MISSING_COMPANION_BINDING")
    source = _companion(source_bytes, companions["source_quality"],
                        "source-quality", run_id, legacy_id)
    strict = _companion(strict_bytes, companions["strict_reference"],
                        "strict-reference", run_id, legacy_id)
    fills = _map(manifest.get("fills"), "fill_profile")
    profile_id = fills.get("profile_id")
    _require(profile_id in ("REFERENCE_RAW", "ADVERSE_RAW")
             and fills.get("price_mode") == "raw_diagnostic",
             "UNSUPPORTED_SCENARIO_PROFILE")
    comparative = dict(manifest)
    del comparative["fills"]
    comparison_base_identity = _identity({
        "domain": "sf283-comparable-profile-v1", "inputs": comparative,
    })
    window = _map(manifest.get("session_and_window"), "window")
    start, split, finish = (_utc(window[k])
                            for k in ("is_start", "oos_start", "measured_end"))
    _require(start < split <= finish
             and (split - start) % timedelta(minutes=5) == timedelta(0)
             and (finish - split) % timedelta(minutes=5) == timedelta(0),
             "INVALID_MEASURED_WINDOWS")
    bounds = {"IS": (start, split), "OOS": (split, finish)}
    quality = _source_quality(source, bounds)
    ambiguity = _strict_reference(strict, bounds)
    expected = {name: int((end - lower) / timedelta(minutes=5))
                for name, (lower, end) in bounds.items()}
    observed = {name: _count(result.get("is_observed" if name == "IS"
                                      else "oos_observed")) for name in bounds}
    _require(observed == expected, "INCOMPLETE_DECISION_GRID")
    _require(result.get("failure") is None and _count(result.get("unsupported")) == 0
             and result.get("replay_verified") is True, "INCOMPLETE_RUN")
    _require(result.get("method_status") in
             ("SCENARIO_METHOD_VALID", "SCENARIO_METHOD_INCONCLUSIVE"),
             "INVALID_METHOD_STATUS")

    closed: dict[str, list[dict[str, Any]]] = {"IS": [], "OOS": []}
    cohort_counts: Counter[str] = Counter()
    signal_counts: Counter[str] = Counter()
    entry_counts: Counter[str] = Counter()
    exit_counts: Counter[str] = Counter()
    lifecycle: dict[str, Counter[str]] = {"IS": Counter(), "OOS": Counter()}
    seen: set[str] = set()
    seen_signals: set[datetime] = set()
    by_opportunity: dict[str, dict[str, Any]] = {}
    all_close: set[datetime] = set()
    last_signal_end: datetime | None = None
    last_terminal: datetime | None = None
    for outcome in outcomes:
        _require(set(FUTURE_FIELDS).issubset(outcome), "MISSING_LIFECYCLE_PROVENANCE")
        oid = outcome.get("opportunity_id")
        if not isinstance(oid, str) or oid in seen:
            raise ReportabilityError("DUPLICATE_OPPORTUNITY")
        seen.add(oid)
        by_opportunity[oid] = outcome
        state = outcome.get("state")
        _require(state in STATES and outcome.get("certainty") == "SCENARIO_CONDITIONED",
                 "INVALID_LIFECYCLE")
        signal_start = _utc(outcome["signal_interval_start"])
        signal_end = _utc(outcome["signal_interval_end"])
        _require(signal_end - signal_start == timedelta(minutes=5)
                 and signal_start >= start and signal_end not in seen_signals,
                 "INVALID_SIGNAL_INTERVAL")
        seen_signals.add(signal_end)
        sw = _window_for_signal(signal_end, start, split, finish)
        valid_until = _utc(outcome["valid_until_boundary"])
        _require(valid_until >= signal_end, "INVALID_VALIDITY_BOUNDARY")
        cutoff = outcome["strategy_cutoff_boundary"]
        cutoff_at = _utc(cutoff) if cutoff is not None else None
        terminal_at = _utc(outcome["terminal_event_bucket"])
        _require(signal_end <= terminal_at <= finish, "INVALID_TERMINAL_BOUNDARY")
        # Outcomes are appended at termination by the one-active-state runner.
        # Once the previous setup is terminal, a new completed signal may arm
        # at the *same* boundary, but never while the previous setup is active.
        if last_signal_end is not None:
            _require(last_signal_end < signal_end and
                     last_terminal is not None and last_terminal <= signal_end,
                     "CONTRADICTORY_ACTIVE_OVERLAP")
        last_signal_end, last_terminal = signal_end, terminal_at
        signal_counts[sw] += 1
        lifecycle[sw][str(state)] += 1
        entered = outcome.get("entry_bucket") is not None
        exited = outcome.get("exit_bucket") is not None
        entry_window = (_window_for_bucket(_utc(outcome["entry_bucket"]), start,
                                           split, finish) if entered else None)
        exit_window = (_window_for_bucket(_utc(outcome["exit_bucket"]), start,
                                          split, finish) if exited else None)
        if entered:
            entry_at = _utc(outcome["entry_bucket"])
            _require(entry_at >= signal_end, "ENTRY_BEFORE_COMPLETED_SIGNAL")
            # The runner expires an unfilled setup before inspecting the 1m
            # bucket at either boundary. Saved CLOSED/OPEN cannot override it.
            _require(entry_at < valid_until and
                     (cutoff_at is None or entry_at < cutoff_at),
                     "ENTRY_AFTER_SETUP_EXPIRY")
        if entry_window:
            entry_counts[entry_window] += 1
        if exit_window:
            exit_counts[exit_window] += 1
        if state == "CLOSED":
            _require(entered and exited and outcome.get("r") is not None
                     and outcome.get("reason") in ("STOP", "TARGET"),
                     "INVALID_CLOSED_OUTCOME")
            exit_at = _utc(outcome["exit_bucket"])
            _require(terminal_at == exit_at and
                     outcome.get("attempted_entry_bucket") is None,
                     "INVALID_CLOSED_TERMINATION")
            _require(exit_at not in all_close, "DUPLICATE_MODELED_CLOSE_BUCKET")
            all_close.add(exit_at)
            _require(_utc(outcome["entry_bucket"]) <= exit_at,
                     "REVERSED_TRADE_LIFECYCLE")
            entry_price = _number(outcome["entry_price"])
            exit_price = _number(outcome["exit_price"])
            stop_price = _number(outcome["modeled_stop_price"])
            target_price = _number(outcome["modeled_target_price"])
            _require(entry_price > stop_price > 0 and target_price > entry_price
                     and exit_price > 0, "INVALID_MODELED_RISK_OR_PRICE")
            # Match the frozen scenario R formula under fixed prospective
            # precision; do not trust an authenticated but contradictory R.
            with localcontext() as ctx:
                ctx.prec = 28
                expected_r = (exit_price - entry_price) / (entry_price - stop_price)
            _require(_number(outcome["r"]) == expected_r,
                     "CONTRADICTORY_MODELED_R")
            expected_span = 1 + int(
                (_utc(outcome["exit_bucket"]) - _utc(outcome["entry_bucket"]))
                / timedelta(minutes=1)
            )
            _require(_count(outcome["holding_span_1m_buckets"]) == expected_span,
                     "CONTRADICTORY_HOLDING_SPAN")
            cohort = (sw if entry_window == sw and exit_window == sw
                      else "CROSS_WINDOW")
            cohort_counts[cohort] += 1
            if cohort != "CROSS_WINDOW":
                closed[cohort].append(outcome)
        else:
            _require(not exited and outcome.get("r") is None,
                     "NONCLOSED_WITH_REALIZED_ECONOMICS")
            if state == "OPEN":
                _require(entered and outcome.get("reason") == "DATASET_END_CONDITIONAL"
                         and terminal_at == finish,
                         "INVALID_TERMINAL_OPEN")
            if state == "ARMED":
                _require(not entered and outcome.get("reason") == "DATASET_END_CONDITIONAL"
                         and terminal_at == finish,
                         "INVALID_TERMINAL_ARMED")
            if state == "EXPIRED":
                reason = outcome.get("reason")
                _require(not entered and reason in EXPIRY
                         and outcome["terminal_event_bucket"] is not None,
                         "INVALID_EXPIRED_OUTCOME")
                if reason == "VALIDITY_WINDOW_END":
                    _require(terminal_at >= valid_until,
                             "EXPIRY_REASON_BOUNDARY_MISMATCH")
                elif reason == "STRATEGY_CUTOFF":
                    _require(cutoff_at is not None and terminal_at >= cutoff_at,
                             "EXPIRY_REASON_BOUNDARY_MISMATCH")
                else:
                    _require(terminal_at < valid_until and
                             (cutoff_at is None or terminal_at < cutoff_at),
                             "EXPIRY_REASON_BOUNDARY_MISMATCH")
            if state == "REJECTED":
                _require(not entered and outcome.get("reason") ==
                         "NON_POSITIVE_OR_UNSUPPORTED_RISK"
                         and outcome["attempted_entry_bucket"] is not None
                         and _utc(outcome["attempted_entry_bucket"]) == terminal_at,
                         "INVALID_REJECTED_OUTCOME")
    active = [o for o in outcomes if o["state"] in ("OPEN", "ARMED")]
    _require(len(active) <= 1 and (not active or active[0] is outcomes[-1])
             and result.get("terminal_active_state") ==
             (active[0]["state"] if active else None),
             "CONTRADICTORY_TERMINAL_ACTIVE_STATE")
    _require(_count(result.get("attempted_outcome_count")) == len(outcomes),
             "OUTCOME_COUNT_MISMATCH")

    blocked = _items(result.get("blocked_decisions"), "blocked")
    blocked_counts: Counter[str] = Counter()
    seen_blocked: set[datetime] = set()
    for row in blocked:
        begin = _utc(row.get("interval_start"))
        end = _utc(row.get("interval_end"))
        blocker_id = row.get("blocking_opportunity_id")
        blocker = by_opportunity.get(blocker_id) if isinstance(blocker_id, str) else None
        _require(end - begin == timedelta(minutes=5)
                 and begin >= start and (begin - start) % timedelta(minutes=5)
                 == timedelta(0) and end <= finish
                 and end not in seen_signals and end not in seen_blocked
                 and blocker is not None,
                 "INVALID_BLOCKED_DECISION")
        seen_blocked.add(end)
        assert blocker is not None
        blocker_signal = _utc(blocker["signal_interval_end"])
        blocker_terminal = _utc(blocker["terminal_event_bucket"])
        # The completed-candle decision at t runs before walking the next 1m
        # bucket starting t. A modeled CLOSE, REJECT, invalidation or strategy
        # cutoff *at that bucket start* may therefore follow a valid block at t.
        # VALIDITY_WINDOW_END instead expires at the preceding candle-end
        # boundary before the decision, so it cannot block at that same t.
        # This ordering is a runner invariant, not inferred intraminute timing.
        blocker_active = (
            blocker_signal <= begin
            and (end < blocker_terminal or (
                end == blocker_terminal
                and blocker.get("reason") != "VALIDITY_WINDOW_END"
            ))
        )
        entered_at = (None if blocker.get("entry_bucket") is None
                      else _utc(blocker["entry_bucket"]))
        expected_state = ("OPEN" if entered_at is not None and entered_at < end
                          else "ARMED")
        _require(blocker_active and row.get("blocking_state") == expected_state,
                 "INVALID_BLOCKER_LIFECYCLE")
        blocked_counts[_window_for_signal(end, start, split, finish)] += 1
    _require(sum(cohort_counts.values()) == sum(o["state"] == "CLOSED" for o in outcomes),
             "UNRECONCILED_CLOSED_COHORT")
    _require(_count(result.get("blocked_actionable_count")) == len(blocked),
             "BLOCKED_COUNT_MISMATCH")

    reports = {}
    for name in ("IS", "OOS"):
        reports[name] = {
            "cohort": name + "_CONTAINED",
            "economics": _economics(closed[name], expected[name], observed[name]),
            "actionable_accepted_signals": signal_counts[name],
            "actionable_blocked_signals": blocked_counts[name],
            "accepted_entry_events": entry_counts[name],
            "modeled_exit_events": exit_counts[name],
            "lifecycle_by_signal_window": dict(sorted(lifecycle[name].items())),
            "source_quality": quality[name],
            "strict_reference": ambiguity[name],
            "cross_window_closed_excluded": cohort_counts["CROSS_WINDOW"],
        }
    return {
        "status": "COMPLETE_PERSISTED_REPORTABILITY",
        "certainty": "SCENARIO_CONDITIONED", "execution_valid": False,
        "point_metrics_basis": "CONDITIONAL_GROSS_R_NOT_ACTUAL_FILLS",
        "contract": CONTRACT, "scenario_result_id": envelope["scenario_result_id"],
        "scenario_run_id": run_id,
        "profile_id": profile_id,
        "comparison_base_identity": comparison_base_identity,
        "windows": reports,
        "closed_cohort_reconciliation": {
            "total_closed": sum(cohort_counts.values()),
            "IS_CONTAINED": cohort_counts["IS"],
            "OOS_CONTAINED": cohort_counts["OOS"],
            "CROSS_WINDOW": cohort_counts["CROSS_WINDOW"],
        },
        "comparisons": {
            "OOS_MINUS_IS": _difference(
                _map(reports["OOS"]["economics"], "oos_economics"),
                _map(reports["IS"]["economics"], "is_economics"),
            ),
            "REFERENCE_MINUS_ADVERSE": {
                "status": "REQUIRES_TWO_SEPARATELY_QUALIFIED_PROFILES",
            },
        },
        "limitations": [
            "CROSS_WINDOW_EXCLUDED_FROM_PRIMARY_ECONOMICS",
            "CONTAINED_OOS_NOT_UNBIASED_COMPLETE_OOS_SAMPLE",
            "STRICT_CLASSIFICATIONS_INDEPENDENTLY_PRODUCED",
            "NOT_REALIZED_HISTORICAL_EXECUTION_OR_NET_PROFITABILITY",
        ],
    }
