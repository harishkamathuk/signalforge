"""Caller-session PostgreSQL adapters for immutable facts and provenance.

The adapters execute writes immediately but leave commit and rollback ownership with
their caller. PostgreSQL ``ON CONFLICT DO NOTHING`` keeps expected duplicate races from
poisoning the caller's transaction; the persisted domain fact is then compared with the
requested fact to distinguish an exact retry from contradictory identity reuse.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import cast

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session
from sqlalchemy.sql.selectable import FromClause, TableClause

from signalforge.domain.armed import ArmedSetup, ArmedSetupState
from signalforge.domain.audit import StateTransition
from signalforge.domain.execution import EntryIntent, Fill, TriggerEvent
from signalforge.domain.exits import Exit
from signalforge.domain.ids import (
    EntryIntentId,
    ExitId,
    FillId,
    InstrumentId,
    PositionId,
    PositionOpenOutcomeId,
    RunId,
    SignalId,
    StateTransitionId,
    TradeId,
    TriggerEventId,
)
from signalforge.domain.position_outcomes import PositionOpenOutcome
from signalforge.domain.positions import Position, PositionState
from signalforge.domain.provenance import RunIdentity
from signalforge.domain.signals import Signal
from signalforge.domain.strategy import StrategyEvaluation
from signalforge.domain.time import CandleInterval
from signalforge.domain.trades import Trade, TradeState
from signalforge.persistence.errors import (
    ContradictoryFactError,
    PersistenceDependencyError,
    PersistenceError,
)
from signalforge.persistence.mappers import (
    armed_setup_from_record,
    armed_setup_record_from_domain,
    entry_intent_from_record,
    entry_intent_record_from_domain,
    exit_from_record,
    exit_record_from_domain,
    fill_from_record,
    fill_record_from_domain,
    indicator_checkpoint_record_from_state,
    indicator_checkpoint_state_from_record,
    position_from_record,
    position_open_outcome_from_record,
    position_open_outcome_record_from_domain,
    position_record_from_domain,
    run_identity_from_records,
    run_record_from_domain,
    signal_from_record,
    signal_record_from_domain,
    state_transition_from_record,
    state_transition_record_from_domain,
    strategy_config_record_from_domain,
    strategy_evaluation_from_record,
    strategy_evaluation_record_from_domain,
    trade_from_record,
    trade_record_from_domain,
    trigger_event_from_record,
    trigger_event_record_from_domain,
)
from signalforge.persistence.models import (
    ArmedSetupRecord,
    EntryIntentRecord,
    ExitRecord,
    FillRecord,
    IndicatorCheckpointRecord,
    PositionOpenOutcomeRecord,
    PositionRecord,
    RunRecord,
    SignalRecord,
    StateTransitionRecord,
    StrategyConfigRecord,
    StrategyEvaluationRecord,
    TradeRecord,
    TriggerEventRecord,
)
from signalforge.runtime.indicators import IndicatorEngineState


def _insert_ignoring_unique_conflicts(
    session: Session,
    table: FromClause,
    record: object,
) -> None:
    values = {column.name: getattr(record, column.name) for column in table.columns}
    session.execute(insert(cast(TableClause, table)).values(values).on_conflict_do_nothing())


def _single_collision[RecordT](records: Sequence[RecordT], *, fact_name: str) -> RecordT | None:
    if len(records) > 1:
        raise ContradictoryFactError(
            f"{fact_name} primary and alternate identities resolve to different stored facts"
        )
    return records[0] if records else None


def _append_immutable[FactT, RecordT](
    *,
    session: Session,
    table: FromClause,
    record: object,
    requested: FactT,
    find_existing: Callable[[], RecordT | None],
    hydrate: Callable[[RecordT], FactT],
    fact_name: str,
) -> FactT:
    existing = find_existing()
    if existing is None:
        _insert_ignoring_unique_conflicts(session, table, record)
        existing = find_existing()
    if existing is None:
        raise PersistenceError(f"{fact_name} insert did not produce a persisted fact")
    persisted = hydrate(existing)
    if persisted != requested:
        raise ContradictoryFactError(f"stored {fact_name} contradicts requested immutable fact")
    return persisted


def _same_record_fields(
    stored: object,
    candidate: object,
    fields: tuple[str, ...],
) -> bool:
    return all(getattr(stored, field) == getattr(candidate, field) for field in fields)


class _PostgresRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def _load_run(self, run_id: RunId | str) -> RunIdentity | None:
        run = self._session.get(RunRecord, str(run_id))
        if run is None:
            return None
        config = self._session.get(StrategyConfigRecord, run.config_id)
        if config is None:
            raise PersistenceDependencyError(
                f"run {run.run_id!r} references missing config {run.config_id!r}"
            )
        return run_identity_from_records(run, config)

    def _require_run(self, expected: RunIdentity) -> RunIdentity:
        persisted = self._load_run(expected.run_id)
        if persisted is None:
            raise PersistenceDependencyError(
                f"run provenance {expected.run_id!s} must be persisted first"
            )
        if persisted != expected:
            raise ContradictoryFactError(
                f"stored run provenance {expected.run_id!s} contradicts fact provenance"
            )
        return persisted

    def _require_record[RecordT](
        self, model: type[RecordT], identity: str, *, name: str
    ) -> RecordT:
        record = self._session.get(model, identity)
        if record is None:
            raise PersistenceDependencyError(f"{name} {identity!r} must be persisted first")
        return record


class PostgresRunProvenanceRepository(_PostgresRepository):
    """Persist complete immutable config and run provenance using the caller's Session."""

    def _find_config(self, candidate: StrategyConfigRecord) -> StrategyConfigRecord | None:
        records = self._session.scalars(
            sa.select(StrategyConfigRecord).where(
                sa.or_(
                    StrategyConfigRecord.config_id == candidate.config_id,
                    sa.and_(
                        StrategyConfigRecord.strategy_id == candidate.strategy_id,
                        StrategyConfigRecord.strategy_version == candidate.strategy_version,
                        StrategyConfigRecord.config_hash == candidate.config_hash,
                    ),
                )
            )
        ).all()
        return _single_collision(records, fact_name="strategy config provenance")

    @staticmethod
    def _same_config(
        stored: StrategyConfigRecord,
        candidate: StrategyConfigRecord,
    ) -> bool:
        return (
            stored.config_id,
            stored.strategy_id,
            stored.strategy_version,
            stored.config_hash,
        ) == (
            candidate.config_id,
            candidate.strategy_id,
            candidate.strategy_version,
            candidate.config_hash,
        )

    def add(self, run: RunIdentity) -> RunIdentity:
        config_candidate = strategy_config_record_from_domain(run)
        run_candidate = run_record_from_domain(run)
        with self._session.begin_nested():
            config = self._find_config(config_candidate)
            if config is None:
                _insert_ignoring_unique_conflicts(
                    self._session,
                    StrategyConfigRecord.__table__,
                    config_candidate,
                )
                config = self._find_config(config_candidate)
            if config is None:
                raise PersistenceError("config provenance insert produced no persisted record")
            if not self._same_config(config, config_candidate):
                raise ContradictoryFactError(
                    "stored strategy config contradicts requested immutable provenance"
                )

            stored_run = self._session.get(RunRecord, run_candidate.run_id)
            if stored_run is None:
                _insert_ignoring_unique_conflicts(
                    self._session,
                    RunRecord.__table__,
                    run_candidate,
                )
                stored_run = self._session.get(RunRecord, run_candidate.run_id)
            if stored_run is None:
                raise PersistenceError("run provenance insert produced no persisted record")
            persisted = run_identity_from_records(stored_run, config)
            if persisted != run:
                raise ContradictoryFactError(
                    "stored run contradicts requested immutable provenance"
                )
        return persisted

    def get(self, run_id: RunId) -> RunIdentity | None:
        return self._load_run(run_id)


class PostgresStrategyEvaluationRepository(_PostgresRepository):
    def append(
        self,
        run_id: RunId,
        evaluation: StrategyEvaluation,
    ) -> StrategyEvaluation:
        if self._load_run(run_id) is None:
            raise PersistenceDependencyError(f"run provenance {run_id!s} must be persisted first")
        candidate = strategy_evaluation_record_from_domain(run_id, evaluation)

        def find() -> StrategyEvaluationRecord | None:
            return self._session.get(
                StrategyEvaluationRecord,
                (
                    str(run_id),
                    str(evaluation.instrument_id),
                    evaluation.interval.start,
                    evaluation.interval.end,
                ),
            )

        return _append_immutable(
            session=self._session,
            table=StrategyEvaluationRecord.__table__,
            record=candidate,
            requested=evaluation,
            find_existing=find,
            hydrate=strategy_evaluation_from_record,
            fact_name="strategy evaluation",
        )

    def get(
        self,
        run_id: RunId,
        instrument_id: InstrumentId,
        interval: CandleInterval,
    ) -> StrategyEvaluation | None:
        record = self._session.get(
            StrategyEvaluationRecord,
            (str(run_id), str(instrument_id), interval.start, interval.end),
        )
        return None if record is None else strategy_evaluation_from_record(record)


class PostgresSignalRepository(_PostgresRepository):
    def _find(self, signal: Signal) -> SignalRecord | None:
        records = self._session.scalars(
            sa.select(SignalRecord).where(
                sa.or_(
                    SignalRecord.signal_id == str(signal.signal_id),
                    sa.and_(
                        SignalRecord.run_id == str(signal.run.run_id),
                        SignalRecord.instrument_id == str(signal.instrument_id),
                        SignalRecord.interval_start == signal.interval.start,
                        SignalRecord.interval_end == signal.interval.end,
                    ),
                )
            )
        ).all()
        return _single_collision(records, fact_name="signal")

    def append(self, signal: Signal) -> Signal:
        run = self._require_run(signal.run)
        candidate = signal_record_from_domain(signal)
        return _append_immutable(
            session=self._session,
            table=SignalRecord.__table__,
            record=candidate,
            requested=signal,
            find_existing=lambda: self._find(signal),
            hydrate=lambda record: signal_from_record(record, run),
            fact_name="signal",
        )

    def get(self, signal_id: SignalId) -> Signal | None:
        record = self._session.get(SignalRecord, str(signal_id))
        if record is None:
            return None
        run = self._load_run(record.run_id)
        if run is None:
            raise PersistenceDependencyError("signal references missing run provenance")
        return signal_from_record(record, run)


class PostgresTriggerEventRepository(_PostgresRepository):
    def append(self, event: TriggerEvent) -> TriggerEvent:
        run = self._require_run(event.run)
        self._require_record(SignalRecord, str(event.signal_id), name="signal")
        candidate = trigger_event_record_from_domain(event)
        return _append_immutable(
            session=self._session,
            table=TriggerEventRecord.__table__,
            record=candidate,
            requested=event,
            find_existing=lambda: self._session.get(
                TriggerEventRecord, str(event.trigger_event_id)
            ),
            hydrate=lambda record: trigger_event_from_record(record, run),
            fact_name="trigger event",
        )

    def get(self, event_id: TriggerEventId) -> TriggerEvent | None:
        record = self._session.get(TriggerEventRecord, str(event_id))
        if record is None:
            return None
        run = self._load_run(record.run_id)
        if run is None:
            raise PersistenceDependencyError("trigger event references missing run provenance")
        return trigger_event_from_record(record, run)


class PostgresEntryIntentRepository(_PostgresRepository):
    def _find(self, intent: EntryIntent) -> EntryIntentRecord | None:
        records = self._session.scalars(
            sa.select(EntryIntentRecord).where(
                sa.or_(
                    EntryIntentRecord.entry_intent_id == str(intent.entry_intent_id),
                    EntryIntentRecord.trigger_event_id == str(intent.trigger_event_id),
                )
            )
        ).all()
        return _single_collision(records, fact_name="entry intent")

    def append(self, intent: EntryIntent) -> EntryIntent:
        run = self._require_run(intent.run)
        self._require_record(
            TriggerEventRecord,
            str(intent.trigger_event_id),
            name="trigger event",
        )
        self._require_record(SignalRecord, str(intent.signal_id), name="signal")
        candidate = entry_intent_record_from_domain(intent)
        return _append_immutable(
            session=self._session,
            table=EntryIntentRecord.__table__,
            record=candidate,
            requested=intent,
            find_existing=lambda: self._find(intent),
            hydrate=lambda record: entry_intent_from_record(record, run),
            fact_name="entry intent",
        )

    def get(self, intent_id: EntryIntentId) -> EntryIntent | None:
        record = self._session.get(EntryIntentRecord, str(intent_id))
        if record is None:
            return None
        run = self._load_run(record.run_id)
        if run is None:
            raise PersistenceDependencyError("entry intent references missing run provenance")
        return entry_intent_from_record(record, run)


class PostgresFillRepository(_PostgresRepository):
    def _find(self, fill: Fill) -> FillRecord | None:
        records = self._session.scalars(
            sa.select(FillRecord).where(
                sa.or_(
                    FillRecord.fill_id == str(fill.fill_id),
                    FillRecord.entry_intent_id == str(fill.entry_intent_id),
                )
            )
        ).all()
        return _single_collision(records, fact_name="fill")

    def append(self, fill: Fill) -> Fill:
        run = self._require_run(fill.run)
        self._require_record(
            EntryIntentRecord,
            str(fill.entry_intent_id),
            name="entry intent",
        )
        self._require_record(
            TriggerEventRecord,
            str(fill.trigger_event_id),
            name="trigger event",
        )
        self._require_record(SignalRecord, str(fill.signal_id), name="signal")
        candidate = fill_record_from_domain(fill)
        return _append_immutable(
            session=self._session,
            table=FillRecord.__table__,
            record=candidate,
            requested=fill,
            find_existing=lambda: self._find(fill),
            hydrate=lambda record: fill_from_record(record, run),
            fact_name="fill",
        )

    def get(self, fill_id: FillId) -> Fill | None:
        record = self._session.get(FillRecord, str(fill_id))
        if record is None:
            return None
        run = self._load_run(record.run_id)
        if run is None:
            raise PersistenceDependencyError("fill references missing run provenance")
        return fill_from_record(record, run)


class PostgresPositionOpenOutcomeRepository(_PostgresRepository):
    """Persist one immutable completed open outcome for each entry Fill."""

    def _find(self, outcome: PositionOpenOutcome) -> PositionOpenOutcomeRecord | None:
        records = self._session.scalars(
            sa.select(PositionOpenOutcomeRecord).where(
                sa.or_(
                    PositionOpenOutcomeRecord.outcome_id == str(outcome.outcome_id),
                    PositionOpenOutcomeRecord.fill_id == str(outcome.fill_id),
                )
            )
        ).all()
        return _single_collision(records, fact_name="position open outcome")

    def append(self, outcome: PositionOpenOutcome) -> PositionOpenOutcome:
        run = self._require_run(outcome.run)
        fill = self._require_record(FillRecord, str(outcome.fill_id), name="fill")
        signal = self._require_record(SignalRecord, str(outcome.signal_id), name="signal")
        if signal.run_id != str(outcome.run.run_id):
            raise ContradictoryFactError("position open outcome contradicts signal provenance")
        if fill.signal_id != str(outcome.signal_id):
            raise ContradictoryFactError("position open outcome contradicts fill signal")
        if fill.run_id != str(outcome.run.run_id):
            raise ContradictoryFactError("position open outcome contradicts fill provenance")
        candidate = position_open_outcome_record_from_domain(outcome)
        return _append_immutable(
            session=self._session,
            table=PositionOpenOutcomeRecord.__table__,
            record=candidate,
            requested=outcome,
            find_existing=lambda: self._find(outcome),
            hydrate=lambda record: position_open_outcome_from_record(record, run),
            fact_name="position open outcome",
        )

    def get(self, outcome_id: PositionOpenOutcomeId) -> PositionOpenOutcome | None:
        record = self._session.get(PositionOpenOutcomeRecord, str(outcome_id))
        if record is None:
            return None
        run = self._load_run(record.run_id)
        if run is None:
            raise PersistenceDependencyError(
                "position open outcome references missing run provenance"
            )
        return position_open_outcome_from_record(record, run)


class PostgresExitRepository(_PostgresRepository):
    def _find(self, exit_fact: Exit) -> ExitRecord | None:
        records = self._session.scalars(
            sa.select(ExitRecord).where(
                sa.or_(
                    ExitRecord.exit_id == str(exit_fact.exit_id),
                    ExitRecord.exit_fill_id == str(exit_fact.exit_fill_id),
                    ExitRecord.trade_id == str(exit_fact.trade_id),
                    ExitRecord.position_id == str(exit_fact.position_id),
                )
            )
        ).all()
        return _single_collision(records, fact_name="exit")

    def append(self, exit_fact: Exit) -> Exit:
        run = self._require_run(exit_fact.run)
        self._require_record(TradeRecord, str(exit_fact.trade_id), name="trade")
        self._require_record(PositionRecord, str(exit_fact.position_id), name="position")
        candidate = exit_record_from_domain(exit_fact)
        return _append_immutable(
            session=self._session,
            table=ExitRecord.__table__,
            record=candidate,
            requested=exit_fact,
            find_existing=lambda: self._find(exit_fact),
            hydrate=lambda record: exit_from_record(record, run),
            fact_name="exit",
        )

    def get(self, exit_id: ExitId) -> Exit | None:
        record = self._session.get(ExitRecord, str(exit_id))
        if record is None:
            return None
        run = self._load_run(record.run_id)
        if run is None:
            raise PersistenceDependencyError("exit references missing run provenance")
        return exit_from_record(record, run)


class PostgresStateTransitionRepository(_PostgresRepository):
    def append(self, transition: StateTransition) -> StateTransition:
        run = self._require_run(transition.run)
        candidate = state_transition_record_from_domain(transition)
        return _append_immutable(
            session=self._session,
            table=StateTransitionRecord.__table__,
            record=candidate,
            requested=transition,
            find_existing=lambda: self._session.get(
                StateTransitionRecord, str(transition.transition_id)
            ),
            hydrate=lambda record: state_transition_from_record(record, run),
            fact_name="state transition",
        )

    def get(self, transition_id: StateTransitionId) -> StateTransition | None:
        record = self._session.get(StateTransitionRecord, str(transition_id))
        if record is None:
            return None
        run = self._load_run(record.run_id)
        if run is None:
            raise PersistenceDependencyError("state transition references missing run provenance")
        return state_transition_from_record(record, run)


class PostgresArmedSetupRepository(_PostgresRepository):
    """Persist authoritative ArmedSetup state with caller-owned transactions."""

    _IMMUTABLE_FIELDS = (
        "signal_id",
        "run_id",
        "raw_trigger",
        "tradable_trigger",
        "signal_low",
        "armed_at",
        "valid_until",
    )
    _STATE_FIELDS = ("state", "terminal_at", "expiry_reason")

    def _require_dependencies(self, run_id: RunId, setup: ArmedSetup) -> None:
        if self._load_run(run_id) is None:
            raise PersistenceDependencyError(f"run provenance {run_id!s} must be persisted first")
        signal = self._require_record(SignalRecord, str(setup.signal_id), name="signal")
        if signal.run_id != str(run_id):
            raise ContradictoryFactError("setup run contradicts the persisted signal provenance")

    def upsert(self, run_id: RunId, setup: ArmedSetup) -> ArmedSetup:
        self._require_dependencies(run_id, setup)
        candidate = armed_setup_record_from_domain(run_id, setup)
        stored = self._session.get(ArmedSetupRecord, candidate.signal_id)
        if stored is None:
            _insert_ignoring_unique_conflicts(self._session, ArmedSetupRecord.__table__, candidate)
            self._session.flush()
            stored = self._session.get(ArmedSetupRecord, candidate.signal_id)
        if stored is None:
            raise PersistenceError("armed setup insert produced no persisted record")
        if not _same_record_fields(stored, candidate, self._IMMUTABLE_FIELDS):
            raise ContradictoryFactError("stored armed setup contradicts immutable setup anchors")
        if _same_record_fields(stored, candidate, self._STATE_FIELDS):
            return armed_setup_from_record(stored)
        if stored.state != ArmedSetupState.ARMED.value or candidate.state not in {
            ArmedSetupState.TRIGGERED.value,
            ArmedSetupState.EXPIRED.value,
        }:
            raise ContradictoryFactError("stored armed setup cannot be replaced or regressed")
        result = cast(
            sa.CursorResult[object],
            self._session.execute(
                sa.update(ArmedSetupRecord)
                .where(
                    ArmedSetupRecord.signal_id == candidate.signal_id,
                    ArmedSetupRecord.state == ArmedSetupState.ARMED.value,
                )
                .values(
                    state=candidate.state,
                    terminal_at=candidate.terminal_at,
                    expiry_reason=candidate.expiry_reason,
                )
            ),
        )
        if result.rowcount == 1:
            self._session.flush()
        self._session.expire_all()
        stored = self._session.get(ArmedSetupRecord, candidate.signal_id)
        if stored is not None and _same_record_fields(stored, candidate, self._STATE_FIELDS):
            return armed_setup_from_record(stored)
        raise ContradictoryFactError("stored armed setup conflicts with requested terminal state")

    def get(self, signal_id: SignalId) -> ArmedSetup | None:
        record = self._session.get(ArmedSetupRecord, str(signal_id))
        return None if record is None else armed_setup_from_record(record)


class PostgresTradeRepository(_PostgresRepository):
    """Persist authoritative Trade state while freezing entry economics."""

    _IMMUTABLE_FIELDS = (
        "trade_id",
        "entry_fill_id",
        "signal_id",
        "run_id",
        "instrument_id",
        "entry_price",
        "stop_price",
        "raw_target_price",
        "tradable_target_price",
        "risk_per_share",
        "quantity",
        "opened_at",
    )
    _STATE_FIELDS = ("state", "closed_at", "exit_id")

    def _find(self, candidate: TradeRecord) -> TradeRecord | None:
        records = self._session.scalars(
            sa.select(TradeRecord).where(
                sa.or_(
                    TradeRecord.trade_id == candidate.trade_id,
                    TradeRecord.entry_fill_id == candidate.entry_fill_id,
                )
            )
        ).all()
        return _single_collision(records, fact_name="trade")

    def _require_dependencies(self, trade: Trade, candidate: TradeRecord) -> None:
        self._require_run(trade.run)
        entry_fill = self._require_record(FillRecord, candidate.entry_fill_id, name="entry fill")
        signal = self._require_record(SignalRecord, candidate.signal_id, name="signal")
        if entry_fill.run_id != candidate.run_id or signal.run_id != candidate.run_id:
            raise ContradictoryFactError(
                "trade dependencies contradict the requested run provenance"
            )
        if candidate.state == TradeState.CLOSED.value:
            exit_record = self._require_record(ExitRecord, candidate.exit_id or "", name="exit")
            if exit_record.trade_id != candidate.trade_id:
                raise ContradictoryFactError("trade close references an exit for a different trade")

    def upsert(self, trade: Trade) -> Trade:
        candidate = trade_record_from_domain(trade)
        self._require_dependencies(trade, candidate)
        stored = self._find(candidate)
        if stored is None:
            _insert_ignoring_unique_conflicts(self._session, TradeRecord.__table__, candidate)
            self._session.flush()
            stored = self._find(candidate)
        if stored is None:
            raise PersistenceError("trade insert produced no persisted record")
        if not _same_record_fields(stored, candidate, self._IMMUTABLE_FIELDS):
            raise ContradictoryFactError("stored trade contradicts immutable entry economics")
        if _same_record_fields(stored, candidate, self._STATE_FIELDS):
            return trade_from_record(stored, trade.run)
        if stored.state != TradeState.OPEN.value or candidate.state != TradeState.CLOSED.value:
            raise ContradictoryFactError("stored trade cannot be replaced or regressed")
        result = cast(
            sa.CursorResult[object],
            self._session.execute(
                sa.update(TradeRecord)
                .where(
                    TradeRecord.trade_id == candidate.trade_id,
                    TradeRecord.state == TradeState.OPEN.value,
                )
                .values(
                    state=candidate.state,
                    closed_at=candidate.closed_at,
                    exit_id=candidate.exit_id,
                )
            ),
        )
        if result.rowcount == 1:
            self._session.flush()
        self._session.expire_all()
        stored = self._find(candidate)
        if stored is not None and _same_record_fields(stored, candidate, self._STATE_FIELDS):
            return trade_from_record(stored, trade.run)
        raise ContradictoryFactError("stored trade conflicts with requested closed state")

    def get(self, trade_id: TradeId) -> Trade | None:
        record = self._session.get(TradeRecord, str(trade_id))
        if record is None:
            return None
        run = self._load_run(record.run_id)
        if run is None:
            raise PersistenceDependencyError("trade references missing run provenance")
        return trade_from_record(record, run)


class PostgresPositionRepository(_PostgresRepository):
    """Persist authoritative Position state while freezing MVP exposure facts."""

    _IMMUTABLE_FIELDS = (
        "position_id",
        "trade_id",
        "run_id",
        "instrument_id",
        "quantity",
        "average_entry_price",
        "opened_at",
    )
    _STATE_FIELDS = ("state", "closed_at")

    def _find(self, candidate: PositionRecord) -> PositionRecord | None:
        records = self._session.scalars(
            sa.select(PositionRecord).where(
                sa.or_(
                    PositionRecord.position_id == candidate.position_id,
                    PositionRecord.trade_id == candidate.trade_id,
                )
            )
        ).all()
        return _single_collision(records, fact_name="position")

    def _require_dependencies(self, position: Position, candidate: PositionRecord) -> None:
        self._require_run(position.run)
        trade = self._require_record(TradeRecord, candidate.trade_id, name="trade")
        if trade.run_id != candidate.run_id or trade.instrument_id != candidate.instrument_id:
            raise ContradictoryFactError("position dependency contradicts the requested exposure")

    def upsert(self, position: Position) -> Position:
        candidate = position_record_from_domain(position)
        self._require_dependencies(position, candidate)
        stored = self._find(candidate)
        if stored is None:
            _insert_ignoring_unique_conflicts(self._session, PositionRecord.__table__, candidate)
            self._session.flush()
            stored = self._find(candidate)
        if stored is None:
            raise PersistenceError("position insert produced no persisted record")
        if not _same_record_fields(stored, candidate, self._IMMUTABLE_FIELDS):
            raise ContradictoryFactError("stored position contradicts immutable exposure fields")
        if _same_record_fields(stored, candidate, self._STATE_FIELDS):
            return position_from_record(stored, position.run)
        if (
            stored.state != PositionState.OPEN.value
            or candidate.state != PositionState.CLOSED.value
        ):
            raise ContradictoryFactError("stored position cannot be replaced or regressed")
        result = cast(
            sa.CursorResult[object],
            self._session.execute(
                sa.update(PositionRecord)
                .where(
                    PositionRecord.position_id == candidate.position_id,
                    PositionRecord.state == PositionState.OPEN.value,
                )
                .values(state=candidate.state, closed_at=candidate.closed_at)
            ),
        )
        if result.rowcount == 1:
            self._session.flush()
        self._session.expire_all()
        stored = self._find(candidate)
        if stored is not None and _same_record_fields(stored, candidate, self._STATE_FIELDS):
            return position_from_record(stored, position.run)
        raise ContradictoryFactError("stored position conflicts with requested closed state")

    def get(self, position_id: PositionId) -> Position | None:
        record = self._session.get(PositionRecord, str(position_id))
        if record is None:
            return None
        run = self._load_run(record.run_id)
        if run is None:
            raise PersistenceDependencyError("position references missing run provenance")
        return position_from_record(record, run)


class PostgresIndicatorCheckpointRepository(_PostgresRepository):
    """Authoritative lossless current checkpoint per run/instrument."""

    def upsert(self, run: RunIdentity, state: IndicatorEngineState) -> IndicatorEngineState:
        self._require_run(run)
        candidate = indicator_checkpoint_record_from_state(run, state)
        existing = self._session.get(
            IndicatorCheckpointRecord, (str(run.run_id), str(state.instrument_id))
        )
        if existing is None:
            self._session.add(candidate)
            self._session.flush()
            return state
        persisted = indicator_checkpoint_state_from_record(existing)
        if persisted == state:
            return persisted
        if persisted.calculation_version != state.calculation_version:
            raise ContradictoryFactError("indicator checkpoint calculation version changed")
        if persisted.continuity.value == "broken" and state.continuity.value == "healthy":
            raise ContradictoryFactError("indicator checkpoint cannot restore broken continuity")
        old_samples = persisted.ema9.samples
        new_samples = state.ema9.samples
        same_interval = persisted.last_interval == state.last_interval
        if (
            same_interval
            and persisted.continuity.value == "healthy"
            and state.continuity.value == "broken"
        ):
            existing.continuity_state = state.continuity.value
            self._session.flush()
            return state
        if new_samples <= old_samples:
            raise ContradictoryFactError(
                "indicator checkpoint is stale or contradicts current state"
            )
        if (
            persisted.last_interval is not None
            and state.last_interval is not None
            and state.last_interval.end <= persisted.last_interval.end
        ):
            raise ContradictoryFactError("indicator checkpoint interval regresses")
        for column in IndicatorCheckpointRecord.__table__.columns:
            setattr(existing, column.name, getattr(candidate, column.name))
        self._session.flush()
        return state

    def get(self, run_id: RunId, instrument_id: InstrumentId) -> IndicatorEngineState | None:
        record = self._session.get(IndicatorCheckpointRecord, (str(run_id), str(instrument_id)))
        return None if record is None else indicator_checkpoint_state_from_record(record)
