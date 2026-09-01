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

from signalforge.domain.audit import StateTransition
from signalforge.domain.execution import EntryIntent, Fill, TriggerEvent
from signalforge.domain.exits import Exit
from signalforge.domain.ids import (
    EntryIntentId,
    ExitId,
    FillId,
    InstrumentId,
    RunId,
    SignalId,
    StateTransitionId,
    TriggerEventId,
)
from signalforge.domain.provenance import RunIdentity
from signalforge.domain.signals import Signal
from signalforge.domain.strategy import StrategyEvaluation
from signalforge.domain.time import CandleInterval
from signalforge.persistence.errors import (
    ContradictoryFactError,
    PersistenceDependencyError,
    PersistenceError,
)
from signalforge.persistence.mappers import (
    entry_intent_from_record,
    entry_intent_record_from_domain,
    exit_from_record,
    exit_record_from_domain,
    fill_from_record,
    fill_record_from_domain,
    run_identity_from_records,
    run_record_from_domain,
    signal_from_record,
    signal_record_from_domain,
    state_transition_from_record,
    state_transition_record_from_domain,
    strategy_config_record_from_domain,
    strategy_evaluation_from_record,
    strategy_evaluation_record_from_domain,
    trigger_event_from_record,
    trigger_event_record_from_domain,
)
from signalforge.persistence.models import (
    EntryIntentRecord,
    ExitRecord,
    FillRecord,
    PositionRecord,
    RunRecord,
    SignalRecord,
    StateTransitionRecord,
    StrategyConfigRecord,
    StrategyEvaluationRecord,
    TradeRecord,
    TriggerEventRecord,
)


def _insert_ignoring_unique_conflicts(
    session: Session,
    table: FromClause,
    record: object,
) -> None:
    values = {column.name: getattr(record, column.name) for column in table.columns}
    session.execute(insert(cast(TableClause, table)).values(values).on_conflict_do_nothing())


def _single_collision[RecordT](
    records: Sequence[RecordT], *, fact_name: str
) -> RecordT | None:
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
        raise ContradictoryFactError(
            f"stored {fact_name} contradicts requested immutable fact"
        )
    return persisted


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
