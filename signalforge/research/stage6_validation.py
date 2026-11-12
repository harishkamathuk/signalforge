"""Evidence-scoped Stage 6 result checks, without source access or execution.

SF-278 consumes already authenticated canonical mappings. Filesystem, custody
and approved four-attempt identity checks belong to the thin operator CLI.
No rule reconstructs missing source observations or changes the frozen runner.
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import cast

START = datetime(2025, 10, 31, tzinfo=UTC)
SPLIT = datetime(2026, 7, 1, tzinfo=UTC)
END = datetime(2026, 10, 30, tzinfo=UTC)
LIMITATIONS = (
    "EVIDENCE_CONTRACT_INTERPRETATION_PENDING",
    "DECISION_GRID_IS_RUNNER_COUNTERS_NOT_A_PER_DECISION_LEDGER",
    "TRACE_HAS_NO_OPPORTUNITY_OR_ARMING_LINKS_FOR_FULL_CONTINUITY_PROOF",
    "SOURCE_INTEGRITY_AND_IS_FIRST_PROCEDURE_REUSE_OPERATOR_ATTESTATION",
)


class EvidenceInvalid(ValueError):
    """Released evidence contradicts an existing runner invariant."""


def _require(condition: bool) -> None:
    if not condition:
        # Never incorporate protected values or exception text into diagnostics.
        raise EvidenceInvalid("inconsistent released evidence")


def _map(value: object) -> dict[str, object]:
    _require(type(value) is dict)
    return cast(dict[str, object], value)


def _rows(value: object) -> list[dict[str, object]]:
    _require(type(value) is list)
    return [_map(row) for row in cast(list[object], value)]


def _count(value: object) -> int:
    _require(type(value) is int and value >= 0)
    return cast(int, value)


def _time(value: object, *, boundary: bool = False) -> datetime:
    _require(type(value) is str)
    stamp = datetime.fromisoformat(cast(str, value))
    _require(stamp.tzinfo == UTC and stamp.second == 0 and stamp.microsecond == 0)
    _require(value == stamp.isoformat())
    _require(START <= stamp <= END if boundary else START <= stamp < END)
    return stamp


def _decimal(value: object) -> Decimal:
    _require(type(value) is Decimal and value.is_finite())
    return cast(Decimal, value)


def _lifecycle(result: dict[str, object]) -> None:
    outcomes = _rows(result["outcomes"])
    traces = _rows(result["trace"])
    blocked = _rows(result["blocked_decisions"])
    _require(_count(result["attempted_outcome_count"]) == len(outcomes))
    _require(_count(result["attempted_trace_count"]) == len(traces))
    _require(_count(result["blocked_actionable_count"]) == len(blocked))
    _require(len(outcomes) <= 104833 and len(traces) + len(blocked) <= 2096640)
    seen: set[str] = set()
    entries: list[datetime] = []
    exits: list[tuple[datetime, str]] = []
    active: list[str] = []
    by_id: dict[str, dict[str, object]] = {}
    previous_exit: datetime | None = None
    for index, outcome in enumerate(outcomes):
        _require(
            set(outcome)
            == {
                "opportunity_id",
                "certainty",
                "state",
                "reason",
                "entry_bucket",
                "exit_bucket",
                "entry_price",
                "exit_price",
                "r",
                "holding_span_1m_buckets",
            }
        )
        identity = outcome["opportunity_id"]
        _require(type(identity) is str and len(identity) == 64)
        _require(all(c in "0123456789abcdef" for c in cast(str, identity)))
        _require(identity not in seen and outcome["certainty"] == "SCENARIO_CONDITIONED")
        seen.add(cast(str, identity))
        by_id[cast(str, identity)] = outcome
        state, reason = outcome["state"], outcome["reason"]
        _require(state in ("CLOSED", "OPEN", "ARMED", "EXPIRED", "REJECTED"))
        if state in ("OPEN", "ARMED"):
            _require(index == len(outcomes) - 1 and reason == "DATASET_END_CONDITIONAL")
            active.append(state)
        elif state == "EXPIRED":
            _require(reason in ("PRE_ENTRY_INVALIDATION", "VALIDITY_WINDOW_END"))
        elif state == "REJECTED":
            _require(reason == "NON_POSITIVE_OR_UNSUPPORTED_RISK")
        else:
            _require(reason in ("STOP", "TARGET"))
        if state in ("CLOSED", "OPEN"):
            entry = _time(outcome["entry_bucket"])
            _require(_decimal(outcome["entry_price"]) > 0)
            # No pyramiding or IS/OOS reset: compare the entire ordered history,
            # never validate the two windows as isolated portfolios.
            _require(previous_exit is None or entry > previous_exit)
            entries.append(entry)
            if state == "CLOSED":
                exit_at = _time(outcome["exit_bucket"])
                _require(exit_at >= entry and _decimal(outcome["exit_price"]) > 0)
                _decimal(outcome["r"])
                span = _count(outcome["holding_span_1m_buckets"])
                _require(span == 1 + int((exit_at - entry) / timedelta(minutes=1)))
                exits.append((exit_at, cast(str, reason)))
                previous_exit = exit_at
        else:
            _require(outcome["entry_bucket"] is None and outcome["entry_price"] is None)
        if state != "CLOSED":
            # Dataset-end OPEN is unresolved, not a synthetic close or zero R.
            _require(
                all(
                    outcome[key] is None
                    for key in ("exit_bucket", "exit_price", "r", "holding_span_1m_buckets")
                )
            )
    _require(result["terminal_active_state"] == (active[0] if active else None))

    trace_entries: list[datetime] = []
    trace_exits: list[tuple[datetime, str]] = []
    actions: Counter[str] = Counter()
    prior: datetime | None = None
    open_position = False
    # The frozen runner publishes outcomes in completion order under one active
    # setup. Each ENTRY therefore consumes the next entry-bearing outcome;
    # REJECTED consumes the attempt without ever opening a position. Its missing
    # fill timestamp must not disable checks for every other accepted entry.
    entry_outcomes = iter(o for o in outcomes if o["state"] in ("CLOSED", "OPEN", "REJECTED"))
    next_entry = next(entry_outcomes, None)
    for trace in traces:
        _require(
            set(trace)
            == {
                "bucket_start",
                "from_level",
                "to_level",
                "action",
                "ordering",
                "modeled_base",
            }
        )
        bucket = _time(trace["bucket_start"])
        _require(prior is None or bucket >= prior)
        prior = bucket
        action = trace["action"]
        _require(action in ("ASSUMED_SEGMENT", "ENTRY", "INVALIDATION", "STOP", "TARGET"))
        action = cast(str, action)
        actions[action] += 1
        start, end = _decimal(trace["from_level"]), _decimal(trace["to_level"])
        _require(start > 0 and end > 0)
        _require(trace["ordering"] in ("ASSUMED", "OBSERVED_OPEN"))
        if trace["ordering"] == "OBSERVED_OPEN":
            _require(start == end and action != "ASSUMED_SEGMENT")
        if action == "ASSUMED_SEGMENT":
            _require(trace["ordering"] == "ASSUMED" and trace["modeled_base"] is None)
        else:
            _require(_decimal(trace["modeled_base"]) == end)
        if action == "ENTRY":
            _require(not open_position and next_entry is not None)
            assert next_entry is not None
            if next_entry["state"] != "REJECTED":
                _require(bucket == _time(next_entry["entry_bucket"]))
                open_position = True
                trace_entries.append(bucket)
            next_entry = next(entry_outcomes, None)
        elif action in ("STOP", "TARGET"):
            _require(open_position)
            open_position = False
            trace_exits.append((bucket, action))
        elif action == "INVALIDATION":
            _require(not open_position)
    _require(next_entry is None)
    _require(trace_entries == entries and trace_exits == exits)
    _require(open_position == (active == ["OPEN"]))
    _require(
        actions["INVALIDATION"] == sum(o["reason"] == "PRE_ENTRY_INVALIDATION" for o in outcomes)
    )
    _require(
        _count(result["event_count"])
        == sum(count for action, count in actions.items() if action != "ASSUMED_SEGMENT")
    )
    _require(cast(int, result["event_count"]) <= 2096640)
    previous_boundary: datetime | None = None
    for decision in blocked:
        _require(
            set(decision)
            == {
                "interval_start",
                "interval_end",
                "blocking_opportunity_id",
                "blocking_state",
            }
        )
        interval_start = _time(decision["interval_start"])
        interval_end = _time(decision["interval_end"], boundary=True)
        _require(
            interval_end - interval_start == timedelta(minutes=5) and interval_start.minute % 5 == 0
        )
        _require(previous_boundary is None or interval_end > previous_boundary)
        previous_boundary = interval_end
        identity = decision["blocking_opportunity_id"]
        _require(type(identity) is str and identity in by_id)
        _require(decision["blocking_state"] in ("ARMED", "OPEN"))
        outcome = by_id[cast(str, identity)]
        if decision["blocking_state"] == "OPEN":
            _require(outcome["state"] in ("OPEN", "CLOSED"))
            _require(_time(outcome["entry_bucket"]) < interval_end)
            if outcome["exit_bucket"] is not None:
                _require(_time(outcome["exit_bucket"]) >= interval_end)


def validate_result(result: dict[str, object]) -> dict[str, object]:
    """Check frozen counters and independently test saved lifecycle consistency.

    Args:
        result: Mapping already parsed and identity-verified by canonical custody.

    Returns:
        Non-economic allowlisted rule verdicts. The provisional independent gate
        remains INCONCLUSIVE pending the evidence-contract reconciliation recorded
        in the operator documentation. A separate decision ledger is additional
        assurance, not an established preregistration requirement. Runner validity
        is reported separately.
        No protected error text, timestamps, prices or trade metrics are returned.
    """
    checks: dict[str, str] = {}
    checks["FULL_WINDOW_COUNTERS"] = (
        "PASS"
        if type(result.get("is_observed")) is int
        and result["is_observed"] == 69984
        and type(result.get("oos_observed")) is int
        and result["oos_observed"] == 34848
        else "INCONCLUSIVE"
    )
    checks["ZERO_UNSUPPORTED"] = (
        "PASS"
        if type(result.get("unsupported")) is int and result["unsupported"] == 0
        else "INCONCLUSIVE"
    )
    checks["REPLAY_REPORTED"] = "PASS" if result.get("replay_verified") is True else "INVALID"
    checks["NO_FAILURE_OR_TRUNCATION"] = (
        "PASS"
        if all(
            result.get(key) is None
            for key in (
                "failure",
                "failure_bucket",
                "failure_opportunity_id",
                "failure_signal_interval_start",
                "last_complete_bucket",
            )
        )
        else "INCONCLUSIVE"
    )
    checks["RUNNER_METHOD_STATUS"] = (
        "PASS" if result.get("method_status") == "SCENARIO_METHOD_VALID" else "INCONCLUSIVE"
    )
    try:
        if result.get("failure") is None:
            _lifecycle(result)
            checks["SAVED_LIFECYCLE_CONSISTENCY"] = "PASS"
        else:
            # The frozen runner deliberately withholds partial histories on any
            # failure, retaining attempted counts. They need not equal zero.
            _require(all(result[key] == [] for key in ("outcomes", "trace", "blocked_decisions")))
            checks["SAVED_LIFECYCLE_CONSISTENCY"] = "INCONCLUSIVE"
    except (EvidenceInvalid, ValueError, TypeError, KeyError, OverflowError):
        checks["SAVED_LIFECYCLE_CONSISTENCY"] = "INVALID"
    # COR #280: this is a provisional implementation hold, not a frozen rule
    # demanding a separate decision ledger. Resolve the evidence-sufficiency
    # interpretation explicitly before changing PASS/summary eligibility.
    checks["INDEPENDENT_GRID_AND_ARMING_CONTINUITY"] = "INCONCLUSIVE"
    if isinstance(result.get("failure"), str) and str(result["failure"]).startswith(
        "SOURCE_INVALID"
    ):
        checks["NO_FAILURE_OR_TRUNCATION"] = "INVALID"
    status = "INVALID" if "INVALID" in checks.values() else "INCONCLUSIVE"
    return {
        "status": status,
        "runner_validity": "RUNNER_REPORTED_VALID"
        if result.get("method_status") == "SCENARIO_METHOD_VALID"
        else "RUNNER_NOT_REPORTED_VALID",
        "coverage": {
            "is_expected": 69984,
            "oos_expected": 34848,
            "total_expected": 104832,
            **{
                key: value if type(value) is int and value >= 0 else None
                for key in ("is_observed", "oos_observed", "unsupported")
                for value in (result.get(key),)
            },
        },
        "failure_present": result.get("failure") is not None,
        "checks": checks,
        "limitations": list(LIMITATIONS),
        "point_metrics_allowed": False,
    }
