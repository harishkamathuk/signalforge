"""Read-only recovery bootstrap for persisted M6 state."""

from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy.orm import Session

from signalforge.domain.armed import ArmedSetup, ArmedSetupState
from signalforge.domain.exits import Exit
from signalforge.domain.ids import InstrumentId
from signalforge.domain.position_outcomes import PositionOpenOutcome, PositionOpenOutcomeType
from signalforge.domain.positions import Position, PositionState
from signalforge.domain.provenance import RunIdentity
from signalforge.domain.signals import Signal
from signalforge.domain.trades import Trade, TradeState
from signalforge.persistence.errors import ContradictoryFactError
from signalforge.persistence.repositories import (
    PostgresArmedSetupRepository,
    PostgresExitRepository,
    PostgresFillRepository,
    PostgresIndicatorCheckpointRepository,
    PostgresPositionOpenOutcomeRepository,
    PostgresPositionRepository,
    PostgresRunProvenanceRepository,
    PostgresSignalRepository,
    PostgresTradeRepository,
)
from signalforge.runtime.indicators import IndicatorEngineState


class RecoveryDisposition(StrEnum):
    NEW = "new"
    RESUMABLE = "resumable"


@dataclass(frozen=True, slots=True)
class RecoveredLifecycle:
    setup: ArmedSetup | None
    signal: Signal | None
    outcome: PositionOpenOutcome | None
    trade: Trade | None
    position: Position | None
    exit_fact: Exit | None


@dataclass(frozen=True, slots=True)
class RecoveryResult:
    disposition: RecoveryDisposition
    run: RunIdentity
    indicator_state: IndicatorEngineState | None
    lifecycle: RecoveredLifecycle


class RecoveryBootstrap:
    def inspect(
        self, *, session: Session, requested_run: RunIdentity, instrument_id: InstrumentId
    ) -> RecoveryResult:
        run = PostgresRunProvenanceRepository(session).get(requested_run.run_id)
        signals = (
            PostgresSignalRepository(session).find_for_run_instrument(
                requested_run.run_id, instrument_id
            )
            if run
            else ()
        )
        setups = (
            PostgresArmedSetupRepository(session).find_for_run_instrument(
                requested_run.run_id, instrument_id
            )
            if run
            else ()
        )
        fills = (
            PostgresFillRepository(session).find_for_run_instrument(
                requested_run.run_id, instrument_id
            )
            if run
            else ()
        )
        outcomes = (
            PostgresPositionOpenOutcomeRepository(session).find_for_run_instrument(
                requested_run.run_id, instrument_id
            )
            if run
            else ()
        )
        trades = (
            PostgresTradeRepository(session).find_for_run_instrument(
                requested_run.run_id, instrument_id
            )
            if run
            else ()
        )
        positions = (
            PostgresPositionRepository(session).find_for_run_instrument(
                requested_run.run_id, instrument_id
            )
            if run
            else ()
        )
        exits = (
            PostgresExitRepository(session).find_for_run_instrument(
                requested_run.run_id, instrument_id
            )
            if run
            else ()
        )
        checkpoint = (
            PostgresIndicatorCheckpointRepository(session).get(requested_run.run_id, instrument_id)
            if run
            else None
        )
        if run is None:
            return RecoveryResult(
                RecoveryDisposition.NEW,
                requested_run,
                None,
                RecoveredLifecycle(None, None, None, None, None, None),
            )
        if run != requested_run:
            raise ContradictoryFactError("persisted run provenance differs from requested runtime")
        if checkpoint is not None and (
            checkpoint.instrument_id != instrument_id
            or checkpoint.calculation_version != requested_run.engine_calculation_version
        ):
            raise ContradictoryFactError(
                "persisted indicator checkpoint contradicts requested runtime"
            )
        if len(outcomes) != len(fills):
            raise ContradictoryFactError("persisted fill lacks a completed position-open outcome")
        if any(
            item.outcome is PositionOpenOutcomeType.REJECTED_NON_POSITIVE_RISK for item in outcomes
        ) and (trades or positions):
            raise ContradictoryFactError(
                "rejected open outcome conflicts with persisted trade or position"
            )

        armed = tuple(item for item in setups if item.state is ArmedSetupState.ARMED)
        open_trades = tuple(item for item in trades if item.state is TradeState.OPEN)
        open_positions = tuple(item for item in positions if item.state is PositionState.OPEN)
        if len(armed) > 1 or len(open_trades) > 1 or len(open_positions) > 1:
            raise ContradictoryFactError("multiple active lifecycle graphs are not supported")
        if armed and (open_trades or open_positions):
            raise ContradictoryFactError("persisted ARMED and OPEN lifecycle states conflict")
        closed_trades = tuple(item for item in trades if item.state is TradeState.CLOSED)
        closed_positions = tuple(item for item in positions if item.state is PositionState.CLOSED)
        if bool(closed_trades) != bool(closed_positions) or len(closed_trades) != len(exits):
            raise ContradictoryFactError(
                "persisted CLOSED lifecycle lacks matching trade, position, or exit"
            )

        if bool(open_trades) != bool(open_positions):
            raise ContradictoryFactError("persisted trade and position active states conflict")
        trade = open_trades[0] if open_trades else None
        position = open_positions[0] if open_positions else None
        outcome = next(
            (
                item
                for item in outcomes
                if trade is not None and item.fill_id == trade.entry_fill_id
            ),
            None,
        )
        if trade is not None and (
            outcome is None
            or outcome.outcome is not PositionOpenOutcomeType.OPENED
            or position is None
            or position.trade_id != trade.trade_id
        ):
            raise ContradictoryFactError(
                "OPEN lifecycle lacks a consistent fill outcome and position"
            )
        setup = armed[0] if armed else None
        signal_id = (
            setup.signal_id
            if setup is not None
            else (trade.signal_id if trade is not None else None)
        )
        signal = next((item for item in signals if item.signal_id == signal_id), None)
        if signal_id is not None and signal is None:
            raise ContradictoryFactError("active lifecycle references a missing signal")
        exit_fact = exits[0] if len(exits) == 1 else None
        return RecoveryResult(
            RecoveryDisposition.RESUMABLE,
            run,
            checkpoint,
            RecoveredLifecycle(setup, signal, outcome, trade, position, exit_fact),
        )
