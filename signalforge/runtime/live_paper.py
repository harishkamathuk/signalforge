"""Operator-facing single-security PAPER runner for live NSE sessions."""

from __future__ import annotations

import json
import os
import signal
import sys
import time as time_module
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import IntEnum
from pathlib import Path
from typing import TextIO

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from signalforge.adapters.openalgo.config import OpenAlgoConfig
from signalforge.adapters.openalgo.health import OpenAlgoPreflightStatus, preflight
from signalforge.adapters.openalgo.live_market_data import OpenAlgoMarketDataAdapter
from signalforge.adapters.openalgo.market_data_config import OpenAlgoMarketDataConfig
from signalforge.adapters.openalgo.reference import resolve_nse_equity_reference
from signalforge.config.strategy_registry import (
    DEFAULT_STRATEGY_REGISTRY,
    StrategyRegistry,
    normalize_strategy_selection,
)
from signalforge.domain.ids import InstrumentId, RunId, deterministic_id
from signalforge.domain.money import Quantity
from signalforge.domain.provenance import RunIdentity
from signalforge.domain.time import IST, require_aware
from signalforge.runtime.decision_audit import project_v1_decision
from signalforge.runtime.eligibility import MarketDataFeedState
from signalforge.runtime.live_runtime import (
    LiveRuntime,
    LiveRuntimeContinuity,
    LiveRuntimeReconciliationRequired,
)
from signalforge.runtime.nse_session import NseSessionPhase, nse_session_boundaries, nse_session_phase
from signalforge.runtime.recovery import RecoveryBootstrap, RecoveryDisposition
from signalforge.runtime.strategy import StrategyRuntimeFacts

Clock = Callable[[], datetime]
MonotonicClock = Callable[[], float]
Sleeper = Callable[[float], None]


class LivePaperExitCode(IntEnum):
    """Stable operator-facing process outcomes."""

    SUCCESS = 0
    STARTUP_FAILURE = 2
    RECONCILIATION_REQUIRED = 3
    RUNTIME_FAILURE = 4


class LivePaperCommandConfig(BaseModel):
    """Non-secret operator configuration for one PAPER live session."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    instrument_id: str
    quantity: int = Field(gt=0)
    engine_calculation_version: str
    strategy: dict[str, object] = Field(default_factory=dict)

    @field_validator("instrument_id")
    @classmethod
    def validate_instrument(cls, value: str) -> str:
        candidate = value.strip()
        if not candidate.startswith("NSE:") or candidate.count(":") != 1:
            raise ValueError("live-paper instrument_id must use canonical NSE:<SYMBOL> form")
        symbol = candidate.removeprefix("NSE:")
        if not symbol or symbol != symbol.upper():
            raise ValueError("live-paper NSE symbol must be non-empty uppercase text")
        return candidate

    @field_validator("engine_calculation_version")
    @classmethod
    def validate_engine_version(cls, value: str) -> str:
        candidate = value.strip()
        if not candidate:
            raise ValueError("engine_calculation_version must not be empty")
        return candidate


@dataclass(slots=True)
class ShutdownController:
    """Process-local cooperative shutdown flag for synchronous operator loops."""

    requested: bool = False

    def request(self, _signum: int | None = None, _frame: object | None = None) -> None:
        self.requested = True


class JsonOperatorLog:
    """Minimal deterministic JSON-lines operational logger."""

    def __init__(self, stream: TextIO, clock: Clock) -> None:
        self._stream = stream
        self._clock = clock

    def emit(self, event: str, **fields: object) -> None:
        payload = {
            "event": event,
            "timestamp": require_aware(self._clock()).isoformat(),
            **fields,
        }
        self._stream.write(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")
        self._stream.flush()


@dataclass(frozen=True, slots=True)
class PreparedLivePaperSession:
    """Validated PAPER session inputs before market-data activation."""

    config: LivePaperCommandConfig
    run: RunIdentity
    instrument_id: InstrumentId
    strategy: object
    engine: Engine
    openalgo_config: OpenAlgoConfig
    market_data_config: OpenAlgoMarketDataConfig
    reference: object
    trading_date: object


def _read_config(path: Path) -> LivePaperCommandConfig:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    return LivePaperCommandConfig.model_validate(payload)


def _session_factory(engine: Engine) -> Callable[[], Session]:
    return lambda: Session(engine)


def _run_identity(
    *,
    instrument_id: InstrumentId,
    strategy: object,
    trading_date: object,
    engine_calculation_version: str,
) -> RunIdentity:
    identity = strategy.identity
    config_identity = strategy.config_identity
    run_id = deterministic_id(
        RunId,
        "live-paper",
        str(instrument_id),
        str(trading_date),
        identity.strategy_id,
        identity.strategy_version,
        config_identity.config_hash,
        engine_calculation_version,
    )
    return RunIdentity(
        run_id=run_id,
        strategy=identity,
        config_id=config_identity.config_id,
        config_hash=config_identity.config_hash,
        engine_calculation_version=engine_calculation_version,
    )


def prepare_live_paper_session(
    config_path: Path,
    *,
    env: Mapping[str, str] | None = None,
    clock: Clock,
    log: JsonOperatorLog,
    registry: StrategyRegistry = DEFAULT_STRATEGY_REGISTRY,
) -> PreparedLivePaperSession:
    """Validate every startup dependency without subscribing to live market data."""

    source = os.environ if env is None else env
    config = _read_config(config_path)
    log.emit("startup", phase="config", result="ready", mode="PAPER")

    strategy = registry.resolve(normalize_strategy_selection(config.strategy))
    if (
        strategy.identity.strategy_id != "intraday_momentum_v1"
        or strategy.identity.strategy_version != "1.0.0"
    ):
        raise ValueError("M8 live-paper supports only intraday_momentum_v1 / 1.0.0")

    openalgo_config = OpenAlgoConfig.from_environment(source)
    market_data_config = OpenAlgoMarketDataConfig.from_environment(source)

    database_url = source.get("DATABASE_URL", "").strip()
    if not database_url:
        raise ValueError("DATABASE_URL must not be empty")
    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        log.emit("startup", phase="database", result="ready")

        health = preflight(openalgo_config)
        log.emit(
            "startup",
            phase="openalgo_preflight",
            result=health.status.value,
            broker=health.broker,
        )
        if health.status is not OpenAlgoPreflightStatus.READY:
            raise RuntimeError(f"OpenAlgo preflight is not READY: {health.status.value}")

        now = require_aware(clock())
        trading_date = now.astimezone(IST).date()
        instrument_id = InstrumentId(config.instrument_id)
        reference = resolve_nse_equity_reference(
            config=openalgo_config,
            instrument_id=instrument_id,
            trading_date=trading_date,
            observed_at=now,
        )
        log.emit(
            "startup",
            phase="reference",
            result="ready",
            instrument_id=str(instrument_id),
            trading_date=trading_date.isoformat(),
        )

        run = _run_identity(
            instrument_id=instrument_id,
            strategy=strategy,
            trading_date=trading_date,
            engine_calculation_version=config.engine_calculation_version,
        )
        with Session(engine) as session:
            recovered = RecoveryBootstrap().inspect(
                session=session,
                requested_run=run,
                instrument_id=instrument_id,
                indicator_requirements=strategy.indicator_requirements,
            )
        log.emit(
            "startup",
            phase="recovery",
            result=recovered.disposition.value,
            run_id=str(run.run_id),
            lifecycle_state=(
                None
                if recovered.lifecycle.armed_setup is None
                and recovered.lifecycle.trade is None
                else "durable_active"
            ),
        )
        if recovered.disposition is RecoveryDisposition.RESUMABLE:
            raise LiveRuntimeReconciliationRequired(
                "Prior live-paper run is RESUMABLE; ADR-009 reconciliation is required"
            )

        return PreparedLivePaperSession(
            config=config,
            run=run,
            instrument_id=instrument_id,
            strategy=strategy,
            engine=engine,
            openalgo_config=openalgo_config,
            market_data_config=market_data_config,
            reference=reference,
            trading_date=trading_date,
        )
    except Exception:
        engine.dispose()
        raise


def _wait_for_activation(
    prepared: PreparedLivePaperSession,
    *,
    clock: Clock,
    sleep: Sleeper,
    shutdown: ShutdownController,
    log: JsonOperatorLog,
) -> bool:
    now = require_aware(clock())
    phase = nse_session_phase(now)
    if phase is NseSessionPhase.POST_SESSION:
        raise RuntimeError("live-paper cannot establish a fresh session after NSE regular close")
    if phase is NseSessionPhase.ACTIVE:
        return True

    boundaries = nse_session_boundaries(now.astimezone(IST).date())
    log.emit("session", phase="pre_session", result="waiting", activates_at=boundaries.opens_at.isoformat())
    while not shutdown.requested:
        now = require_aware(clock())
        phase = nse_session_phase(now)
        if phase is NseSessionPhase.ACTIVE:
            return True
        if phase is NseSessionPhase.POST_SESSION:
            raise RuntimeError("NSE session passed before live-paper activation")
        sleep(min(1.0, max(0.0, (boundaries.opens_at - now.astimezone(IST)).total_seconds())))
    return False


def _build_runtime(
    prepared: PreparedLivePaperSession,
    *,
    clock: Clock,
    monotonic_clock: MonotonicClock,
    sleep: Sleeper,
) -> LiveRuntime:
    reference = prepared.reference
    feed = OpenAlgoMarketDataAdapter(
        config=prepared.openalgo_config,
        market_data_config=prepared.market_data_config,
        instrument_id=prepared.instrument_id,
        subscription=reference.subscription,
        wall_clock=clock,
        monotonic_clock=monotonic_clock,
        sleep=sleep,
    )
    holder: dict[str, LiveRuntime] = {}

    def facts(_candle: object) -> StrategyRuntimeFacts:
        runtime = holder["runtime"]
        return StrategyRuntimeFacts(
            completed_regular_session_candles=(
                runtime.indicator_engine.state.completed_candle_count
            ),
            continuity=runtime.indicator_engine.continuity,
            feed_state=runtime.feed.state,
        )

    runtime = LiveRuntime.bootstrap(
        feed=feed,
        run=prepared.run,
        instrument_id=prepared.instrument_id,
        tick_schedule=reference.tick_size_schedule,
        quantity=Quantity(prepared.config.quantity),
        strategy=prepared.strategy,
        session_factory=_session_factory(prepared.engine),
        decision_projector=project_v1_decision,
        evaluation_context_factory=facts,
    )
    holder["runtime"] = runtime
    return runtime


def _log_step(
    log: JsonOperatorLog,
    runtime: LiveRuntime,
    step: object,
    *,
    prior_feed_state: MarketDataFeedState | None,
    prior_transition_ids: set[str],
) -> MarketDataFeedState:
    if step.feed_state is not prior_feed_state:
        log.emit(
            "feed_state",
            feed_state=step.feed_state.value,
            continuity=step.continuity.value,
            lifecycle_state=step.lifecycle.state.value,
        )
    if step.completed_candle is not None:
        log.emit(
            "candle_completed",
            instrument_id=str(runtime.instrument_id),
            interval_start=step.completed_candle.interval.start.isoformat(),
            interval_end=step.completed_candle.interval.end.isoformat(),
        )
    if step.evaluation is not None:
        log.emit(
            "strategy_decision",
            qualified=step.evaluation.qualified,
            actionable=step.evaluation.actionable,
            reasons=[str(reason) for reason in step.evaluation.reasons],
        )
    for transition in runtime.lifecycle.audit_transitions:
        transition_id = str(transition.transition_id)
        if transition_id in prior_transition_ids:
            continue
        prior_transition_ids.add(transition_id)
        log.emit(
            "lifecycle_transition",
            entity_type=transition.entity_type.value,
            entity_id=transition.entity_id,
            from_state=transition.from_state,
            to_state=transition.to_state,
            occurred_at=transition.occurred_at.isoformat(),
        )
    return step.feed_state


def run_prepared_live_paper(
    prepared: PreparedLivePaperSession,
    *,
    clock: Clock,
    monotonic_clock: MonotonicClock,
    sleep: Sleeper,
    shutdown: ShutdownController,
    log: JsonOperatorLog,
) -> LivePaperExitCode:
    """Activate and synchronously operate one prepared PAPER session."""

    if not _wait_for_activation(
        prepared,
        clock=clock,
        sleep=sleep,
        shutdown=shutdown,
        log=log,
    ):
        return LivePaperExitCode.SUCCESS

    runtime: LiveRuntime | None = None
    try:
        runtime = _build_runtime(
            prepared,
            clock=clock,
            monotonic_clock=monotonic_clock,
            sleep=sleep,
        )
        log.emit(
            "live_activation",
            mode="PAPER",
            run_id=str(runtime.run.run_id),
            instrument_id=str(runtime.instrument_id),
            continuity=runtime.continuity.value,
            warmup_completed_candles=runtime.indicator_engine.state.completed_candle_count,
        )
        prior_feed_state: MarketDataFeedState | None = None
        transition_ids = {str(item.transition_id) for item in runtime.lifecycle.audit_transitions}

        while not shutdown.requested:
            now = require_aware(clock())
            if nse_session_phase(now) is NseSessionPhase.POST_SESSION:
                break

            before_ids = {str(item.transition_id) for item in runtime.lifecycle.audit_transitions}
            timed = runtime.process_time(now)
            for transition in runtime.lifecycle.audit_transitions:
                transition_id = str(transition.transition_id)
                if transition_id in before_ids or transition_id in transition_ids:
                    continue
                transition_ids.add(transition_id)
                log.emit(
                    "lifecycle_transition",
                    entity_type=transition.entity_type.value,
                    entity_id=transition.entity_id,
                    from_state=transition.from_state,
                    to_state=transition.to_state,
                    occurred_at=transition.occurred_at.isoformat(),
                )
            if runtime.continuity is not LiveRuntimeContinuity.CONTINUOUS:
                break

            step = runtime.poll_once()
            prior_feed_state = _log_step(
                log,
                runtime,
                step,
                prior_feed_state=prior_feed_state,
                prior_transition_ids=transition_ids,
            )
            if step.continuity is not LiveRuntimeContinuity.CONTINUOUS:
                break

        if runtime.continuity is LiveRuntimeContinuity.RECONCILIATION_REQUIRED:
            log.emit(
                "reconciliation_required",
                run_id=str(runtime.run.run_id),
                lifecycle_state=runtime.lifecycle.state.value,
            )
            return LivePaperExitCode.RECONCILIATION_REQUIRED
        if runtime.continuity is LiveRuntimeContinuity.TERMINAL:
            log.emit("terminal", run_id=str(runtime.run.run_id))
            return LivePaperExitCode.RUNTIME_FAILURE
        return LivePaperExitCode.SUCCESS
    except LiveRuntimeReconciliationRequired as exc:
        log.emit("reconciliation_required", detail=str(exc))
        return LivePaperExitCode.RECONCILIATION_REQUIRED
    except Exception as exc:
        continuity = None if runtime is None else runtime.continuity.value
        log.emit("runtime_failure", detail=str(exc), continuity=continuity)
        return LivePaperExitCode.RUNTIME_FAILURE
    finally:
        if runtime is not None:
            runtime.feed.close()
            log.emit(
                "shutdown",
                result="complete",
                lifecycle_state=runtime.lifecycle.state.value,
                continuity=runtime.continuity.value,
            )
        prepared.engine.dispose()


def live_paper_command(
    config_path: Path,
    *,
    env: Mapping[str, str] | None = None,
    clock: Clock | None = None,
    monotonic_clock: MonotonicClock = time_module.monotonic,
    sleep: Sleeper = time_module.sleep,
    shutdown: ShutdownController | None = None,
    stream: TextIO | None = None,
) -> int:
    """Run the explicit PAPER-only operator command with stable exit codes."""

    actual_clock = clock or (lambda: datetime.now(UTC))
    actual_shutdown = shutdown or ShutdownController()
    log = JsonOperatorLog(stream or sys.stdout, actual_clock)
    try:
        prepared = prepare_live_paper_session(
            config_path,
            env=env,
            clock=actual_clock,
            log=log,
        )
    except LiveRuntimeReconciliationRequired as exc:
        log.emit("reconciliation_required", detail=str(exc))
        return int(LivePaperExitCode.RECONCILIATION_REQUIRED)
    except Exception as exc:
        log.emit("startup_failure", detail=str(exc), mode="PAPER")
        return int(LivePaperExitCode.STARTUP_FAILURE)

    return int(
        run_prepared_live_paper(
            prepared,
            clock=actual_clock,
            monotonic_clock=monotonic_clock,
            sleep=sleep,
            shutdown=actual_shutdown,
            log=log,
        )
    )


def install_shutdown_signal_handlers(controller: ShutdownController) -> None:
    """Install cooperative SIGINT/SIGTERM handlers for the CLI process."""

    signal.signal(signal.SIGINT, controller.request)
    signal.signal(signal.SIGTERM, controller.request)
