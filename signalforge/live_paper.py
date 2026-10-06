"""Operator-facing single-security PAPER runner for live OpenAlgo market data."""

from __future__ import annotations

import json
import logging
import os
import signal
import sys
import time as time_module
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import IntEnum
from pathlib import Path
from types import FrameType
from typing import Any, cast

import sqlalchemy as sa
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from signalforge.adapters.openalgo.config import OpenAlgoConfig
from signalforge.adapters.openalgo.health import OpenAlgoPreflightStatus, preflight
from signalforge.adapters.openalgo.history import (
    OpenAlgoHistoryAcquisitionError,
    OpenAlgoHistoryValidationError,
    fetch_openalgo_history,
)
from signalforge.adapters.openalgo.live_market_data import OpenAlgoMarketDataAdapter
from signalforge.adapters.openalgo.market_data_config import OpenAlgoMarketDataConfig
from signalforge.adapters.openalgo.reference import (
    ResolvedOpenAlgoInstrument,
    resolve_nse_equity_reference,
)
from signalforge.config.strategy_registry import (
    DEFAULT_STRATEGY_REGISTRY,
    StrategyRegistry,
    normalize_strategy_selection,
)
from signalforge.domain.decision_facts import StrategyDecisionFact
from signalforge.domain.ids import InstrumentId, RunId, deterministic_id
from signalforge.domain.market import CompletedCandle, MarketEvent
from signalforge.domain.money import Quantity
from signalforge.domain.prepared_indicators import (
    PreparedIndicatorCheckpoint,
    indicator_requirements_hash,
)
from signalforge.domain.provenance import RunIdentity
from signalforge.domain.session import (
    NseSessionPhase,
    nse_regular_session_boundary_at,
    nse_regular_session_open_at,
    nse_session_phase,
)
from signalforge.domain.time import to_ist
from signalforge.domain.trading_calendar import NseEquityTradingCalendar
from signalforge.persistence.errors import ContradictoryFactError
from signalforge.persistence.repositories import PostgresPreparedIndicatorCheckpointRepository
from signalforge.runtime.decision_audit import (
    project_rsi_mean_reversion_decision,
    project_v1_decision,
)
from signalforge.runtime.eligibility import MarketDataFeedState
from signalforge.runtime.live_runtime import (
    LiveRuntime,
    LiveRuntimeContinuity,
    LiveRuntimeError,
    LiveRuntimeReconciliationRequired,
)
from signalforge.runtime.prepared_indicators import (
    PreparationOutcome,
    PreparedStateError,
    PreparedStateFailureCode,
    build_prepared_checkpoint,
    previous_session_final_interval,
    require_suitable_prepared_checkpoint,
    required_strategy_v1_warmup,
)
from signalforge.runtime.recovery import RecoveryBootstrap, RecoveryDisposition
from signalforge.runtime.strategy import Strategy, StrategyDecision, StrategyRuntimeFacts
from signalforge.runtime.strategy_v1 import IntradayMomentumV1Strategy


class LivePaperExitCode(IntEnum):
    """Stable operator exit codes for the PAPER runner."""

    OK = 0
    STARTUP_FAILED = 2
    RECONCILIATION_REQUIRED = 3
    RUNTIME_FAILED = 4


class LivePaperConfig(BaseModel):
    """Non-secret operator configuration for one live PAPER security."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    instrument_id: str
    quantity: int = Field(gt=0)
    engine_calculation_version: str
    strategy: dict[str, object] = Field(default_factory=dict)

    @field_validator("instrument_id")
    @classmethod
    def validate_instrument_id(cls, value: str) -> str:
        candidate = value.strip()
        if (
            not candidate.startswith("NSE:")
            or candidate.count(":") != 1
            or candidate != value
            or candidate.removeprefix("NSE:") != candidate.removeprefix("NSE:").upper()
            or not candidate.removeprefix("NSE:")
        ):
            raise ValueError("live-paper instrument_id must be canonical NSE:<SYMBOL>")
        return candidate

    @field_validator("engine_calculation_version")
    @classmethod
    def validate_engine_version(cls, value: str) -> str:
        if not value.strip() or value != value.strip():
            raise ValueError("engine_calculation_version must be non-empty trimmed text")
        return value


@dataclass(frozen=True, slots=True)
class LivePaperPrepared:
    """Validated startup state that is safe to hold before market activation."""

    config: LivePaperConfig
    strategy: Strategy
    run: RunIdentity
    instrument_id: InstrumentId
    reference: ResolvedOpenAlgoInstrument
    openalgo: OpenAlgoConfig
    market_data: OpenAlgoMarketDataConfig
    engine: Engine
    prepared_checkpoint: PreparedIndicatorCheckpoint


@dataclass(slots=True)
class _RuntimeFactsProvider:
    runtime: LiveRuntime | None = None

    def __call__(self, _candle: CompletedCandle) -> StrategyRuntimeFacts:
        if self.runtime is None:
            raise RuntimeError("Live evaluation context requested before runtime binding")
        return StrategyRuntimeFacts(
            completed_regular_session_candles=(
                self.runtime.indicator_engine.state.completed_candle_count
            ),
            continuity=self.runtime.indicator_engine.continuity,
            feed_state=None,
        )


class _SessionBoundedLiveFeed:
    """Filter normalized live events to the accepted inclusive NSE input window."""

    def __init__(
        self,
        delegate: OpenAlgoMarketDataAdapter,
        *,
        session_open_at: datetime,
        session_boundary_at: datetime,
    ) -> None:
        self.delegate = delegate
        self.session_open_at = session_open_at
        self.session_boundary_at = session_boundary_at
        self.session_complete = False

    @property
    def state(self) -> MarketDataFeedState:
        return self.delegate.state

    def start(self) -> None:
        self.delegate.start()

    def receive_once(self) -> MarketEvent | None:
        event = self.delegate.receive_once()
        if event is None:
            return None
        if event.exchange_timestamp < self.session_open_at:
            return None
        if event.exchange_timestamp > self.session_boundary_at:
            self.session_complete = True
            return None
        return event

    def close(self) -> None:
        self.delegate.close()


def configure_json_logger(
    *,
    stream: Any = sys.stderr,
    name: str = "signalforge.live-paper",
) -> logging.Logger:
    """Return a dedicated line-oriented operator logger."""

    logger = logging.getLogger(name)
    logger.handlers.clear()
    logger.propagate = False
    logger.setLevel(logging.INFO)
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    return logger


def _emit(logger: logging.Logger, event: str, **fields: object) -> None:
    payload = {"event": event, **fields}
    logger.info(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str))


def _read_config(path: Path) -> LivePaperConfig:
    with path.open("r", encoding="utf-8") as handle:
        raw = json.load(handle)
    return LivePaperConfig.model_validate(raw)


def _decision_projector(
    strategy: Strategy,
) -> Callable[[StrategyDecision], StrategyDecisionFact]:
    key = (strategy.identity.strategy_id, strategy.identity.strategy_version)
    if key == ("intraday_momentum_v1", "1.0.0"):
        return cast(Callable[[StrategyDecision], StrategyDecisionFact], project_v1_decision)
    if key == ("rsi_mean_reversion_v1", "1.0.0"):
        return cast(
            Callable[[StrategyDecision], StrategyDecisionFact],
            project_rsi_mean_reversion_decision,
        )
    raise ValueError(f"No decision-audit projector registered for {key[0]} / {key[1]}")


def _strategy_v1_required_warmup(strategy: Strategy) -> int:
    """Return the live Strategy V1 warm-up contract with the canonical floor."""

    if not isinstance(strategy, IntradayMomentumV1Strategy):
        raise TypeError("M8 live PAPER requires IntradayMomentumV1Strategy")
    return required_strategy_v1_warmup(strategy.config.minimum_warmup_candles)


def _run_identity(
    *,
    config: LivePaperConfig,
    strategy: Strategy,
    instrument_id: InstrumentId,
    trading_date: str,
) -> RunIdentity:
    identity = strategy.config_identity
    run_id = deterministic_id(
        RunId,
        "live-paper",
        trading_date,
        str(instrument_id),
        strategy.identity.strategy_id,
        strategy.identity.strategy_version,
        identity.config_hash,
        config.engine_calculation_version,
    )
    return RunIdentity(
        run_id=run_id,
        strategy=strategy.identity,
        config_id=identity.config_id,
        config_hash=identity.config_hash,
        engine_calculation_version=config.engine_calculation_version,
    )


class LivePaperRunner:
    """Validate, activate and supervise one synchronous PAPER live runtime."""

    def __init__(
        self,
        *,
        config_path: Path,
        env: Mapping[str, str] | None = None,
        registry: StrategyRegistry = DEFAULT_STRATEGY_REGISTRY,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        monotonic: Callable[[], float] = time_module.monotonic,
        sleep: Callable[[float], None] = time_module.sleep,
        logger: logging.Logger | None = None,
    ) -> None:
        self.config_path = config_path
        self.env = os.environ if env is None else env
        self.registry = registry
        self.now = now
        self.monotonic = monotonic
        self.sleep = sleep
        self.logger = logger or configure_json_logger()
        self._shutdown_requested = False
        self._runtime: LiveRuntime | None = None
        self._session_feed: _SessionBoundedLiveFeed | None = None
        self._last_feed_state: MarketDataFeedState | None = None
        self._logged_transition_ids: set[str] = set()

    def request_shutdown(self) -> None:
        """Request cooperative shutdown between synchronous runtime steps."""

        self._shutdown_requested = True

    def prepare(self) -> LivePaperPrepared:
        """Run every fail-closed startup check before WebSocket activation."""

        config = _read_config(self.config_path)
        strategy = self.registry.resolve(normalize_strategy_selection(config.strategy))
        if (
            strategy.identity.strategy_id != "intraday_momentum_v1"
            or strategy.identity.strategy_version != "1.0.0"
        ):
            raise ValueError("M8 live-paper supports only intraday_momentum_v1 / 1.0.0")
        instrument_id = InstrumentId(config.instrument_id)
        openalgo = OpenAlgoConfig.from_environment(self.env)
        market_data = OpenAlgoMarketDataConfig.from_environment(self.env)

        database_url = self.env.get("DATABASE_URL", "").strip()
        if not database_url:
            raise ValueError("DATABASE_URL must be configured")
        engine = sa.create_engine(database_url)
        try:
            with engine.connect() as connection:
                connection.execute(sa.text("SELECT 1"))
        except Exception:
            engine.dispose()
            raise

        _emit(
            self.logger,
            "startup",
            phase="database_ready",
            mode="PAPER",
            instrument_id=str(instrument_id),
        )

        try:
            result = preflight(openalgo)
        except Exception:
            engine.dispose()
            raise
        _emit(
            self.logger,
            "openalgo_preflight",
            status=result.status.value,
            broker=result.broker,
        )
        if result.status is not OpenAlgoPreflightStatus.READY:
            engine.dispose()
            raise RuntimeError(f"OpenAlgo preflight is not READY: {result.status.value}")

        observed_at = self.now()
        trading_date = to_ist(observed_at).date()
        try:
            reference = resolve_nse_equity_reference(
                config=openalgo,
                instrument_id=instrument_id,
                trading_date=trading_date,
                observed_at=observed_at,
            )
        except Exception:
            engine.dispose()
            raise

        run = _run_identity(
            config=config,
            strategy=strategy,
            instrument_id=instrument_id,
            trading_date=trading_date.isoformat(),
        )
        def session_factory() -> Session:
            return Session(engine)
        try:
            with session_factory() as session:
                recovered = RecoveryBootstrap().inspect(
                    session=session,
                    requested_run=run,
                    instrument_id=instrument_id,
                    indicator_requirements=strategy.indicator_requirements,
                )
        except Exception:
            engine.dispose()
            raise
        _emit(
            self.logger,
            "recovery",
            disposition=recovered.disposition.value,
            run_id=str(run.run_id),
            instrument_id=str(instrument_id),
        )
        if recovered.disposition is RecoveryDisposition.RESUMABLE:
            engine.dispose()
            raise LiveRuntimeReconciliationRequired(
                "Recovered live-paper run requires reconciliation before activation"
            )

        try:
            calendar = NseEquityTradingCalendar()
            if not calendar.is_trading_day(trading_date):
                raise RuntimeError(
                    "live-paper target date is not an NSE equities trading session"
                )
            expected_boundary = previous_session_final_interval(
                trading_date,
                calendar=calendar,
            )
        except Exception:
            engine.dispose()
            raise

        minimum_warmup_candles = _strategy_v1_required_warmup(strategy)
        try:
            with session_factory() as session:
                checkpoint = PostgresPreparedIndicatorCheckpointRepository(
                    session
                ).find_for_boundary(
                    instrument_id=instrument_id,
                    requirements_hash=indicator_requirements_hash(
                        strategy.indicator_requirements
                    ),
                    calculation_version=config.engine_calculation_version,
                    interval=expected_boundary,
                )
            checkpoint = require_suitable_prepared_checkpoint(
                checkpoint,
                target_trading_date=trading_date,
                instrument_id=instrument_id,
                requirements=strategy.indicator_requirements,
                calculation_version=config.engine_calculation_version,
                minimum_warmup_candles=minimum_warmup_candles,
                calendar=calendar,
            )
        except PreparedStateError as exc:
            _emit(
                self.logger,
                "prepared_state_failure",
                code=exc.code.value,
                detail=self._safe_detail(exc),
            )
            engine.dispose()
            raise
        except ValueError as exc:
            failure = PreparedStateError(
                PreparedStateFailureCode.PREPARED_STATE_PROVENANCE_INVALID,
                str(exc),
            )
            _emit(
                self.logger,
                "prepared_state_failure",
                code=failure.code.value,
                detail=self._safe_detail(failure),
            )
            engine.dispose()
            raise failure from exc

        _emit(
            self.logger,
            "prepared_state_ready",
            checkpoint_id=str(checkpoint.checkpoint_id),
            completed_candle_count=checkpoint.state.completed_candle_count,
            boundary_end=checkpoint.final_accepted_interval.end.isoformat(),
        )
        _emit(
            self.logger,
            "reference_ready",
            instrument_id=str(reference.instrument_id),
            trading_date=reference.provenance.trading_date.isoformat(),
            sources=reference.provenance.sources,
        )
        return LivePaperPrepared(
            config=config,
            strategy=strategy,
            run=run,
            instrument_id=instrument_id,
            reference=reference,
            openalgo=openalgo,
            market_data=market_data,
            engine=engine,
            prepared_checkpoint=checkpoint,
        )

    def run(self) -> LivePaperExitCode:
        """Prepare, activate at the canonical boundary, run and shut down safely."""

        prepared: LivePaperPrepared | None = None
        try:
            prepared = self.prepare()
            checked_at = self.now()
            phase = nse_session_phase(checked_at)
            activation_at = nse_regular_session_open_at(checked_at)
            if phase is NseSessionPhase.POST_SESSION:
                raise RuntimeError("live-paper cannot activate after the NSE regular session")
            if phase is NseSessionPhase.ACTIVE and checked_at > activation_at:
                raise RuntimeError(
                    "live-paper missed the canonical NSE activation boundary"
                )

            if phase is NseSessionPhase.PRE_SESSION:
                _emit(
                    self.logger,
                    "pre_session_wait",
                    activate_at=activation_at.isoformat(),
                )
                while (
                    not self._shutdown_requested
                    and nse_session_phase(self.now()) is NseSessionPhase.PRE_SESSION
                ):
                    self.sleep(1.0)
                if self._shutdown_requested:
                    return LivePaperExitCode.OK
                reached_at = self.now()
                if nse_session_phase(reached_at) is not NseSessionPhase.ACTIVE:
                    raise RuntimeError(
                        "live-paper session became unsafe before activation"
                    )

            if self._shutdown_requested:
                return LivePaperExitCode.OK
            self._activate(prepared)
            if (
                self._runtime is None
                or self._runtime.continuity
                is not LiveRuntimeContinuity.CONTINUOUS
            ):
                raise LiveRuntimeReconciliationRequired(
                    "Live runtime did not establish continuous chronology"
                )
            self._operator_loop()
            return LivePaperExitCode.OK
        except LiveRuntimeReconciliationRequired as exc:
            _emit(self.logger, "reconciliation_required", detail=self._safe_detail(exc))
            return LivePaperExitCode.RECONCILIATION_REQUIRED
        except LiveRuntimeError as exc:
            _emit(self.logger, "runtime_failure", detail=self._safe_detail(exc))
            return LivePaperExitCode.RUNTIME_FAILED
        except Exception as exc:
            if (
                self._runtime is not None
                and self._runtime.continuity
                is LiveRuntimeContinuity.RECONCILIATION_REQUIRED
            ):
                _emit(
                    self.logger,
                    "reconciliation_required",
                    detail=self._safe_detail(exc),
                )
                return LivePaperExitCode.RECONCILIATION_REQUIRED
            _emit(self.logger, "startup_or_runtime_failure", detail=self._safe_detail(exc))
            return (
                LivePaperExitCode.RUNTIME_FAILED
                if self._runtime is not None
                else LivePaperExitCode.STARTUP_FAILED
            )
        finally:
            self._shutdown(prepared)

    def _activate(self, prepared: LivePaperPrepared) -> None:
        facts = _RuntimeFactsProvider()
        adapter = OpenAlgoMarketDataAdapter(
            config=prepared.openalgo,
            market_data_config=prepared.market_data,
            instrument_id=prepared.instrument_id,
            subscription=prepared.reference.subscription,
            wall_clock=self.now,
            monotonic_clock=self.monotonic,
            sleep=self.sleep,
        )
        reference_at = prepared.reference.provenance.observed_at
        feed = _SessionBoundedLiveFeed(
            adapter,
            session_open_at=nse_regular_session_open_at(reference_at),
            session_boundary_at=nse_regular_session_boundary_at(reference_at),
        )
        runtime = LiveRuntime.bootstrap(
            feed=feed,
            run=prepared.run,
            instrument_id=prepared.instrument_id,
            tick_schedule=prepared.reference.tick_size_schedule,
            quantity=Quantity(prepared.config.quantity),
            strategy=prepared.strategy,
            session_factory=lambda: Session(prepared.engine),
            decision_projector=_decision_projector(prepared.strategy),
            evaluation_context_factory=facts,
            initial_prepared_checkpoint=prepared.prepared_checkpoint,
        )
        facts.runtime = runtime
        self._session_feed = feed
        self._runtime = runtime
        _emit(
            self.logger,
            "live_activation",
            mode="PAPER",
            run_id=str(prepared.run.run_id),
            instrument_id=str(prepared.instrument_id),
            strategy_id=prepared.strategy.identity.strategy_id,
            strategy_version=prepared.strategy.identity.strategy_version,
            config_id=str(prepared.strategy.config_identity.config_id),
            continuity=runtime.continuity.value,
            prepared_checkpoint_id=str(prepared.prepared_checkpoint.checkpoint_id),
        )

    def _operator_loop(self) -> None:
        assert self._runtime is not None
        while not self._shutdown_requested:
            phase = nse_session_phase(self.now())
            if phase is NseSessionPhase.PRE_SESSION:
                raise LiveRuntimeError(
                    "Live runtime cannot process before the NSE regular session"
                )
            if phase is NseSessionPhase.POST_SESSION and self._session_feed is None:
                return

            # Poll before wall-clock dispatch so an already-buffered event keeps
            # its authoritative exchange chronology. A quote observed before an
            # ARMED boundary must not be invalidated merely because delivery was
            # delayed until after the wall clock crossed that boundary.
            step = self._runtime.poll_once()
            self._log_feed_state(step.feed_state)
            if step.completed_candle is not None:
                _emit(
                    self.logger,
                    "candle_completed",
                    interval_start=step.completed_candle.interval.start.isoformat(),
                    interval_end=step.completed_candle.interval.end.isoformat(),
                )
            if step.evaluation is not None:
                _emit(
                    self.logger,
                    "strategy_decision",
                    qualified=step.evaluation.qualified,
                    actionable=step.evaluation.actionable,
                    reasons=tuple(str(reason) for reason in step.evaluation.reasons),
                )

            # A signal may arrive while receive_once/process_event is in flight.
            # That synchronous market-input unit is allowed to finish, but once
            # shutdown has been requested the runner must not initiate a new
            # wall-clock lifecycle transition.
            if self._shutdown_requested:
                self._log_transitions()
                return

            self._runtime.process_time(self.now())
            self._log_transitions()
            if self._runtime.continuity is LiveRuntimeContinuity.RECONCILIATION_REQUIRED:
                raise LiveRuntimeReconciliationRequired(
                    "Live runtime chronology requires reconciliation"
                )
            if self._runtime.continuity is LiveRuntimeContinuity.TERMINAL:
                raise LiveRuntimeError("Live runtime became terminal")

            session_feed = self._session_feed
            if session_feed is not None and session_feed.session_complete:
                _emit(self.logger, "session_complete", reason="post_session_market_event")
                return

            # At/after 15:30, drain already-buffered events only while the feed
            # continues to produce accepted <=15:30 exchange timestamps. A
            # no-event poll proves there is nothing immediately available; the
            # runner then stops without extending the accepted input window.
            if phase is NseSessionPhase.POST_SESSION and step.market_event is None:
                _emit(self.logger, "session_complete", reason="boundary_drain_complete")
                return

    def _log_feed_state(self, state: MarketDataFeedState) -> None:
        if state is self._last_feed_state:
            return
        self._last_feed_state = state
        _emit(self.logger, "feed_state", feed_state=state.value)

    def _log_transitions(self) -> None:
        if self._runtime is None:
            return
        for transition in self._runtime.lifecycle.audit_transitions:
            key = str(transition.transition_id)
            if key in self._logged_transition_ids:
                continue
            self._logged_transition_ids.add(key)
            _emit(
                self.logger,
                "lifecycle_transition",
                transition_id=key,
                entity_type=transition.entity_type.value,
                from_state=transition.from_state,
                to_state=transition.to_state,
                occurred_at=transition.occurred_at.isoformat(),
            )

    def _safe_detail(self, exc: Exception) -> str:
        detail = str(exc)
        for key in ("OPENALGO_API_KEY", "DATABASE_URL"):
            value = self.env.get(key)
            if value:
                detail = detail.replace(value, "<redacted>")
        return detail

    def _shutdown(self, prepared: LivePaperPrepared | None) -> None:
        runtime = self._runtime
        if runtime is not None:
            final_feed_state = runtime.feed.state
            try:
                runtime.feed.close()
            except Exception as exc:
                _emit(self.logger, "shutdown_feed_close_failed", detail=self._safe_detail(exc))
            _emit(
                self.logger,
                "shutdown",
                lifecycle_state=runtime.lifecycle.state.value,
                continuity=runtime.continuity.value,
                feed_state=final_feed_state.value,
            )
        elif prepared is not None:
            _emit(self.logger, "shutdown", lifecycle_state=None, continuity=None)
        if prepared is not None:
            prepared.engine.dispose()


def install_shutdown_handlers(runner: LivePaperRunner) -> dict[int, Any]:
    """Install SIGINT/SIGTERM handlers that request cooperative shutdown."""

    prior: dict[int, Any] = {}

    def handle(_signum: int, _frame: FrameType | None) -> None:
        runner.request_shutdown()

    for signum in (signal.SIGINT, signal.SIGTERM):
        prior[signum] = signal.getsignal(signum)
        signal.signal(signum, handle)
    return prior


def restore_shutdown_handlers(prior: Mapping[int, Any]) -> None:
    """Restore signal handlers installed by :func:`install_shutdown_handlers`."""

    for signum, handler in prior.items():
        signal.signal(signum, handler)


def live_paper_command(config_path: Path) -> int:
    """Run the operator-facing PAPER command with cooperative signal handling."""

    runner = LivePaperRunner(config_path=config_path)
    prior = install_shutdown_handlers(runner)
    try:
        return int(runner.run())
    finally:
        restore_shutdown_handlers(prior)


def prepare_session_command(config_path: Path) -> int:
    """Create or verify immutable pre-session indicator readiness for M8."""

    env = os.environ
    engine: Engine | None = None
    try:
        config = _read_config(config_path)
        strategy = DEFAULT_STRATEGY_REGISTRY.resolve(
            normalize_strategy_selection(config.strategy)
        )
        if (
            strategy.identity.strategy_id != "intraday_momentum_v1"
            or strategy.identity.strategy_version != "1.0.0"
        ):
            raise ValueError(
                "M8 prepare-session supports only intraday_momentum_v1 / 1.0.0"
            )
        instrument_id = InstrumentId(config.instrument_id)
        minimum_warmup_candles = _strategy_v1_required_warmup(strategy)
        openalgo = OpenAlgoConfig.from_environment(env)
        database_url = env.get("DATABASE_URL", "").strip()
        if not database_url:
            raise ValueError("DATABASE_URL must be configured")
        engine = sa.create_engine(database_url)
        with engine.connect() as connection:
            connection.execute(sa.text("SELECT 1"))

        result = preflight(openalgo)
        if result.status is not OpenAlgoPreflightStatus.READY:
            raise RuntimeError(
                f"OpenAlgo preflight is not READY: {result.status.value}"
            )

        observed_at = datetime.now(UTC)
        target_trading_date = to_ist(observed_at).date()
        calendar = NseEquityTradingCalendar()
        if not calendar.is_trading_day(target_trading_date):
            raise ValueError(
                "prepare-session target date is not an NSE equities trading session"
            )
        reference = resolve_nse_equity_reference(
            config=openalgo,
            instrument_id=instrument_id,
            trading_date=target_trading_date,
            observed_at=observed_at,
        )
        expected_boundary = previous_session_final_interval(
            target_trading_date,
            calendar=calendar,
        )
        requirements_hash = indicator_requirements_hash(
            strategy.indicator_requirements
        )

        with Session(engine) as session:
            existing = PostgresPreparedIndicatorCheckpointRepository(
                session
            ).find_for_boundary(
                instrument_id=instrument_id,
                requirements_hash=requirements_hash,
                calculation_version=config.engine_calculation_version,
                interval=expected_boundary,
            )
        if existing is not None:
            checkpoint = require_suitable_prepared_checkpoint(
                existing,
                target_trading_date=target_trading_date,
                instrument_id=instrument_id,
                requirements=strategy.indicator_requirements,
                calculation_version=config.engine_calculation_version,
                minimum_warmup_candles=minimum_warmup_candles,
                calendar=calendar,
            )
            print(
                json.dumps(
                    {
                        "outcome": PreparationOutcome.READY_EXISTING.value,
                        "checkpoint_id": str(checkpoint.checkpoint_id),
                        "instrument_id": str(checkpoint.instrument_id),
                        "target_trading_date": target_trading_date.isoformat(),
                        "completed_candle_count": checkpoint.state.completed_candle_count,
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                )
            )
            return 0

        requested_to = expected_boundary.start.date()
        requested_from = requested_to - timedelta(days=14)
        candles = fetch_openalgo_history(
            config=openalgo,
            instrument_id=reference.instrument_id,
            start_date=requested_from,
            end_date=requested_to,
        )
        try:
            checkpoint = build_prepared_checkpoint(
                instrument_id=instrument_id,
                requirements=strategy.indicator_requirements,
                calculation_version=config.engine_calculation_version,
                target_trading_date=target_trading_date,
                requested_from=requested_from,
                requested_to=requested_to,
                candles=candles,
                prepared_at=observed_at,
                minimum_warmup_candles=minimum_warmup_candles,
                calendar=calendar,
            )
        except ValueError as exc:
            detail = str(exc)
            if "required completed regular-session candles" in detail:
                outcome = "FAILED_INSUFFICIENT_HISTORY"
            elif "continuity" in detail:
                outcome = "FAILED_INDICATOR_CONTINUITY"
            else:
                outcome = "FAILED_HISTORY_VALIDATION"
            print(
                json.dumps(
                    {"outcome": outcome, "detail": detail},
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                file=sys.stderr,
            )
            return 2

        try:
            with Session(engine) as session:
                with session.begin():
                    persisted = PostgresPreparedIndicatorCheckpointRepository(
                        session
                    ).add(checkpoint)
            with Session(engine) as session:
                verified = PostgresPreparedIndicatorCheckpointRepository(session).get(
                    checkpoint.checkpoint_id
                )
            if verified != persisted or verified != checkpoint:
                raise RuntimeError("persisted prepared checkpoint failed read-back verification")
        except ContradictoryFactError as exc:
            print(
                json.dumps(
                    {"outcome": "FAILED_CONTRADICTION", "detail": str(exc)},
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                file=sys.stderr,
            )
            return 2
        except Exception as exc:
            print(
                json.dumps(
                    {"outcome": "FAILED_PERSISTENCE", "detail": str(exc)},
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                file=sys.stderr,
            )
            return 2

        print(
            json.dumps(
                {
                    "outcome": PreparationOutcome.PREPARED_NEW.value,
                    "checkpoint_id": str(checkpoint.checkpoint_id),
                    "instrument_id": str(checkpoint.instrument_id),
                    "target_trading_date": target_trading_date.isoformat(),
                    "completed_candle_count": checkpoint.state.completed_candle_count,
                    "historical_digest": checkpoint.candle_sequence_digest,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return 0
    except OpenAlgoHistoryAcquisitionError as exc:
        print(
            json.dumps(
                {"outcome": "FAILED_HISTORY_ACQUISITION", "detail": str(exc)},
                sort_keys=True,
                separators=(",", ":"),
            ),
            file=sys.stderr,
        )
        return 2
    except OpenAlgoHistoryValidationError as exc:
        print(
            json.dumps(
                {"outcome": "FAILED_HISTORY_VALIDATION", "detail": str(exc)},
                sort_keys=True,
                separators=(",", ":"),
            ),
            file=sys.stderr,
        )
        return 2
    finally:
        if engine is not None:
            engine.dispose()
