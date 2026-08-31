"""Developer-facing SignalForge command-line entry points."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from signalforge.config.strategy_v1 import StrategyV1EvaluationConfig
from signalforge.domain.ids import InstrumentId, RunId, deterministic_id
from signalforge.domain.instruments import TickSizeRule, TickSizeSchedule
from signalforge.domain.market import MarketEvent
from signalforge.domain.money import Price, Quantity
from signalforge.domain.provenance import RunIdentity
from signalforge.runtime.eligibility import MarketDataFeedState
from signalforge.runtime.indicators import IndicatorContinuity
from signalforge.runtime.replay import InMemoryReplaySource
from signalforge.runtime.replay_clock import ReplaySessionClock
from signalforge.runtime.replay_runtime import ReplayRuntime
from signalforge.runtime.strategy_evaluator import StrategyEvaluationContext


class ReplayTickRuleConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    tick_size: Decimal = Field(gt=0)
    effective_from: date
    effective_to: date | None = None


class ReplayCommandConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    instrument_id: str
    quantity: int = Field(gt=0)
    engine_calculation_version: str
    tick_rules: tuple[ReplayTickRuleConfig, ...]
    strategy: StrategyV1EvaluationConfig = StrategyV1EvaluationConfig()


class ReplayEventInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    exchange_timestamp: datetime
    received_timestamp: datetime
    price: Decimal = Field(gt=0)
    quantity: int = Field(gt=0)
    source: str
    source_event_id: str | None = None


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="signalforge")
    subparsers = parser.add_subparsers(dest="command", required=True)
    replay = subparsers.add_parser("replay", help="run deterministic single-security replay")
    replay.add_argument("--config", required=True, type=Path)
    replay.add_argument("--input", required=True, type=Path)
    return parser


def _read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _build_runtime(config: ReplayCommandConfig, raw_events: Any) -> tuple[ReplayRuntime, ReplaySessionClock]:
    if not isinstance(raw_events, list):
        raise ValueError("Replay input must be a JSON array")

    instrument_id = InstrumentId(config.instrument_id)
    parsed_events = [ReplayEventInput.model_validate(item) for item in raw_events]
    events = tuple(
        MarketEvent(
            instrument_id=instrument_id,
            exchange_timestamp=item.exchange_timestamp,
            received_timestamp=item.received_timestamp,
            price=Price(item.price),
            quantity=item.quantity,
            source=item.source,
            source_event_id=item.source_event_id,
        )
        for item in parsed_events
    )
    source = InMemoryReplaySource(instrument_id=instrument_id, events=events)
    config_identity = config.strategy.identify()
    run_id = deterministic_id(
        RunId,
        config_identity.config_hash,
        source.identity.source_id,
        config.engine_calculation_version,
    )
    run = RunIdentity(
        run_id=run_id,
        strategy=config.strategy.strategy_identity,
        config_id=config_identity.config_id,
        config_hash=config_identity.config_hash,
        engine_calculation_version=config.engine_calculation_version,
    )
    tick_schedule = TickSizeSchedule(
        instrument_id=instrument_id,
        rules=tuple(
            TickSizeRule(
                tick_size=Price(rule.tick_size),
                effective_from=rule.effective_from,
                effective_to=rule.effective_to,
            )
            for rule in config.tick_rules
        ),
    )
    completed_count = 0

    def context_factory(_candle: object) -> StrategyEvaluationContext:
        nonlocal completed_count
        completed_count += 1
        return StrategyEvaluationContext(
            completed_regular_session_candles=completed_count,
            continuity=IndicatorContinuity.HEALTHY,
            feed_state=MarketDataFeedState.HEALTHY,
        )

    runtime = ReplayRuntime(
        source=source,
        run=run,
        tick_schedule=tick_schedule,
        quantity=Quantity(config.quantity),
        strategy_config=config.strategy,
        evaluation_context_factory=context_factory,
    )
    return runtime, ReplaySessionClock(runtime=runtime)


def _summary(runtime: ReplayRuntime, clock_steps: tuple[object, ...]) -> dict[str, object]:
    evaluations = []
    rejection_fill_ids: set[str] = set()
    for step in clock_steps:
        runtime_step = step.runtime_step  # type: ignore[attr-defined]
        if runtime_step.evaluation is not None:
            evaluations.append(runtime_step.evaluation.evaluation)
        lifecycle = runtime_step.lifecycle
        if (
            lifecycle.open_result is not None
            and lifecycle.open_result.rejection is not None
            and lifecycle.execution is not None
        ):
            rejection_fill_ids.add(str(lifecycle.execution.fill.fill_id))

    reason_counts: Counter[str] = Counter()
    for evaluation in evaluations:
        reason_counts.update(reason.value for reason in evaluation.reasons)

    transitions = runtime.lifecycle.audit_transitions
    signals = sum(
        transition.entity_type.value == "armed_setup" and transition.from_state == "none"
        for transition in transitions
    )
    trades = sum(
        transition.entity_type.value == "trade" and transition.from_state == "none"
        for transition in transitions
    )
    exits = sum(
        transition.entity_type.value == "trade" and transition.to_state == "closed"
        for transition in transitions
    )
    return {
        "run_id": str(runtime.run.run_id),
        "instrument_id": str(runtime.instrument_id),
        "source_id": runtime.source.identity.source_id,
        "events": runtime.source.identity.event_count,
        "evaluations": len(evaluations),
        "qualified": sum(evaluation.qualified for evaluation in evaluations),
        "actionable": sum(evaluation.actionable for evaluation in evaluations),
        "signals": signals,
        "trades": trades,
        "exits": exits,
        "open_rejections": len(rejection_fill_ids),
        "decision_counts": dict(sorted(reason_counts.items())),
        "final_lifecycle_state": runtime.lifecycle.state.value,
    }


def replay_command(config_path: Path, input_path: Path) -> dict[str, object]:
    config = ReplayCommandConfig.model_validate(_read_json(config_path))
    runtime, clock = _build_runtime(config, _read_json(input_path))
    steps = clock.run_all()
    return _summary(runtime, steps)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "replay":
            summary = replay_command(args.config, args.input)
            print(json.dumps(summary, sort_keys=True, separators=(",", ":")))
            return 0
        raise RuntimeError(f"Unsupported command: {args.command}")
    except Exception as exc:
        print(f"signalforge: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
