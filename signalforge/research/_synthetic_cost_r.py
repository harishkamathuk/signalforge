"""Private SF-293 Slice 2 synthetic-only incremental cost/R calculation.

This is NOT a reporting API, protected-study adapter, or economic release path.
Only already persisted and independently bound synthetic scenario evidence enters.
All rates and funding charges are conspicuously artificial TEST_ONLY assumptions.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal, InvalidOperation, localcontext
from hashlib import sha256
from typing import Any

from signalforge.config.identity import config_hash
from signalforge.research.scenario_reportability import (
    ReportabilityError,
    _count,
    _decode_canonical,
    _map,
    _number,
    _utc,
    _window_for_bucket,
    _window_for_signal,
    report_from_saved_bytes,
)

_CONTRACT = "sf293-slice2-synthetic-cost-r-v1"
_ASSUMPTION_CONTRACT = "sf293-slice2-test-cost-assumptions-v1"
_SOURCE = "SYNTHETIC_TEST_ONLY"
_FEE_KINDS = frozenset({"ENTRY_FEE", "EXIT_FEE"})
_WITHHOLD_CAUSES = frozenset({
    "SOURCE_NOT_ASSESSED",
    "UNQUALIFIED_SOURCE",
    "STRICT_NOT_ASSESSED",
    "STRICT_COVERAGE_PROOF_REQUIRED",
    "STRICT_COVERAGE_INCOMPLETE_WITHHOLD",
    "INCOMPLETE_RUN",
    "INCOMPLETE_DECISION_GRID",
})


class _SyntheticCostBlocked(ValueError):
    """Private fail-closed classification; never print or publish its details."""

    def __init__(self, disposition: str) -> None:
        super().__init__(disposition)
        self.disposition = disposition


def _require(ok: bool) -> None:
    if not ok:
        raise _SyntheticCostBlocked("INVALID")


def _decimal(value: object, *, nonnegative: bool = False) -> Decimal:
    # No binary floats, non-finite values, implicit rates or ambient precision.
    _require(type(value) is str)
    try:
        result = Decimal(value)  # type: ignore[arg-type]
    except (ValueError, InvalidOperation) as exc:
        raise _SyntheticCostBlocked("INVALID") from exc
    _require(result.is_finite() and (not nonnegative or result >= 0))
    return result


def _string(value: object) -> str:
    _require(type(value) is str and bool(value))
    return str(value)


def _cost_model(raw: Mapping[str, object]) -> tuple[dict[str, Decimal], str, datetime, datetime]:
    """Validate complete *invented* fee assumptions without zero defaults."""
    required = {
        "contract", "source_kind", "model_id", "model_version", "currency",
        "payoff", "quantity", "effective_start", "effective_end", "components",
        "funding_events",
    }
    if not required.issubset(raw):
        raise _SyntheticCostBlocked("WITHHELD")
    _require(set(raw) == required)
    _require(raw["contract"] == _ASSUMPTION_CONTRACT
             and raw["source_kind"] == _SOURCE
             and raw["payoff"] == "LINEAR_ONE_UNIT_LONG_TEST_ONLY"
             and raw["currency"] == "TEST_QUOTE"
             and raw["quantity"] == "1")
    _string(raw["model_id"])
    _string(raw["model_version"])
    start = _utc(raw["effective_start"])
    end = _utc(raw["effective_end"])
    _require(start < end)
    components = raw["components"]
    _require(type(components) is list)
    assert isinstance(components, list)
    if len(components) < 2:
        raise _SyntheticCostBlocked("WITHHELD")
    _require(len(components) == 2)
    assert isinstance(components, list)
    fees: dict[str, Decimal] = {}
    for item in components:
        _require(type(item) is dict)
        assert isinstance(item, dict)
        required_fee = {
            "id", "kind", "side", "basis", "rate", "unit", "source_id",
            "source_revision", "overlap_policy", "effective_start", "effective_end",
        }
        _require(set(item) == required_fee)
        kind = _string(item["kind"])
        _require(kind in _FEE_KINDS and kind not in fees
                 and item["side"] == ("ENTRY" if kind == "ENTRY_FEE" else "EXIT")
                 and item["basis"] == "MODELED_FILL_NOTIONAL"
                 and item["unit"] == "DECIMAL_RATE_OF_NOTIONAL"
                 and item["overlap_policy"] == "INCREMENTAL_NOT_IN_RAW_FILL"
                 and item["effective_start"] == raw["effective_start"]
                 and item["effective_end"] == raw["effective_end"])
        _string(item["id"])
        _string(item["source_id"])
        _string(item["source_revision"])
        _require(str(item["source_id"]).startswith("TEST_ONLY:"))
        fees[kind] = _decimal(item["rate"], nonnegative=True)
    if set(fees) != _FEE_KINDS:
        raise _SyntheticCostBlocked("WITHHELD")
    events = raw["funding_events"]
    _require(type(events) is list)
    assert isinstance(events, list)
    seen_ids: set[str] = set()
    seen_trade_event: set[tuple[str, datetime]] = set()
    for event in events:
        _require(type(event) is dict)
        assert isinstance(event, dict)
        _require(set(event) == {
            "id", "opportunity_id", "bucket", "signed_debit_quote",
            "source_id", "source_revision", "unit",
        })
        key = _string(event["id"])
        opportunity_id = _string(event["opportunity_id"])
        at = _utc(event["bucket"])
        _require(key not in seen_ids and (opportunity_id, at) not in seen_trade_event
                 and start <= at < end and event["unit"] == "TEST_QUOTE")
        seen_ids.add(key)
        seen_trade_event.add((opportunity_id, at))
        _require(_string(event["source_id"]).startswith("TEST_ONLY:"))
        _string(event["source_revision"])
        _decimal(event["signed_debit_quote"])
    # Identity is of the *exact declared* test assumption mapping, not a file.
    return fees, config_hash({
        "domain": _ASSUMPTION_CONTRACT, "input": dict(raw),
    }), start, end


def _trade_math(
    *, entry: Decimal, stop: Decimal, exit: Decimal,
    entry_rate: Decimal, exit_rate: Decimal, funding_debit: Decimal,
) -> dict[str, Decimal]:
    """Explicit q=1 linear quote-unit bridge; modeled fills stay immutable."""
    _require(entry > stop > 0 and exit > 0
             and entry_rate >= 0 and exit_rate >= 0)
    with localcontext() as ctx:
        ctx.prec = 28
        risk = entry - stop
        gross_quote = exit - entry
        entry_fee = entry * entry_rate
        exit_fee = exit * exit_rate
        incremental_cost = entry_fee + exit_fee + funding_debit
        gross_r = gross_quote / risk
        cost_r = incremental_cost / risk
        adjusted_r = (gross_quote - incremental_cost) / risk
    return {
        "risk_quote": risk,
        "gross_quote": gross_quote,
        "entry_fee_quote": entry_fee,
        "exit_fee_quote": exit_fee,
        "funding_debit_quote": funding_debit,
        "incremental_cost_quote": incremental_cost,
        "gross_r": gross_r,
        "cost_r": cost_r,
        "adjusted_r": adjusted_r,
    }


def _metric(value: Decimal | None, reason: str) -> dict[str, object]:
    return ({"status": "DEFINED", "value": str(value)} if value is not None
            else {"status": "UNDEFINED", "reason": reason})


def _aggregate(closed: list[dict[str, Any]], expected: int) -> dict[str, object]:
    """Chronological matched-cohort R metrics with the SF-283 zero peak."""
    ordered = sorted(closed, key=lambda row: _utc(row["exit_bucket"]))
    buckets = [_utc(row["exit_bucket"]) for row in ordered]
    _require(len(set(buckets)) == len(buckets) and expected >= 0)
    n = len(ordered)
    with localcontext() as ctx:
        ctx.prec = max(64, 3 * n + 32)
        gross = sum((_number(row["gross_r"]) for row in ordered), Decimal(0))
        adjusted = sum((_number(row["adjusted_r"]) for row in ordered), Decimal(0))
        cost = sum((_number(row["cost_r"]) for row in ordered), Decimal(0))
        positives = sum((_number(row["adjusted_r"]) for row in ordered
                         if _number(row["adjusted_r"]) > 0), Decimal(0))
        negatives = -sum((_number(row["adjusted_r"]) for row in ordered
                          if _number(row["adjusted_r"]) < 0), Decimal(0))
        cumulative = Decimal(0)
        peak = Decimal(0)
        max_dd = Decimal(0)
        for row in ordered:
            cumulative += _number(row["adjusted_r"])
            peak = max(peak, cumulative)
            max_dd = max(max_dd, peak - cumulative)
        wins = sum(_number(row["adjusted_r"]) > 0 for row in ordered)
        breakevens = sum(_number(row["adjusted_r"]) == 0 for row in ordered)
        losses = n - wins - breakevens
        return {
            "count": n, "wins": wins, "breakevens": breakevens, "losses": losses,
            "sum_gross_r": str(gross),
            "sum_incremental_cost_r": str(cost),
            "sum_adjusted_r": str(adjusted),
            "mean_gross_r": _metric(gross / n if n else None, "NO_CLOSED_TRADES"),
            "mean_adjusted_r": _metric(adjusted / n if n else None, "NO_CLOSED_TRADES"),
            "adjusted_win_rate": _metric(
                Decimal(wins) / n if n else None, "NO_CLOSED_TRADES",
            ),
            "adjusted_profit_factor_r": _metric(
                positives / negatives if negatives else None,
                "NO_CLOSED_TRADES" if n == 0 else "NO_LOSING_R",
            ),
            "max_cumulative_adjusted_r_drawdown": {
                "value": str(max_dd), "basis": "MODELED_CLOSE_BUCKET_ORDER",
                "reason": "EMPTY_COHORT" if n == 0 else None,
            },
            "frequency_per_1000_expected_5m_decisions": _metric(
                Decimal(1000 * n) / expected if expected else None,
                "NO_MEASURED_DECISIONS",
            ),
            "trades": ordered,
        }


def _calculate_synthetic_cost_r(
    document: bytes, source_bytes: bytes, strict_bytes: bytes,
    assumptions: Mapping[str, object],
) -> dict[str, object]:
    """Compute *private test-only* economics from immutable qualified saved bytes.

    Does not read a filesystem, emit output, mutate source, open OOS evidence
    independently, or claim SF-296 T2 custody/actual execution validity.
    Incomplete authentic strict/source evidence is WITHHELD; contradictions
    block all economic output rather than returning partial aggregates.
    """
    try:
        fees, assumption_id, valid_from, valid_until = _cost_model(assumptions)
        envelope = _decode_canonical(document)
        manifest = _map(envelope.get("manifest"), "manifest")
        src = _map(manifest.get("source"), "source")
        src_manifest = _map(src.get("manifest"), "source_manifest")
        grid = _map(src_manifest.get("grid"), "grid")
        strategy = _map(manifest.get("strategy"), "strategy")
        _require(
            grid.get("grid_id") == "scenario-synthetic"
            and "SYNTHETIC_TEST_ONLY" in src_manifest.get("limitations", ())
            and strategy.get("synthetic_fixture_identity") is not None
        )
        qualified: Any = report_from_saved_bytes(document, source_bytes, strict_bytes)
        result = _map(envelope.get("result"), "result")
        fills = _map(manifest.get("fills"), "fills")
        _require(fills.get("profile_id") in ("REFERENCE_RAW", "ADVERSE_RAW"))
        window = _map(manifest.get("session_and_window"), "window")
        start = _utc(window["is_start"])
        split = _utc(window["oos_start"])
        finish = _utc(window["measured_end"])
        _require(valid_from <= start and valid_until >= finish)
        # Source and strict denominators and original exclusions are taken
        # only from already independently qualified SF-283 saved-byte report.
        reports: dict[str, dict[str, object]] = {}
        for name in ("IS", "OOS"):
            original = qualified["windows"][name]
            reports[name] = {
                "population": {
                    key: original[key] for key in (
                        "actionable_accepted_signals", "actionable_blocked_signals",
                        "accepted_entry_events", "modeled_exit_events",
                        "lifecycle_by_signal_window", "source_quality",
                        "strict_reference", "cross_window_closed_excluded",
                        "expiry_reasons_by_signal_window",
                    )
                },
                "expected_completed_5m_decisions": original["economics"][
                    "expected_completed_5m_decisions"
                ],
                "observed_completed_5m_decisions": original["economics"][
                    "observed_completed_5m_decisions"
                ],
            }
        events = assumptions["funding_events"]
        assert isinstance(events, list)
        by_opportunity: dict[str, list[dict[str, object]]] = {}
        for event in events:
            assert isinstance(event, dict)
            oid = str(event["opportunity_id"])
            by_opportunity.setdefault(oid, []).append(event)
        all_closed: set[str] = set()
        buckets: dict[str, list[dict[str, Any]]] = {"IS": [], "OOS": []}
        for item in result["outcomes"]:
            outcome = _map(item, "outcome")
            if outcome["state"] != "CLOSED":
                continue
            oid = str(outcome["opportunity_id"])
            all_closed.add(oid)
            signal_window = _window_for_signal(
                _utc(outcome["signal_interval_end"]), start, split, finish,
            )
            entry_at = _utc(outcome["entry_bucket"])
            exit_at = _utc(outcome["exit_bucket"])
            entry_window = _window_for_bucket(entry_at, start, split, finish)
            exit_window = _window_for_bucket(exit_at, start, split, finish)
            # Even cross-window CLOSED trades must have an explicitly qualified
            # funding ledger: exclusion from metrics is not evidence of zero cost.
            funding_rows = by_opportunity.get(oid, [])
            if not funding_rows:
                raise _SyntheticCostBlocked("WITHHELD")
            _require(all(
                entry_at <= _utc(event["bucket"]) <= exit_at
                for event in funding_rows
            ))
            funding_debit = sum(
                (_decimal(event["signed_debit_quote"]) for event in funding_rows),
                Decimal(0),
            )
            bridge = _trade_math(
                entry=_number(outcome["entry_price"]),
                stop=_number(outcome["modeled_stop_price"]),
                exit=_number(outcome["exit_price"]),
                entry_rate=fees["ENTRY_FEE"],
                exit_rate=fees["EXIT_FEE"],
                funding_debit=funding_debit,
            )
            _require(bridge["gross_r"] == _number(outcome["r"]))
            if signal_window != entry_window or signal_window != exit_window:
                continue
            buckets[signal_window].append({
                "opportunity_id": oid,
                "exit_bucket": outcome["exit_bucket"],
                **{key: str(value) for key, value in bridge.items()},
            })
        _require(set(by_opportunity) == all_closed)
        for name in ("IS", "OOS"):
            expected = _count(reports[name]["expected_completed_5m_decisions"])
            rows = buckets[name]
            _require(len(rows) == qualified["windows"][name]["economics"][
                "closed_contained"
            ])
            reports[name]["economics"] = _aggregate(rows, expected)
        return {
            "contract": _CONTRACT,
            "status": "SYNTHETIC_TEST_ONLY_CALCULATED",
            "source_kind": _SOURCE,
            "certainty": "SCENARIO_CONDITIONED",
            "execution_valid": False,
            "study_outcome": "NOT_PREREGISTERED",
            "assumption_identity": assumption_id,
            "scenario_result_id": qualified["scenario_result_id"],
            "scenario_run_id": qualified["scenario_run_id"],
            "profile_id": qualified["profile_id"],
            "saved_byte_sha256": {
                "result": sha256(document).hexdigest(),
                "source_quality": sha256(source_bytes).hexdigest(),
                "strict_reference": sha256(strict_bytes).hexdigest(),
            },
            "closed_cohort_reconciliation": qualified[
                "closed_cohort_reconciliation"
            ],
            "windows": reports,
            "limitations": (
                "PRIVATE_SYNTHETIC_TEST_ONLY",
                "NO_REAL_BTC_FEES_OR_FUNDING",
                "NOT_OBSERVED_FILLS_OR_CAPITAL_DRAWDOWN",
                "NO_IS_OOS_ECONOMIC_RELEASE",
            ),
        }
    except ReportabilityError as exc:
        disposition = "WITHHELD" if str(exc) in _WITHHOLD_CAUSES else "INVALID"
        raise _SyntheticCostBlocked(disposition) from exc
