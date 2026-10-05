from __future__ import annotations

import io
import json
import signal
from datetime import datetime
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
from signalforge.domain.money import Price
from signalforge.domain.provenance import RunIdentity
from signalforge.domain.session import NseSessionPhase, nse_session_phase
from signalforge.domain.time import IST
from signalforge.live_paper import (
    LivePaperExitCode,
    LivePaperPrepared,
    LivePaperRunner,
    configure_json_logger,
    install_shutdown_handlers,
    restore_shutdown_handlers,
)
from signalforge.runtime.live_runtime import LiveRuntimeContinuity
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
    )


def _patch_prepare_dependencies(
    monkeypatch: pytest.MonkeyPatch,
    *,
    at: datetime,
    disposition: RecoveryDisposition = RecoveryDisposition.NEW,
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
    at = datetime(2026, 10, 5, 10, 0, tzinfo=IST)
    prepared = _prepared(at)
    stream = io.StringIO()
    runner = LivePaperRunner(
        config_path=_write_config(tmp_path),
        env=_env(),
        now=lambda: at,
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
