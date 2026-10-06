from __future__ import annotations

import io
import json
import signal
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from signalforge.adapters.openalgo.config import OpenAlgoConfig
from signalforge.adapters.openalgo.health import (
    OpenAlgoPreflightResult,
    OpenAlgoPreflightStatus,
)
from signalforge.adapters.openalgo.market_data_config import OpenAlgoMarketDataConfig
from signalforge.adapters.openalgo.reference import (
    OpenAlgoReferenceProvenance,
    OpenAlgoSubscriptionIdentity,
    ResolvedOpenAlgoInstrument,
)
from signalforge.config.strategy_v1 import StrategyV1EvaluationConfig
from signalforge.domain.ids import InstrumentId, RunId, deterministic_id
from signalforge.domain.instruments import Instrument, TickSizeRule, TickSizeSchedule
from signalforge.domain.market import CandleQuality, CompletedCandle
from signalforge.domain.money import Price, Quantity
from signalforge.domain.prepared_indicators import (
    PreparedIndicatorCheckpoint,
    prepared_checkpoint_id,
)
from signalforge.domain.provenance import RunIdentity
from signalforge.domain.session import NseSessionPhase, nse_session_phase
from signalforge.domain.time import IST, CandleInterval
from signalforge.live_paper import (
    LivePaperExitCode,
    LivePaperPrepared,
    LivePaperRunner,
    _SessionBoundedLiveFeed,
    configure_json_logger,
    install_shutdown_handlers,
    live_paper_command,
    restore_shutdown_handlers,
)
from signalforge.runtime.eligibility import MarketDataFeedState
from signalforge.runtime.indicators import IndicatorEngine
from signalforge.runtime.live_runtime import (
    LiveRuntimeContinuity,
    LiveRuntimeError,
    LiveRuntimeReconciliationRequired,
)
from signalforge.runtime.prepared_indicators import previous_session_final_interval
from signalforge.runtime.recovery import RecoveryDisposition
from signalforge.runtime.strategy_v1 import IntradayMomentumV1Strategy


def _write_config(tmp_path: Path) -> Path:
    path = tmp_path / "live-paper.json"
    path.write_text(
        json.dumps(
            {
                "instrument_id": "NSE:RELIANCE",
                "quantity": 10,
                "engine_calculation_version": "engine-v1",
                "strategy": {},
            }
        ),
        encoding="utf-8",
    )
    return path


def _env() -> dict[str, str]:
    return {
        "DATABASE_URL": "postgresql+psycopg://user:secret@localhost/signalforge",
        "OPENALGO_HOST": "http://127.0.0.1:5000",
        "OPENALGO_API_KEY": "top-secret-openalgo-key",
        "OPENALGO_WS_URL": "ws://127.0.0.1:8765",
    }


class FakeConnection:
    def __enter__(self):
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(self, _statement: object) -> None:
        return None


class FakeEngine:
    def __init__(self) -> None:
        self.disposed = False

    def connect(self) -> FakeConnection:
        return FakeConnection()

    def dispose(self) -> None:
        self.disposed = True


class FakeSession:
    def __enter__(self):
        return self

    def __exit__(self, *args: object) -> None:
        return None


def _reference(at: datetime) -> ResolvedOpenAlgoInstrument:
    instrument_id = InstrumentId("NSE:RELIANCE")
    return ResolvedOpenAlgoInstrument(
        instrument_id=instrument_id,
        instrument=Instrument(
            instrument_id=instrument_id,
            exchange="NSE",
            symbol="RELIANCE",
        ),
        subscription=OpenAlgoSubscriptionIdentity(symbol="RELIANCE", exchange="NSE"),
        tick_size_schedule=TickSizeSchedule(
            instrument_id=instrument_id,
            rules=(
                TickSizeRule(
                    tick_size=Price(Decimal("0.05")),
                    effective_from=at.date(),
                    effective_to=at.date(),
                ),
            ),
        ),
        provenance=OpenAlgoReferenceProvenance(
            trading_date=at.date(),
            observed_at=at,
            sources=("/api/v1/symbol", "/api/v1/search"),
            provider_token=None,
            broker_symbol=None,
            broker_exchange=None,
        ),
    )


def _prepared_checkpoint(
    at: datetime,
    strategy: IntradayMomentumV1Strategy,
) -> PreparedIndicatorCheckpoint:
    instrument_id = InstrumentId("NSE:RELIANCE")
    boundary = previous_session_final_interval(at.date())
    indicator = IndicatorEngine(
        instrument_id,
        "engine-v1",
        requirements=strategy.indicator_requirements,
    )
    first_interval: CandleInterval | None = None
    start = boundary.start - timedelta(minutes=5 * 249)
    for offset in range(250):
        interval = CandleInterval(
            start + timedelta(minutes=5 * offset),
            start + timedelta(minutes=5 * (offset + 1)),
        )
        first_interval = first_interval or interval
        close = Decimal("100") + Decimal(offset) / Decimal("100")
        indicator.update(
            CompletedCandle(
                instrument_id=instrument_id,
                interval=interval,
                quality=CandleQuality.VALID,
                open=Price(close),
                high=Price(close + Decimal("1")),
                low=Price(close - Decimal("1")),
                close=Price(close),
                volume=100,
                source="sf073-test",
                source_event_count=1,
            )
        )
    assert first_interval is not None
    state = indicator.state
    return PreparedIndicatorCheckpoint(
        checkpoint_id=prepared_checkpoint_id(
            instrument_id=instrument_id,
            requirements=strategy.indicator_requirements,
            calculation_version="engine-v1",
            boundary=boundary,
        ),
        state=state,
        exchange="NSE",
        target_trading_date=at.date(),
        historical_source="openalgo:/api/v1/history",
        requested_from=first_interval.start.date(),
        requested_to=boundary.start.date(),
        first_accepted_interval=first_interval,
        final_accepted_interval=boundary,
        accepted_candle_count=250,
        candle_sequence_digest="a" * 64,
        prepared_at=at,
    )


def _prepared(at: datetime, engine: FakeEngine | None = None) -> LivePaperPrepared:
    strategy = IntradayMomentumV1Strategy(StrategyV1EvaluationConfig())
    identity = strategy.config_identity
    instrument_id = InstrumentId("NSE:RELIANCE")
    run = RunIdentity(
        run_id=deterministic_id(
            RunId,
            "test-live-paper",
            at.date().isoformat(),
        ),
        strategy=strategy.identity,
        config_id=identity.config_id,
        config_hash=identity.config_hash,
        engine_calculation_version="engine-v1",
    )
    return LivePaperPrepared(
        config=SimpleNamespace(quantity=10),  # type: ignore[arg-type]
        strategy=strategy,
        run=run,
        instrument_id=instrument_id,
        reference=_reference(at),
        openalgo=OpenAlgoConfig(
            host="http://127.0.0.1:5000",
            api_key="top-secret-openalgo-key",
        ),
        market_data=OpenAlgoMarketDataConfig(ws_url="ws://127.0.0.1:8765"),
        engine=engine or FakeEngine(),  # type: ignore[arg-type]
        prepared_checkpoint=_prepared_checkpoint(at, strategy),
    )


def _patch_prepare_dependencies(
    monkeypatch: pytest.MonkeyPatch,
    *,
    at: datetime,
    disposition: RecoveryDisposition = RecoveryDisposition.NEW,
    patch_checkpoint: bool = True,
) -> FakeEngine:
    engine = FakeEngine()
    monkeypatch.setattr("signalforge.live_paper.sa.create_engine", lambda _url: engine)
    monkeypatch.setattr("signalforge.live_paper.Session", lambda _engine: FakeSession())
    monkeypatch.setattr(
        "signalforge.live_paper.preflight",
        lambda _config: OpenAlgoPreflightResult(
            status=OpenAlgoPreflightStatus.READY,
            broker="zerodha",
        ),
    )
    monkeypatch.setattr(
        "signalforge.live_paper.resolve_nse_equity_reference",
        lambda **_kwargs: _reference(at),
    )
    monkeypatch.setattr(
        "signalforge.live_paper.RecoveryBootstrap.inspect",
        lambda self, **_kwargs: SimpleNamespace(disposition=disposition),
    )
    if patch_checkpoint:
        prepared_strategy = IntradayMomentumV1Strategy(StrategyV1EvaluationConfig())
        checkpoint = _prepared_checkpoint(at, prepared_strategy)
        monkeypatch.setattr(
            "signalforge.live_paper.PostgresPreparedIndicatorCheckpointRepository.find_for_boundary",
            lambda self, **_kwargs: checkpoint,
        )
    return engine


def test_prepare_validates_dependencies_without_constructing_websocket(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    at = datetime(2026, 10, 5, 8, 30, tzinfo=IST)
    engine = _patch_prepare_dependencies(monkeypatch, at=at)
    opened: list[object] = []
    monkeypatch.setattr(
        "signalforge.live_paper.OpenAlgoMarketDataAdapter",
        lambda **kwargs: opened.append(kwargs),
    )

    runner = LivePaperRunner(
        config_path=_write_config(tmp_path),
        env=_env(),
        now=lambda: at,
        logger=configure_json_logger(stream=io.StringIO(), name="sf058-prepare"),
    )
    prepared = runner.prepare()

    assert prepared.instrument_id == InstrumentId("NSE:RELIANCE")
    assert opened == []
    assert not engine.disposed
    prepared.engine.dispose()




def test_missing_prepared_state_fails_before_live_activation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    at = datetime(2026, 10, 5, 9, 0, tzinfo=IST)
    engine = _patch_prepare_dependencies(monkeypatch, at=at)
    monkeypatch.setattr(
        "signalforge.live_paper.PostgresPreparedIndicatorCheckpointRepository.find_for_boundary",
        lambda self, **_kwargs: None,
    )
    stream = io.StringIO()
    runner = LivePaperRunner(
        config_path=_write_config(tmp_path),
        env=_env(),
        now=lambda: at,
        logger=configure_json_logger(stream=stream, name="sf073-missing-prepared"),
    )
    activated: list[bool] = []
    monkeypatch.setattr(runner, "_activate", lambda _prepared: activated.append(True))

    assert runner.run() is LivePaperExitCode.STARTUP_FAILED
    assert activated == []
    assert engine.disposed
    records = [json.loads(line) for line in stream.getvalue().splitlines()]
    failures = [item for item in records if item["event"] == "prepared_state_failure"]
    assert failures[-1]["code"] == "PREPARED_STATE_MISSING"


def test_configured_warmup_above_checkpoint_count_fails_before_activation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    at = datetime(2026, 10, 5, 9, 0, tzinfo=IST)
    engine = _patch_prepare_dependencies(monkeypatch, at=at)
    path = tmp_path / "live-paper-warmup.json"
    path.write_text(
        json.dumps(
            {
                "instrument_id": "NSE:RELIANCE",
                "quantity": 10,
                "engine_calculation_version": "engine-v1",
                "strategy": {"minimum_warmup_candles": 300},
            }
        ),
        encoding="utf-8",
    )
    stream = io.StringIO()
    runner = LivePaperRunner(
        config_path=path,
        env=_env(),
        now=lambda: at,
        logger=configure_json_logger(stream=stream, name="sf073-configured-warmup"),
    )
    activated: list[bool] = []
    monkeypatch.setattr(runner, "_activate", lambda _prepared: activated.append(True))

    assert runner.run() is LivePaperExitCode.STARTUP_FAILED
    assert activated == []
    assert engine.disposed
    records = [json.loads(line) for line in stream.getvalue().splitlines()]
    failures = [item for item in records if item["event"] == "prepared_state_failure"]
    assert failures[-1]["code"] == "PREPARED_STATE_NOT_READY"


def test_calendar_resolution_failure_disposes_engine(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    at = datetime(2027, 1, 4, 9, 0, tzinfo=IST)
    engine = _patch_prepare_dependencies(
        monkeypatch,
        at=at,
        patch_checkpoint=False,
    )
    runner = LivePaperRunner(
        config_path=_write_config(tmp_path),
        env=_env(),
        now=lambda: at,
        logger=configure_json_logger(stream=io.StringIO(), name="sf073-calendar-fail"),
    )
    activated: list[bool] = []
    monkeypatch.setattr(runner, "_activate", lambda _prepared: activated.append(True))

    assert runner.run() is LivePaperExitCode.STARTUP_FAILED
    assert activated == []
    assert engine.disposed


def test_non_ready_preflight_prevents_reference_and_activation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    at = datetime(2026, 10, 5, 9, 0, tzinfo=IST)
    engine = FakeEngine()
    monkeypatch.setattr("signalforge.live_paper.sa.create_engine", lambda _url: engine)
    monkeypatch.setattr(
        "signalforge.live_paper.preflight",
        lambda _config: OpenAlgoPreflightResult(
            status=OpenAlgoPreflightStatus.BROKER_SESSION_UNAVAILABLE
        ),
    )
    referenced: list[bool] = []
    monkeypatch.setattr(
        "signalforge.live_paper.resolve_nse_equity_reference",
        lambda **_kwargs: referenced.append(True),
    )

    runner = LivePaperRunner(
        config_path=_write_config(tmp_path),
        env=_env(),
        now=lambda: at,
        logger=configure_json_logger(stream=io.StringIO(), name="sf058-preflight"),
    )

    assert runner.run() is LivePaperExitCode.STARTUP_FAILED
    assert referenced == []
    assert engine.disposed


def test_resumable_recovery_returns_reconciliation_without_activation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    at = datetime(2026, 10, 5, 9, 0, tzinfo=IST)
    engine = _patch_prepare_dependencies(
        monkeypatch,
        at=at,
        disposition=RecoveryDisposition.RESUMABLE,
    )
    runner = LivePaperRunner(
        config_path=_write_config(tmp_path),
        env=_env(),
        now=lambda: at,
        logger=configure_json_logger(stream=io.StringIO(), name="sf058-resumable"),
    )
    activated: list[bool] = []
    monkeypatch.setattr(runner, "_activate", lambda _prepared: activated.append(True))

    assert runner.run() is LivePaperExitCode.RECONCILIATION_REQUIRED
    assert activated == []
    assert engine.disposed


def test_pre_session_wait_does_not_activate_until_0915(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current = [datetime(2026, 10, 5, 9, 14, 59, tzinfo=IST)]
    prepared = _prepared(current[0])
    runner = LivePaperRunner(
        config_path=_write_config(tmp_path),
        env=_env(),
        now=lambda: current[0],
        sleep=lambda _seconds: current.__setitem__(
            0, datetime(2026, 10, 5, 9, 15, tzinfo=IST)
        ),
        logger=configure_json_logger(stream=io.StringIO(), name="sf058-pre-session"),
    )
    monkeypatch.setattr(runner, "prepare", lambda: prepared)
    activated: list[datetime] = []

    def activate(_prepared: LivePaperPrepared) -> None:
        activated.append(current[0])
        runner._runtime = SimpleNamespace(
            continuity=LiveRuntimeContinuity.CONTINUOUS
        )  # type: ignore[assignment]

    monkeypatch.setattr(runner, "_activate", activate)
    monkeypatch.setattr(runner, "_operator_loop", lambda: None)
    monkeypatch.setattr(runner, "_shutdown", lambda _prepared: None)

    assert runner.run() is LivePaperExitCode.OK
    assert activated == [datetime(2026, 10, 5, 9, 15, tzinfo=IST)]


def test_post_session_start_fails_closed_without_activation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    at = datetime(2026, 10, 5, 15, 30, tzinfo=IST)
    prepared = _prepared(at)
    runner = LivePaperRunner(
        config_path=_write_config(tmp_path),
        env=_env(),
        now=lambda: at,
        logger=configure_json_logger(stream=io.StringIO(), name="sf058-post-session"),
    )
    monkeypatch.setattr(runner, "prepare", lambda: prepared)
    activated: list[bool] = []
    monkeypatch.setattr(runner, "_activate", lambda _prepared: activated.append(True))
    monkeypatch.setattr(runner, "_shutdown", lambda _prepared: None)

    assert nse_session_phase(at) is NseSessionPhase.POST_SESSION
    assert runner.run() is LivePaperExitCode.STARTUP_FAILED
    assert activated == []


def test_configured_secrets_are_redacted_from_failure_logs(tmp_path: Path) -> None:
    stream = io.StringIO()
    env = _env()
    runner = LivePaperRunner(
        config_path=_write_config(tmp_path),
        env=env,
        logger=configure_json_logger(stream=stream, name="sf058-redaction"),
    )
    secret_error = RuntimeError(
        f"bad {env['OPENALGO_API_KEY']} at {env['DATABASE_URL']}"
    )

    detail = runner._safe_detail(secret_error)

    assert env["OPENALGO_API_KEY"] not in detail
    assert env["DATABASE_URL"] not in detail
    assert "<redacted>" in detail


def test_signal_handlers_request_cooperative_shutdown(tmp_path: Path) -> None:
    runner = LivePaperRunner(config_path=_write_config(tmp_path), env=_env())
    prior = install_shutdown_handlers(runner)
    try:
        handler = signal.getsignal(signal.SIGINT)
        assert callable(handler)
        handler(signal.SIGINT, None)
        assert runner._shutdown_requested
    finally:
        restore_shutdown_handlers(prior)



def test_transport_error_after_gap_uses_reconciliation_exit_code(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current = [datetime(2026, 10, 5, 9, 14, 59, tzinfo=IST)]
    prepared = _prepared(current[0])
    stream = io.StringIO()
    runner = LivePaperRunner(
        config_path=_write_config(tmp_path),
        env=_env(),
        now=lambda: current[0],
        sleep=lambda _seconds: current.__setitem__(
            0, datetime(2026, 10, 5, 9, 15, tzinfo=IST)
        ),
        logger=configure_json_logger(stream=stream, name="sf058-gap-classification"),
    )
    monkeypatch.setattr(runner, "prepare", lambda: prepared)

    def activate(_prepared: LivePaperPrepared) -> None:
        runner._runtime = SimpleNamespace(
            continuity=LiveRuntimeContinuity.CONTINUOUS
        )  # type: ignore[assignment]

    def operator_loop() -> None:
        assert runner._runtime is not None
        runner._runtime.continuity = LiveRuntimeContinuity.RECONCILIATION_REQUIRED
        raise RuntimeError("transport lost after continuity gap")

    monkeypatch.setattr(runner, "_activate", activate)
    monkeypatch.setattr(runner, "_operator_loop", operator_loop)
    monkeypatch.setattr(runner, "_shutdown", lambda _prepared: None)

    assert runner.run() is LivePaperExitCode.RECONCILIATION_REQUIRED
    records = [json.loads(line) for line in stream.getvalue().splitlines()]
    assert records[-1]["event"] == "reconciliation_required"



def test_mid_session_fresh_start_fails_closed_without_activation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    at = datetime(2026, 10, 5, 10, 0, tzinfo=IST)
    prepared = _prepared(at)
    runner = LivePaperRunner(
        config_path=_write_config(tmp_path),
        env=_env(),
        now=lambda: at,
        logger=configure_json_logger(stream=io.StringIO(), name="sf058-mid-session"),
    )
    monkeypatch.setattr(runner, "prepare", lambda: prepared)
    activated: list[bool] = []
    monkeypatch.setattr(runner, "_activate", lambda _prepared: activated.append(True))
    monkeypatch.setattr(runner, "_shutdown", lambda _prepared: None)

    assert nse_session_phase(at) is NseSessionPhase.ACTIVE
    assert runner.run() is LivePaperExitCode.STARTUP_FAILED
    assert activated == []



class _FakeLiveFeed:
    def __init__(self, events: list[object] | None = None) -> None:
        self.state = MarketDataFeedState.HEALTHY
        self.closed = False
        self.events = list(events or [])

    def start(self) -> None:
        return None

    def receive_once(self) -> object | None:
        return None if not self.events else self.events.pop(0)

    def close(self) -> None:
        self.closed = True


class _FakeOperatorRuntime:
    def __init__(
        self,
        *,
        continuity: LiveRuntimeContinuity = LiveRuntimeContinuity.CONTINUOUS,
        steps: list[object] | None = None,
    ) -> None:
        self.continuity = continuity
        self.feed = _FakeLiveFeed()
        self.lifecycle = SimpleNamespace(state=SimpleNamespace(value="idle"), audit_transitions=())
        self.steps = list(steps or [])
        self.time_calls: list[datetime] = []
        self.poll_calls = 0
        self.call_order: list[str] = []

    def process_time(self, at: datetime) -> object:
        self.call_order.append("time")
        self.time_calls.append(at)
        return self.lifecycle

    def poll_once(self) -> object:
        self.call_order.append("poll")
        self.poll_calls += 1
        if not self.steps:
            raise AssertionError("unexpected poll")
        return self.steps.pop(0)


def test_invalid_live_paper_config_fails_before_database_work(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "bad-live-paper.json"
    path.write_text(
        json.dumps(
            {
                "instrument_id": "BSE:RELIANCE",
                "quantity": 10,
                "engine_calculation_version": "engine-v1",
                "strategy": {},
            }
        ),
        encoding="utf-8",
    )
    created: list[str] = []
    monkeypatch.setattr(
        "signalforge.live_paper.sa.create_engine",
        lambda url: created.append(url),
    )
    runner = LivePaperRunner(
        config_path=path,
        env=_env(),
        logger=configure_json_logger(stream=io.StringIO(), name="sf058-bad-config"),
    )

    assert runner.run() is LivePaperExitCode.STARTUP_FAILED
    assert created == []


def test_database_failure_prevents_openalgo_preflight(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingEngine(FakeEngine):
        def connect(self) -> FakeConnection:
            raise RuntimeError("database unavailable")

    engine = FailingEngine()
    monkeypatch.setattr("signalforge.live_paper.sa.create_engine", lambda _url: engine)
    preflight_calls: list[bool] = []
    monkeypatch.setattr(
        "signalforge.live_paper.preflight",
        lambda _config: preflight_calls.append(True),
    )
    runner = LivePaperRunner(
        config_path=_write_config(tmp_path),
        env=_env(),
        logger=configure_json_logger(stream=io.StringIO(), name="sf058-db-fail"),
    )

    assert runner.run() is LivePaperExitCode.STARTUP_FAILED
    assert preflight_calls == []
    assert engine.disposed


def test_reference_failure_disposes_engine_and_prevents_recovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    at = datetime(2026, 10, 5, 9, 0, tzinfo=IST)
    engine = FakeEngine()
    monkeypatch.setattr("signalforge.live_paper.sa.create_engine", lambda _url: engine)
    monkeypatch.setattr(
        "signalforge.live_paper.preflight",
        lambda _config: OpenAlgoPreflightResult(
            status=OpenAlgoPreflightStatus.READY,
            broker="zerodha",
        ),
    )
    monkeypatch.setattr(
        "signalforge.live_paper.resolve_nse_equity_reference",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("reference unavailable")),
    )
    recovered: list[bool] = []
    monkeypatch.setattr(
        "signalforge.live_paper.RecoveryBootstrap.inspect",
        lambda self, **_kwargs: recovered.append(True),
    )
    runner = LivePaperRunner(
        config_path=_write_config(tmp_path),
        env=_env(),
        now=lambda: at,
        logger=configure_json_logger(stream=io.StringIO(), name="sf058-reference-fail"),
    )

    assert runner.run() is LivePaperExitCode.STARTUP_FAILED
    assert recovered == []
    assert engine.disposed


def test_pre_session_shutdown_returns_cleanly_without_activation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    at = datetime(2026, 10, 5, 9, 0, tzinfo=IST)
    prepared = _prepared(at)
    runner = LivePaperRunner(
        config_path=_write_config(tmp_path),
        env=_env(),
        now=lambda: at,
        sleep=lambda _seconds: runner.request_shutdown(),
        logger=configure_json_logger(stream=io.StringIO(), name="sf058-early-shutdown"),
    )
    monkeypatch.setattr(runner, "prepare", lambda: prepared)
    activated: list[bool] = []
    monkeypatch.setattr(runner, "_activate", lambda _prepared: activated.append(True))
    monkeypatch.setattr(runner, "_shutdown", lambda _prepared: None)

    assert runner.run() is LivePaperExitCode.OK
    assert activated == []


def test_activate_wires_only_paper_runtime_components(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    at = datetime(2026, 10, 5, 9, 15, tzinfo=IST)
    prepared = _prepared(at)
    runner = LivePaperRunner(
        config_path=_write_config(tmp_path),
        env=_env(),
        now=lambda: at,
        logger=configure_json_logger(stream=io.StringIO(), name="sf058-activate"),
    )
    feed = _FakeLiveFeed()
    adapter_kwargs: dict[str, object] = {}
    bootstrap_kwargs: dict[str, object] = {}

    def adapter(**kwargs: object) -> _FakeLiveFeed:
        adapter_kwargs.update(kwargs)
        return feed

    fake_runtime = _FakeOperatorRuntime()

    def bootstrap(**kwargs: object) -> _FakeOperatorRuntime:
        bootstrap_kwargs.update(kwargs)
        return fake_runtime

    monkeypatch.setattr("signalforge.live_paper.OpenAlgoMarketDataAdapter", adapter)
    monkeypatch.setattr("signalforge.live_paper.LiveRuntime.bootstrap", bootstrap)

    runner._activate(prepared)

    assert runner._runtime is fake_runtime
    assert adapter_kwargs["instrument_id"] == prepared.instrument_id
    assert adapter_kwargs["subscription"] == prepared.reference.subscription
    bounded_feed = bootstrap_kwargs["feed"]
    assert isinstance(bounded_feed, _SessionBoundedLiveFeed)
    assert bounded_feed.delegate is feed
    assert bootstrap_kwargs["quantity"] == Quantity(10)
    assert bootstrap_kwargs["strategy"] is prepared.strategy


def test_operator_loop_logs_material_step_and_feed_state_once(
    tmp_path: Path,
) -> None:
    at_values = [
        datetime(2026, 10, 5, 10, 0, tzinfo=IST),
        datetime(2026, 10, 5, 10, 0, 1, tzinfo=IST),
        datetime(2026, 10, 5, 15, 30, tzinfo=IST),
    ]
    index = [0]

    def now() -> datetime:
        value = at_values[min(index[0], len(at_values) - 1)]
        index[0] += 1
        return value

    candle = SimpleNamespace(
        interval=SimpleNamespace(
            start=datetime(2026, 10, 5, 9, 55, tzinfo=IST),
            end=datetime(2026, 10, 5, 10, 0, tzinfo=IST),
        )
    )
    evaluation = SimpleNamespace(
        qualified=False,
        actionable=False,
        reasons=("warmup_incomplete",),
    )
    step = SimpleNamespace(
        feed_state=MarketDataFeedState.HEALTHY,
        completed_candle=candle,
        evaluation=evaluation,
    )
    runtime = _FakeOperatorRuntime(steps=[step])
    stream = io.StringIO()
    runner = LivePaperRunner(
        config_path=_write_config(tmp_path),
        env=_env(),
        now=now,
        logger=configure_json_logger(stream=stream, name="sf058-loop-log"),
    )
    runner._runtime = runtime  # type: ignore[assignment]

    runner._operator_loop()

    records = [json.loads(line) for line in stream.getvalue().splitlines()]
    events = [record["event"] for record in records]
    assert events.count("feed_state") == 1
    assert "candle_completed" in events
    assert "strategy_decision" in events
    assert runtime.poll_calls == 1
    assert len(runtime.time_calls) == 1
    assert runtime.call_order == ["poll", "time"]


def test_shutdown_requested_during_poll_skips_new_time_dispatch(
    tmp_path: Path,
) -> None:
    at = datetime(2026, 10, 5, 10, 0, tzinfo=IST)
    step = SimpleNamespace(
        market_event=SimpleNamespace(exchange_timestamp=at),
        feed_state=MarketDataFeedState.HEALTHY,
        completed_candle=None,
        evaluation=None,
    )
    runtime = _FakeOperatorRuntime(steps=[step])
    runner = LivePaperRunner(
        config_path=_write_config(tmp_path),
        env=_env(),
        now=lambda: at,
        logger=configure_json_logger(stream=io.StringIO(), name="sf058-stop-after-poll"),
    )
    runner._runtime = runtime  # type: ignore[assignment]

    original_poll = runtime.poll_once

    def poll_and_stop() -> object:
        result = original_poll()
        runner.request_shutdown()
        return result

    runtime.poll_once = poll_and_stop  # type: ignore[method-assign]

    runner._operator_loop()

    assert runtime.poll_calls == 1
    assert runtime.time_calls == []
    assert runtime.call_order == ["poll"]


def test_session_bounded_feed_accepts_1530_and_rejects_later_event() -> None:
    boundary = datetime(2026, 10, 5, 15, 30, tzinfo=IST)
    accepted = SimpleNamespace(exchange_timestamp=boundary)
    rejected = SimpleNamespace(
        exchange_timestamp=datetime(2026, 10, 5, 15, 30, 0, 1, tzinfo=IST)
    )
    delegate = _FakeLiveFeed([accepted, rejected])
    feed = _SessionBoundedLiveFeed(
        delegate,  # type: ignore[arg-type]
        session_open_at=datetime(2026, 10, 5, 9, 15, tzinfo=IST),
        session_boundary_at=boundary,
    )

    assert feed.receive_once() is accepted
    assert not feed.session_complete
    assert feed.receive_once() is None
    assert feed.session_complete


def test_operator_loop_drains_boundary_event_then_stops_on_post_session_event(
    tmp_path: Path,
) -> None:
    at = datetime(2026, 10, 5, 15, 30, tzinfo=IST)
    accepted = SimpleNamespace(exchange_timestamp=at)
    rejected = SimpleNamespace(
        exchange_timestamp=datetime(2026, 10, 5, 15, 30, 1, tzinfo=IST)
    )
    delegate = _FakeLiveFeed([accepted, rejected])
    bounded = _SessionBoundedLiveFeed(
        delegate,  # type: ignore[arg-type]
        session_open_at=datetime(2026, 10, 5, 9, 15, tzinfo=IST),
        session_boundary_at=at,
    )

    class BoundaryRuntime(_FakeOperatorRuntime):
        def poll_once(self) -> object:
            self.call_order.append("poll")
            self.poll_calls += 1
            event = bounded.receive_once()
            return SimpleNamespace(
                market_event=event,
                feed_state=MarketDataFeedState.HEALTHY,
                completed_candle=None,
                evaluation=None,
            )

    runtime = BoundaryRuntime()
    runtime.feed = bounded
    runner = LivePaperRunner(
        config_path=_write_config(tmp_path),
        env=_env(),
        now=lambda: at,
        logger=configure_json_logger(stream=io.StringIO(), name="sf058-boundary-drain"),
    )
    runner._runtime = runtime  # type: ignore[assignment]
    runner._session_feed = bounded

    runner._operator_loop()

    assert runtime.poll_calls == 2
    assert runtime.time_calls == [at, at]
    assert runtime.call_order == ["poll", "time", "poll", "time"]
    assert bounded.session_complete


def test_shutdown_requested_after_prepare_prevents_activation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    at = datetime(2026, 10, 5, 9, 15, tzinfo=IST)
    prepared = _prepared(at)
    runner = LivePaperRunner(
        config_path=_write_config(tmp_path),
        env=_env(),
        now=lambda: at,
        logger=configure_json_logger(stream=io.StringIO(), name="sf058-cancel-before-activate"),
    )

    def prepare() -> LivePaperPrepared:
        runner.request_shutdown()
        return prepared

    activated: list[bool] = []
    monkeypatch.setattr(runner, "prepare", prepare)
    monkeypatch.setattr(runner, "_activate", lambda _prepared: activated.append(True))
    monkeypatch.setattr(runner, "_shutdown", lambda _prepared: None)

    assert runner.run() is LivePaperExitCode.OK
    assert activated == []


def test_operator_loop_stops_on_reconciliation_required(
    tmp_path: Path,
) -> None:
    at = datetime(2026, 10, 5, 10, 0, tzinfo=IST)
    step = SimpleNamespace(
        feed_state=MarketDataFeedState.STALE,
        completed_candle=None,
        evaluation=None,
    )
    runtime = _FakeOperatorRuntime(
        continuity=LiveRuntimeContinuity.RECONCILIATION_REQUIRED,
        steps=[step],
    )
    runner = LivePaperRunner(
        config_path=_write_config(tmp_path),
        env=_env(),
        now=lambda: at,
        logger=configure_json_logger(stream=io.StringIO(), name="sf058-loop-recon"),
    )
    runner._runtime = runtime  # type: ignore[assignment]

    with pytest.raises(LiveRuntimeReconciliationRequired):
        runner._operator_loop()


def test_operator_loop_stops_on_terminal_runtime(
    tmp_path: Path,
) -> None:
    at = datetime(2026, 10, 5, 10, 0, tzinfo=IST)
    step = SimpleNamespace(
        feed_state=MarketDataFeedState.HEALTHY,
        completed_candle=None,
        evaluation=None,
    )
    runtime = _FakeOperatorRuntime(
        continuity=LiveRuntimeContinuity.TERMINAL,
        steps=[step],
    )
    runner = LivePaperRunner(
        config_path=_write_config(tmp_path),
        env=_env(),
        now=lambda: at,
        logger=configure_json_logger(stream=io.StringIO(), name="sf058-loop-terminal"),
    )
    runner._runtime = runtime  # type: ignore[assignment]

    with pytest.raises(LiveRuntimeError):
        runner._operator_loop()


def test_shutdown_closes_feed_disposes_engine_and_reports_final_state(
    tmp_path: Path,
) -> None:
    at = datetime(2026, 10, 5, 10, 0, tzinfo=IST)
    engine = FakeEngine()
    prepared = _prepared(at, engine=engine)
    runtime = _FakeOperatorRuntime()
    stream = io.StringIO()
    runner = LivePaperRunner(
        config_path=_write_config(tmp_path),
        env=_env(),
        logger=configure_json_logger(stream=stream, name="sf058-shutdown"),
    )
    runner._runtime = runtime  # type: ignore[assignment]

    runner._shutdown(prepared)

    assert runtime.feed.closed
    assert engine.disposed
    record = json.loads(stream.getvalue().splitlines()[-1])
    assert record["event"] == "shutdown"
    assert record["continuity"] == LiveRuntimeContinuity.CONTINUOUS.value
    assert record["feed_state"] == MarketDataFeedState.HEALTHY.value


def test_shutdown_close_failure_is_redacted_and_does_not_skip_dispose(
    tmp_path: Path,
) -> None:
    at = datetime(2026, 10, 5, 10, 0, tzinfo=IST)
    engine = FakeEngine()
    prepared = _prepared(at, engine=engine)
    secret = _env()["OPENALGO_API_KEY"]

    class FailingFeed(_FakeLiveFeed):
        def close(self) -> None:
            raise RuntimeError(f"close failed {secret}")

    runtime = _FakeOperatorRuntime()
    runtime.feed = FailingFeed()
    stream = io.StringIO()
    runner = LivePaperRunner(
        config_path=_write_config(tmp_path),
        env=_env(),
        logger=configure_json_logger(stream=stream, name="sf058-shutdown-fail"),
    )
    runner._runtime = runtime  # type: ignore[assignment]

    runner._shutdown(prepared)

    output = stream.getvalue()
    assert secret not in output
    assert "<redacted>" in output
    assert engine.disposed



def test_missing_database_url_fails_before_database_creation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = _env()
    env.pop("DATABASE_URL")
    created: list[bool] = []
    monkeypatch.setattr(
        "signalforge.live_paper.sa.create_engine",
        lambda _url: created.append(True),
    )
    runner = LivePaperRunner(
        config_path=_write_config(tmp_path),
        env=env,
        logger=configure_json_logger(stream=io.StringIO(), name="sf058-missing-db"),
    )

    assert runner.run() is LivePaperExitCode.STARTUP_FAILED
    assert created == []


def test_preflight_exception_disposes_engine_and_prevents_reference(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = FakeEngine()
    referenced: list[bool] = []
    monkeypatch.setattr("signalforge.live_paper.sa.create_engine", lambda _url: engine)
    monkeypatch.setattr(
        "signalforge.live_paper.preflight",
        lambda _config: (_ for _ in ()).throw(RuntimeError("preflight failed")),
    )
    monkeypatch.setattr(
        "signalforge.live_paper.resolve_nse_equity_reference",
        lambda **_kwargs: referenced.append(True),
    )
    runner = LivePaperRunner(
        config_path=_write_config(tmp_path),
        env=_env(),
        logger=configure_json_logger(stream=io.StringIO(), name="sf058-preflight-exception"),
    )

    assert runner.run() is LivePaperExitCode.STARTUP_FAILED
    assert referenced == []
    assert engine.disposed


def test_recovery_exception_disposes_engine_and_prevents_activation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    at = datetime(2026, 10, 5, 8, 30, tzinfo=IST)
    engine = _patch_prepare_dependencies(monkeypatch, at=at)
    monkeypatch.setattr(
        "signalforge.live_paper.RecoveryBootstrap.inspect",
        lambda self, **_kwargs: (_ for _ in ()).throw(RuntimeError("corrupt recovery")),
    )
    runner = LivePaperRunner(
        config_path=_write_config(tmp_path),
        env=_env(),
        now=lambda: at,
        logger=configure_json_logger(stream=io.StringIO(), name="sf058-recovery-exception"),
    )
    activated: list[bool] = []
    monkeypatch.setattr(runner, "_activate", lambda _prepared: activated.append(True))

    assert runner.run() is LivePaperExitCode.STARTUP_FAILED
    assert activated == []
    assert engine.disposed


def test_live_paper_command_restores_signal_handlers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _write_config(tmp_path)
    calls: list[str] = []

    class FakeRunner:
        def __init__(self, *, config_path: Path) -> None:
            assert config_path == config

        def run(self) -> LivePaperExitCode:
            calls.append("run")
            return LivePaperExitCode.OK

    monkeypatch.setattr("signalforge.live_paper.LivePaperRunner", FakeRunner)
    monkeypatch.setattr(
        "signalforge.live_paper.install_shutdown_handlers",
        lambda _runner: calls.append("install") or {signal.SIGINT: signal.SIG_DFL},
    )
    monkeypatch.setattr(
        "signalforge.live_paper.restore_shutdown_handlers",
        lambda _prior: calls.append("restore"),
    )

    assert live_paper_command(config) == 0
    assert calls == ["install", "run", "restore"]



def test_exact_0915_activation_boundary_is_allowed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    at = datetime(2026, 10, 5, 9, 15, tzinfo=IST)
    prepared = _prepared(at)
    runner = LivePaperRunner(
        config_path=_write_config(tmp_path),
        env=_env(),
        now=lambda: at,
        logger=configure_json_logger(stream=io.StringIO(), name="sf058-exact-boundary"),
    )
    monkeypatch.setattr(runner, "prepare", lambda: prepared)
    activated: list[bool] = []

    def activate(_prepared: LivePaperPrepared) -> None:
        activated.append(True)
        runner._runtime = SimpleNamespace(
            continuity=LiveRuntimeContinuity.CONTINUOUS
        )  # type: ignore[assignment]

    monkeypatch.setattr(runner, "_activate", activate)
    monkeypatch.setattr(runner, "_operator_loop", lambda: None)
    monkeypatch.setattr(runner, "_shutdown", lambda _prepared: None)

    assert runner.run() is LivePaperExitCode.OK
    assert activated == [True]


def test_pre_session_wait_activates_on_first_active_scheduler_tick(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current = [datetime(2026, 10, 5, 9, 14, 59, tzinfo=IST)]
    prepared = _prepared(current[0])
    runner = LivePaperRunner(
        config_path=_write_config(tmp_path),
        env=_env(),
        now=lambda: current[0],
        sleep=lambda _seconds: current.__setitem__(
            0, datetime(2026, 10, 5, 9, 15, 1, tzinfo=IST)
        ),
        logger=configure_json_logger(stream=io.StringIO(), name="sf058-overshoot"),
    )
    monkeypatch.setattr(runner, "prepare", lambda: prepared)
    activated: list[bool] = []

    def activate(_prepared: LivePaperPrepared) -> None:
        activated.append(True)
        runner._runtime = SimpleNamespace(
            continuity=LiveRuntimeContinuity.CONTINUOUS
        )  # type: ignore[assignment]

    monkeypatch.setattr(runner, "_activate", activate)
    monkeypatch.setattr(runner, "_operator_loop", lambda: None)
    monkeypatch.setattr(runner, "_shutdown", lambda _prepared: None)

    assert runner.run() is LivePaperExitCode.OK
    assert activated == [True]
