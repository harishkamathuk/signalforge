"""SQLAlchemy persistence models for canonical SignalForge runtime state.

These are persistence records, not domain models. Runtime/domain code must not depend on
SQLAlchemy entities directly; mapping/repository behavior is introduced by later M6 issues.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Numeric,
    PrimaryKeyConstraint,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

ID_LENGTH = 64
INSTRUMENT_LENGTH = 128
STATE_LENGTH = 64
PRICE_PRECISION = 38
PRICE_SCALE = 18


class Base(DeclarativeBase):
    """Declarative metadata root used by Alembic autogeneration."""


class StrategyConfigRecord(Base):
    """Immutable strategy/config provenance shared by one or more runs."""

    __tablename__ = "strategy_configs"
    __table_args__ = (
        UniqueConstraint(
            "strategy_id",
            "strategy_version",
            "config_hash",
            name="uq_strategy_configs_identity",
        ),
    )

    config_id: Mapped[str] = mapped_column(String(ID_LENGTH), primary_key=True)
    strategy_id: Mapped[str] = mapped_column(String(128), nullable=False)
    strategy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    config_hash: Mapped[str] = mapped_column(String(128), nullable=False)


class RunRecord(Base):
    """Immutable execution/replay run provenance."""

    __tablename__ = "runs"

    run_id: Mapped[str] = mapped_column(String(ID_LENGTH), primary_key=True)
    config_id: Mapped[str] = mapped_column(
        ForeignKey("strategy_configs.config_id", ondelete="RESTRICT"), nullable=False
    )
    engine_calculation_version: Mapped[str] = mapped_column(String(128), nullable=False)


class StrategyEvaluationRecord(Base):
    """Immutable strategy decision for one completed canonical candle."""

    __tablename__ = "strategy_evaluations"
    __table_args__ = (
        PrimaryKeyConstraint(
            "run_id",
            "instrument_id",
            "interval_start",
            "interval_end",
            name="pk_strategy_evaluations",
        ),
        CheckConstraint("interval_end > interval_start", name="ck_evaluation_interval_order"),
        CheckConstraint("NOT actionable OR qualified", name="ck_evaluation_actionable_qualified"),
    )

    run_id: Mapped[str] = mapped_column(
        ForeignKey("runs.run_id", ondelete="CASCADE"), nullable=False
    )
    instrument_id: Mapped[str] = mapped_column(String(INSTRUMENT_LENGTH), nullable=False)
    interval_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    interval_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    trend_passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    momentum_passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    rsi_passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    adx_passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    macd_signal_positive: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    setup_passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    qualified: Mapped[bool] = mapped_column(Boolean, nullable=False)
    actionable: Mapped[bool] = mapped_column(Boolean, nullable=False)
    reasons: Mapped[list[str]] = mapped_column(JSONB, nullable=False)


class SignalRecord(Base):
    """Immutable qualifying signal fact."""

    __tablename__ = "signals"
    __table_args__ = (
        UniqueConstraint(
            "run_id",
            "instrument_id",
            "interval_start",
            "interval_end",
            name="uq_signals_logical_identity",
        ),
        CheckConstraint("interval_end > interval_start", name="ck_signal_interval_order"),
        CheckConstraint("signal_close > 0", name="ck_signal_close_positive"),
        CheckConstraint("signal_low > 0", name="ck_signal_low_positive"),
        CheckConstraint("signal_low <= signal_close", name="ck_signal_low_close"),
    )

    signal_id: Mapped[str] = mapped_column(String(ID_LENGTH), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("runs.run_id", ondelete="CASCADE"), nullable=False
    )
    instrument_id: Mapped[str] = mapped_column(String(INSTRUMENT_LENGTH), nullable=False)
    interval_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    interval_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    signal_close: Mapped[Decimal] = mapped_column(
        Numeric(PRICE_PRECISION, PRICE_SCALE), nullable=False
    )
    signal_low: Mapped[Decimal] = mapped_column(
        Numeric(PRICE_PRECISION, PRICE_SCALE), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ArmedSetupRecord(Base):
    """Authoritative current state for the setup derived from a signal."""

    __tablename__ = "armed_setups"
    __table_args__ = (
        CheckConstraint("raw_trigger > 0", name="ck_armed_raw_trigger_positive"),
        CheckConstraint("tradable_trigger > 0", name="ck_armed_tradable_trigger_positive"),
        CheckConstraint("tradable_trigger >= raw_trigger", name="ck_armed_trigger_order"),
        CheckConstraint("signal_low > 0", name="ck_armed_signal_low_positive"),
        CheckConstraint("valid_until > armed_at", name="ck_armed_validity_order"),
        CheckConstraint(
            "state IN ('armed', 'triggered', 'expired')",
            name="ck_armed_state",
        ),
        CheckConstraint(
            "(state = 'armed' AND terminal_at IS NULL AND expiry_reason IS NULL) OR "
            "(state = 'triggered' AND terminal_at IS NOT NULL AND expiry_reason IS NULL) OR "
            "(state = 'expired' AND terminal_at IS NOT NULL AND expiry_reason IS NOT NULL)",
            name="ck_armed_terminal_metadata",
        ),
    )

    signal_id: Mapped[str] = mapped_column(
        ForeignKey("signals.signal_id", ondelete="CASCADE"), primary_key=True
    )
    run_id: Mapped[str] = mapped_column(
        ForeignKey("runs.run_id", ondelete="CASCADE"), nullable=False
    )
    raw_trigger: Mapped[Decimal] = mapped_column(
        Numeric(PRICE_PRECISION, PRICE_SCALE), nullable=False
    )
    tradable_trigger: Mapped[Decimal] = mapped_column(
        Numeric(PRICE_PRECISION, PRICE_SCALE), nullable=False
    )
    signal_low: Mapped[Decimal] = mapped_column(
        Numeric(PRICE_PRECISION, PRICE_SCALE), nullable=False
    )
    armed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    state: Mapped[str] = mapped_column(String(STATE_LENGTH), nullable=False)
    terminal_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expiry_reason: Mapped[str | None] = mapped_column(String(STATE_LENGTH), nullable=True)


class TriggerEventRecord(Base):
    """Immutable evidence of an observed market price crossing an entry trigger."""

    __tablename__ = "trigger_events"
    __table_args__ = (
        CheckConstraint("reference_price > 0", name="ck_trigger_reference_positive"),
        CheckConstraint("observed_price > 0", name="ck_trigger_observed_positive"),
        CheckConstraint(
            "observed_price >= reference_price",
            name="ck_trigger_observed_reference",
        ),
    )

    trigger_event_id: Mapped[str] = mapped_column(String(ID_LENGTH), primary_key=True)
    signal_id: Mapped[str] = mapped_column(
        ForeignKey("signals.signal_id", ondelete="RESTRICT"), nullable=False
    )
    run_id: Mapped[str] = mapped_column(
        ForeignKey("runs.run_id", ondelete="CASCADE"), nullable=False
    )
    instrument_id: Mapped[str] = mapped_column(String(INSTRUMENT_LENGTH), nullable=False)
    reference_price: Mapped[Decimal] = mapped_column(
        Numeric(PRICE_PRECISION, PRICE_SCALE), nullable=False
    )
    observed_price: Mapped[Decimal] = mapped_column(
        Numeric(PRICE_PRECISION, PRICE_SCALE), nullable=False
    )
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class EntryIntentRecord(Base):
    """Immutable broker-independent request to execute a triggered entry."""

    __tablename__ = "entry_intents"
    __table_args__ = (
        UniqueConstraint("trigger_event_id", name="uq_entry_intents_trigger_event"),
        CheckConstraint("reference_price > 0", name="ck_entry_intent_reference_positive"),
        CheckConstraint("quantity > 0", name="ck_entry_intent_quantity_positive"),
        CheckConstraint(
            "execution_mode IN ('paper', 'live')",
            name="ck_entry_intent_execution_mode",
        ),
    )

    entry_intent_id: Mapped[str] = mapped_column(String(ID_LENGTH), primary_key=True)
    trigger_event_id: Mapped[str] = mapped_column(
        ForeignKey("trigger_events.trigger_event_id", ondelete="RESTRICT"), nullable=False
    )
    signal_id: Mapped[str] = mapped_column(
        ForeignKey("signals.signal_id", ondelete="RESTRICT"), nullable=False
    )
    run_id: Mapped[str] = mapped_column(
        ForeignKey("runs.run_id", ondelete="CASCADE"), nullable=False
    )
    instrument_id: Mapped[str] = mapped_column(String(INSTRUMENT_LENGTH), nullable=False)
    reference_price: Mapped[Decimal] = mapped_column(
        Numeric(PRICE_PRECISION, PRICE_SCALE), nullable=False
    )
    quantity: Mapped[int] = mapped_column(BigInteger, nullable=False)
    execution_mode: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class FillRecord(Base):
    """Immutable accepted entry execution fact."""

    __tablename__ = "fills"
    __table_args__ = (
        UniqueConstraint("entry_intent_id", name="uq_fills_entry_intent"),
        CheckConstraint("reference_price > 0", name="ck_fill_reference_positive"),
        CheckConstraint("fill_price > 0", name="ck_fill_price_positive"),
        CheckConstraint("quantity > 0", name="ck_fill_quantity_positive"),
        CheckConstraint("execution_mode IN ('paper', 'live')", name="ck_fill_execution_mode"),
    )

    fill_id: Mapped[str] = mapped_column(String(ID_LENGTH), primary_key=True)
    entry_intent_id: Mapped[str] = mapped_column(
        ForeignKey("entry_intents.entry_intent_id", ondelete="RESTRICT"), nullable=False
    )
    trigger_event_id: Mapped[str] = mapped_column(
        ForeignKey("trigger_events.trigger_event_id", ondelete="RESTRICT"), nullable=False
    )
    signal_id: Mapped[str] = mapped_column(
        ForeignKey("signals.signal_id", ondelete="RESTRICT"), nullable=False
    )
    run_id: Mapped[str] = mapped_column(
        ForeignKey("runs.run_id", ondelete="CASCADE"), nullable=False
    )
    instrument_id: Mapped[str] = mapped_column(String(INSTRUMENT_LENGTH), nullable=False)
    reference_price: Mapped[Decimal] = mapped_column(
        Numeric(PRICE_PRECISION, PRICE_SCALE), nullable=False
    )
    fill_price: Mapped[Decimal] = mapped_column(
        Numeric(PRICE_PRECISION, PRICE_SCALE), nullable=False
    )
    quantity: Mapped[int] = mapped_column(BigInteger, nullable=False)
    execution_mode: Mapped[str] = mapped_column(String(16), nullable=False)
    filled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PositionOpenOutcomeRecord(Base):
    """Immutable completed business outcome for one accepted entry fill."""

    __tablename__ = "position_open_outcomes"
    __table_args__ = (
        UniqueConstraint("fill_id", name="uq_position_open_outcomes_fill"),
        CheckConstraint(
            "outcome IN ('opened', 'rejected_non_positive_risk')",
            name="ck_position_open_outcomes_outcome",
        ),
    )
    outcome_id: Mapped[str] = mapped_column(String(ID_LENGTH), primary_key=True)
    fill_id: Mapped[str] = mapped_column(
        ForeignKey("fills.fill_id", ondelete="RESTRICT"), nullable=False
    )
    run_id: Mapped[str] = mapped_column(
        ForeignKey("runs.run_id", ondelete="CASCADE"), nullable=False
    )
    outcome: Mapped[str] = mapped_column(String(64), nullable=False)


class TradeRecord(Base):
    """Authoritative trade economics and current trade lifecycle state."""

    __tablename__ = "trades"
    __table_args__ = (
        UniqueConstraint("entry_fill_id", name="uq_trades_entry_fill"),
        CheckConstraint("entry_price > 0", name="ck_trade_entry_positive"),
        CheckConstraint("stop_price > 0", name="ck_trade_stop_positive"),
        CheckConstraint("risk_per_share > 0", name="ck_trade_risk_positive"),
        CheckConstraint("raw_target_price > entry_price", name="ck_trade_raw_target"),
        CheckConstraint(
            "tradable_target_price >= raw_target_price",
            name="ck_trade_tradable_target",
        ),
        CheckConstraint("quantity > 0", name="ck_trade_quantity_positive"),
        CheckConstraint("state IN ('open', 'closed')", name="ck_trade_state"),
        CheckConstraint(
            "(state = 'open' AND closed_at IS NULL AND exit_id IS NULL) OR "
            "(state = 'closed' AND closed_at IS NOT NULL AND exit_id IS NOT NULL)",
            name="ck_trade_close_metadata",
        ),
    )

    trade_id: Mapped[str] = mapped_column(String(ID_LENGTH), primary_key=True)
    entry_fill_id: Mapped[str] = mapped_column(
        ForeignKey("fills.fill_id", ondelete="RESTRICT"), nullable=False
    )
    signal_id: Mapped[str] = mapped_column(
        ForeignKey("signals.signal_id", ondelete="RESTRICT"), nullable=False
    )
    run_id: Mapped[str] = mapped_column(
        ForeignKey("runs.run_id", ondelete="CASCADE"), nullable=False
    )
    instrument_id: Mapped[str] = mapped_column(String(INSTRUMENT_LENGTH), nullable=False)
    entry_price: Mapped[Decimal] = mapped_column(
        Numeric(PRICE_PRECISION, PRICE_SCALE), nullable=False
    )
    stop_price: Mapped[Decimal] = mapped_column(
        Numeric(PRICE_PRECISION, PRICE_SCALE), nullable=False
    )
    raw_target_price: Mapped[Decimal] = mapped_column(
        Numeric(PRICE_PRECISION, PRICE_SCALE), nullable=False
    )
    tradable_target_price: Mapped[Decimal] = mapped_column(
        Numeric(PRICE_PRECISION, PRICE_SCALE), nullable=False
    )
    risk_per_share: Mapped[Decimal] = mapped_column(
        Numeric(PRICE_PRECISION, PRICE_SCALE), nullable=False
    )
    quantity: Mapped[int] = mapped_column(BigInteger, nullable=False)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    state: Mapped[str] = mapped_column(String(STATE_LENGTH), nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    exit_id: Mapped[str | None] = mapped_column(
        ForeignKey(
            "exits.exit_id",
            name="fk_trades_exit_id_exits",
            ondelete="RESTRICT",
            use_alter=True,
        ),
        nullable=True,
    )


class PositionRecord(Base):
    """Authoritative current exposure state distinct from Trade economics."""

    __tablename__ = "positions"
    __table_args__ = (
        UniqueConstraint("trade_id", name="uq_positions_trade"),
        CheckConstraint("average_entry_price > 0", name="ck_position_entry_positive"),
        CheckConstraint("quantity > 0", name="ck_position_quantity_positive"),
        CheckConstraint("state IN ('open', 'closed')", name="ck_position_state"),
        CheckConstraint(
            "(state = 'open' AND closed_at IS NULL) OR "
            "(state = 'closed' AND closed_at IS NOT NULL)",
            name="ck_position_close_metadata",
        ),
    )

    position_id: Mapped[str] = mapped_column(String(ID_LENGTH), primary_key=True)
    trade_id: Mapped[str] = mapped_column(
        ForeignKey("trades.trade_id", ondelete="CASCADE"), nullable=False
    )
    run_id: Mapped[str] = mapped_column(
        ForeignKey("runs.run_id", ondelete="CASCADE"), nullable=False
    )
    instrument_id: Mapped[str] = mapped_column(String(INSTRUMENT_LENGTH), nullable=False)
    quantity: Mapped[int] = mapped_column(BigInteger, nullable=False)
    average_entry_price: Mapped[Decimal] = mapped_column(
        Numeric(PRICE_PRECISION, PRICE_SCALE), nullable=False
    )
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    state: Mapped[str] = mapped_column(String(STATE_LENGTH), nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ExitRecord(Base):
    """Immutable closure fact for one full-quantity MVP trade/position."""

    __tablename__ = "exits"
    __table_args__ = (
        UniqueConstraint("exit_fill_id", name="uq_exits_exit_fill"),
        UniqueConstraint("trade_id", name="uq_exits_trade"),
        UniqueConstraint("position_id", name="uq_exits_position"),
        CheckConstraint("reference_price > 0", name="ck_exit_reference_positive"),
        CheckConstraint("fill_price > 0", name="ck_exit_fill_positive"),
        CheckConstraint("quantity > 0", name="ck_exit_quantity_positive"),
        CheckConstraint(
            "reason IN ('stop', 'target', 'forced_session_exit')",
            name="ck_exit_reason",
        ),
        CheckConstraint("execution_mode IN ('paper', 'live')", name="ck_exit_execution_mode"),
    )

    exit_id: Mapped[str] = mapped_column(String(ID_LENGTH), primary_key=True)
    # Exit fill identity is a deterministic execution fact generated by PositionManager;
    # it is not currently represented by the entry-only Fill domain object.
    exit_fill_id: Mapped[str] = mapped_column(String(ID_LENGTH), nullable=False)
    trade_id: Mapped[str] = mapped_column(
        ForeignKey("trades.trade_id", ondelete="RESTRICT"), nullable=False
    )
    position_id: Mapped[str] = mapped_column(
        ForeignKey("positions.position_id", ondelete="RESTRICT"), nullable=False
    )
    run_id: Mapped[str] = mapped_column(
        ForeignKey("runs.run_id", ondelete="CASCADE"), nullable=False
    )
    instrument_id: Mapped[str] = mapped_column(String(INSTRUMENT_LENGTH), nullable=False)
    reason: Mapped[str] = mapped_column(String(STATE_LENGTH), nullable=False)
    reference_price: Mapped[Decimal] = mapped_column(
        Numeric(PRICE_PRECISION, PRICE_SCALE), nullable=False
    )
    fill_price: Mapped[Decimal] = mapped_column(
        Numeric(PRICE_PRECISION, PRICE_SCALE), nullable=False
    )
    quantity: Mapped[int] = mapped_column(BigInteger, nullable=False)
    execution_mode: Mapped[str] = mapped_column(String(16), nullable=False)
    exited_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    realised_pnl: Mapped[Decimal] = mapped_column(
        Numeric(PRICE_PRECISION, PRICE_SCALE), nullable=False
    )
    realised_r: Mapped[Decimal] = mapped_column(Numeric(), nullable=False)


class StateTransitionRecord(Base):
    """Immutable audit fact for a domain lifecycle transition."""

    __tablename__ = "state_transitions"
    __table_args__ = (
        CheckConstraint("from_state <> to_state", name="ck_transition_changes_state"),
    )

    transition_id: Mapped[str] = mapped_column(String(ID_LENGTH), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("runs.run_id", ondelete="CASCADE"), nullable=False
    )
    entity_type: Mapped[str] = mapped_column(String(STATE_LENGTH), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(ID_LENGTH), nullable=False)
    from_state: Mapped[str] = mapped_column(String(STATE_LENGTH), nullable=False)
    to_state: Mapped[str] = mapped_column(String(STATE_LENGTH), nullable=False)
    cause_type: Mapped[str] = mapped_column(String(STATE_LENGTH), nullable=False)
    cause_id: Mapped[str] = mapped_column(String(ID_LENGTH), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class IndicatorCheckpointRecord(Base):
    """Authoritative current incremental-indicator checkpoint per run/instrument."""

    __tablename__ = "indicator_checkpoints"
    __table_args__ = (
        PrimaryKeyConstraint("run_id", "instrument_id", name="pk_indicator_checkpoints"),
        CheckConstraint("interval_end > interval_start", name="ck_indicator_interval_order"),
        CheckConstraint("completed_candle_count >= 0", name="ck_indicator_count_nonnegative"),
        CheckConstraint(
            "continuity_state IN ('healthy', 'broken')",
            name="ck_indicator_continuity_state",
        ),
    )

    run_id: Mapped[str] = mapped_column(
        ForeignKey("runs.run_id", ondelete="CASCADE"), nullable=False
    )
    instrument_id: Mapped[str] = mapped_column(String(INSTRUMENT_LENGTH), nullable=False)
    interval_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    interval_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    calculation_version: Mapped[str] = mapped_column(String(128), nullable=False)
    continuity_state: Mapped[str] = mapped_column(String(STATE_LENGTH), nullable=False)
    completed_candle_count: Mapped[int] = mapped_column(BigInteger, nullable=False)
    ema9: Mapped[Decimal | None] = mapped_column(
        Numeric(PRICE_PRECISION, PRICE_SCALE), nullable=True
    )
    ema20: Mapped[Decimal | None] = mapped_column(
        Numeric(PRICE_PRECISION, PRICE_SCALE), nullable=True
    )
    ema50: Mapped[Decimal | None] = mapped_column(
        Numeric(PRICE_PRECISION, PRICE_SCALE), nullable=True
    )
    rsi14: Mapped[Decimal | None] = mapped_column(
        Numeric(PRICE_PRECISION, PRICE_SCALE), nullable=True
    )
    adx14: Mapped[Decimal | None] = mapped_column(
        Numeric(PRICE_PRECISION, PRICE_SCALE), nullable=True
    )
    macd_line: Mapped[Decimal | None] = mapped_column(
        Numeric(PRICE_PRECISION, PRICE_SCALE), nullable=True
    )
    macd_signal: Mapped[Decimal | None] = mapped_column(
        Numeric(PRICE_PRECISION, PRICE_SCALE), nullable=True
    )
    macd_histogram: Mapped[Decimal | None] = mapped_column(
        Numeric(PRICE_PRECISION, PRICE_SCALE), nullable=True
    )
    state_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


class LifecycleStateRecord(Base):
    """Authoritative current coordinator identity/state per run/instrument."""

    __tablename__ = "lifecycle_state"
    __table_args__ = (
        PrimaryKeyConstraint("run_id", "instrument_id", name="pk_lifecycle_state"),
        CheckConstraint(
            "state IN ('idle', 'armed', 'triggered', 'expired', 'open', 'closed')",
            name="ck_lifecycle_state",
        ),
        ForeignKeyConstraint(
            ["current_signal_id"],
            ["signals.signal_id"],
            name="fk_lifecycle_current_signal",
            ondelete="SET NULL",
        ),
        ForeignKeyConstraint(
            ["current_trade_id"],
            ["trades.trade_id"],
            name="fk_lifecycle_current_trade",
            ondelete="SET NULL",
        ),
        ForeignKeyConstraint(
            ["current_position_id"],
            ["positions.position_id"],
            name="fk_lifecycle_current_position",
            ondelete="SET NULL",
        ),
    )

    run_id: Mapped[str] = mapped_column(
        ForeignKey("runs.run_id", ondelete="CASCADE"), nullable=False
    )
    instrument_id: Mapped[str] = mapped_column(String(INSTRUMENT_LENGTH), nullable=False)
    state: Mapped[str] = mapped_column(String(STATE_LENGTH), nullable=False)
    current_signal_id: Mapped[str | None] = mapped_column(String(ID_LENGTH), nullable=True)
    current_trade_id: Mapped[str | None] = mapped_column(String(ID_LENGTH), nullable=True)
    current_position_id: Mapped[str | None] = mapped_column(String(ID_LENGTH), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
