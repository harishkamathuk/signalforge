"""Create canonical M6 runtime persistence schema.

Revision ID: 20260831_0001
Revises:
Create Date: 2026-08-31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260831_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ID = 64
_INSTRUMENT = 128
_STATE = 64
_PRICE_PRECISION = 38
_PRICE_SCALE = 18


def _price() -> sa.Numeric:
    return sa.Numeric(_PRICE_PRECISION, _PRICE_SCALE)


def upgrade() -> None:
    """Create the ADR-003 hybrid immutable-facts/current-state schema."""

    op.create_table(
        "strategy_configs",
        sa.Column("config_id", sa.String(_ID), nullable=False),
        sa.Column("strategy_id", sa.String(128), nullable=False),
        sa.Column("strategy_version", sa.String(64), nullable=False),
        sa.Column("config_hash", sa.String(128), nullable=False),
        sa.PrimaryKeyConstraint("config_id", name="pk_strategy_configs"),
        sa.UniqueConstraint(
            "strategy_id",
            "strategy_version",
            "config_hash",
            name="uq_strategy_configs_identity",
        ),
    )

    op.create_table(
        "runs",
        sa.Column("run_id", sa.String(_ID), nullable=False),
        sa.Column("config_id", sa.String(_ID), nullable=False),
        sa.Column("engine_calculation_version", sa.String(128), nullable=False),
        sa.ForeignKeyConstraint(
            ["config_id"],
            ["strategy_configs.config_id"],
            name="fk_runs_config_id_strategy_configs",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("run_id", name="pk_runs"),
    )

    op.create_table(
        "strategy_evaluations",
        sa.Column("run_id", sa.String(_ID), nullable=False),
        sa.Column("instrument_id", sa.String(_INSTRUMENT), nullable=False),
        sa.Column("interval_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("interval_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("trend_passed", sa.Boolean(), nullable=False),
        sa.Column("momentum_passed", sa.Boolean(), nullable=False),
        sa.Column("rsi_passed", sa.Boolean(), nullable=False),
        sa.Column("adx_passed", sa.Boolean(), nullable=False),
        sa.Column("macd_signal_positive", sa.Boolean(), nullable=True),
        sa.Column("setup_passed", sa.Boolean(), nullable=False),
        sa.Column("qualified", sa.Boolean(), nullable=False),
        sa.Column("actionable", sa.Boolean(), nullable=False),
        sa.Column("reasons", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.CheckConstraint("interval_end > interval_start", name="ck_evaluation_interval_order"),
        sa.CheckConstraint("NOT actionable OR qualified", name="ck_evaluation_actionable_qualified"),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["runs.run_id"],
            name="fk_strategy_evaluations_run_id_runs",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "run_id",
            "instrument_id",
            "interval_start",
            "interval_end",
            name="pk_strategy_evaluations",
        ),
    )

    op.create_table(
        "signals",
        sa.Column("signal_id", sa.String(_ID), nullable=False),
        sa.Column("run_id", sa.String(_ID), nullable=False),
        sa.Column("instrument_id", sa.String(_INSTRUMENT), nullable=False),
        sa.Column("interval_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("interval_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("signal_close", _price(), nullable=False),
        sa.Column("signal_low", _price(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("interval_end > interval_start", name="ck_signal_interval_order"),
        sa.CheckConstraint("signal_close > 0", name="ck_signal_close_positive"),
        sa.CheckConstraint("signal_low > 0", name="ck_signal_low_positive"),
        sa.CheckConstraint("signal_low <= signal_close", name="ck_signal_low_close"),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["runs.run_id"],
            name="fk_signals_run_id_runs",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("signal_id", name="pk_signals"),
        sa.UniqueConstraint(
            "run_id",
            "instrument_id",
            "interval_start",
            "interval_end",
            name="uq_signals_logical_identity",
        ),
    )

    op.create_table(
        "armed_setups",
        sa.Column("signal_id", sa.String(_ID), nullable=False),
        sa.Column("run_id", sa.String(_ID), nullable=False),
        sa.Column("raw_trigger", _price(), nullable=False),
        sa.Column("tradable_trigger", _price(), nullable=False),
        sa.Column("signal_low", _price(), nullable=False),
        sa.Column("armed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("state", sa.String(_STATE), nullable=False),
        sa.Column("terminal_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expiry_reason", sa.String(_STATE), nullable=True),
        sa.CheckConstraint("raw_trigger > 0", name="ck_armed_raw_trigger_positive"),
        sa.CheckConstraint("tradable_trigger > 0", name="ck_armed_tradable_trigger_positive"),
        sa.CheckConstraint("tradable_trigger >= raw_trigger", name="ck_armed_trigger_order"),
        sa.CheckConstraint("signal_low > 0", name="ck_armed_signal_low_positive"),
        sa.CheckConstraint("valid_until > armed_at", name="ck_armed_validity_order"),
        sa.CheckConstraint(
            "state IN ('armed', 'triggered', 'expired')",
            name="ck_armed_state",
        ),
        sa.CheckConstraint(
            "(state = 'armed' AND terminal_at IS NULL AND expiry_reason IS NULL) OR "
            "(state = 'triggered' AND terminal_at IS NOT NULL AND expiry_reason IS NULL) OR "
            "(state = 'expired' AND terminal_at IS NOT NULL AND expiry_reason IS NOT NULL)",
            name="ck_armed_terminal_metadata",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["runs.run_id"],
            name="fk_armed_setups_run_id_runs",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["signal_id"],
            ["signals.signal_id"],
            name="fk_armed_setups_signal_id_signals",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("signal_id", name="pk_armed_setups"),
    )

    op.create_table(
        "trigger_events",
        sa.Column("trigger_event_id", sa.String(_ID), nullable=False),
        sa.Column("signal_id", sa.String(_ID), nullable=False),
        sa.Column("run_id", sa.String(_ID), nullable=False),
        sa.Column("instrument_id", sa.String(_INSTRUMENT), nullable=False),
        sa.Column("reference_price", _price(), nullable=False),
        sa.Column("observed_price", _price(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("reference_price > 0", name="ck_trigger_reference_positive"),
        sa.CheckConstraint("observed_price > 0", name="ck_trigger_observed_positive"),
        sa.CheckConstraint(
            "observed_price >= reference_price",
            name="ck_trigger_observed_reference",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["runs.run_id"],
            name="fk_trigger_events_run_id_runs",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["signal_id"],
            ["signals.signal_id"],
            name="fk_trigger_events_signal_id_signals",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("trigger_event_id", name="pk_trigger_events"),
    )

    op.create_table(
        "entry_intents",
        sa.Column("entry_intent_id", sa.String(_ID), nullable=False),
        sa.Column("trigger_event_id", sa.String(_ID), nullable=False),
        sa.Column("signal_id", sa.String(_ID), nullable=False),
        sa.Column("run_id", sa.String(_ID), nullable=False),
        sa.Column("instrument_id", sa.String(_INSTRUMENT), nullable=False),
        sa.Column("reference_price", _price(), nullable=False),
        sa.Column("quantity", sa.BigInteger(), nullable=False),
        sa.Column("execution_mode", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("reference_price > 0", name="ck_entry_intent_reference_positive"),
        sa.CheckConstraint("quantity > 0", name="ck_entry_intent_quantity_positive"),
        sa.CheckConstraint(
            "execution_mode IN ('paper', 'live')",
            name="ck_entry_intent_execution_mode",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["runs.run_id"],
            name="fk_entry_intents_run_id_runs",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["signal_id"],
            ["signals.signal_id"],
            name="fk_entry_intents_signal_id_signals",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["trigger_event_id"],
            ["trigger_events.trigger_event_id"],
            name="fk_entry_intents_trigger_event_id_trigger_events",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("entry_intent_id", name="pk_entry_intents"),
        sa.UniqueConstraint("trigger_event_id", name="uq_entry_intents_trigger_event"),
    )

    op.create_table(
        "fills",
        sa.Column("fill_id", sa.String(_ID), nullable=False),
        sa.Column("entry_intent_id", sa.String(_ID), nullable=False),
        sa.Column("trigger_event_id", sa.String(_ID), nullable=False),
        sa.Column("signal_id", sa.String(_ID), nullable=False),
        sa.Column("run_id", sa.String(_ID), nullable=False),
        sa.Column("instrument_id", sa.String(_INSTRUMENT), nullable=False),
        sa.Column("reference_price", _price(), nullable=False),
        sa.Column("fill_price", _price(), nullable=False),
        sa.Column("quantity", sa.BigInteger(), nullable=False),
        sa.Column("execution_mode", sa.String(16), nullable=False),
        sa.Column("filled_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("reference_price > 0", name="ck_fill_reference_positive"),
        sa.CheckConstraint("fill_price > 0", name="ck_fill_price_positive"),
        sa.CheckConstraint("quantity > 0", name="ck_fill_quantity_positive"),
        sa.CheckConstraint("execution_mode IN ('paper', 'live')", name="ck_fill_execution_mode"),
        sa.ForeignKeyConstraint(
            ["entry_intent_id"],
            ["entry_intents.entry_intent_id"],
            name="fk_fills_entry_intent_id_entry_intents",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["runs.run_id"],
            name="fk_fills_run_id_runs",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["signal_id"],
            ["signals.signal_id"],
            name="fk_fills_signal_id_signals",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["trigger_event_id"],
            ["trigger_events.trigger_event_id"],
            name="fk_fills_trigger_event_id_trigger_events",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("fill_id", name="pk_fills"),
        sa.UniqueConstraint("entry_intent_id", name="uq_fills_entry_intent"),
    )

    op.create_table(
        "trades",
        sa.Column("trade_id", sa.String(_ID), nullable=False),
        sa.Column("entry_fill_id", sa.String(_ID), nullable=False),
        sa.Column("signal_id", sa.String(_ID), nullable=False),
        sa.Column("run_id", sa.String(_ID), nullable=False),
        sa.Column("instrument_id", sa.String(_INSTRUMENT), nullable=False),
        sa.Column("entry_price", _price(), nullable=False),
        sa.Column("stop_price", _price(), nullable=False),
        sa.Column("raw_target_price", _price(), nullable=False),
        sa.Column("tradable_target_price", _price(), nullable=False),
        sa.Column("risk_per_share", _price(), nullable=False),
        sa.Column("quantity", sa.BigInteger(), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("state", sa.String(_STATE), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("exit_id", sa.String(_ID), nullable=True),
        sa.CheckConstraint("entry_price > 0", name="ck_trade_entry_positive"),
        sa.CheckConstraint("stop_price > 0", name="ck_trade_stop_positive"),
        sa.CheckConstraint("risk_per_share > 0", name="ck_trade_risk_positive"),
        sa.CheckConstraint("raw_target_price > entry_price", name="ck_trade_raw_target"),
        sa.CheckConstraint(
            "tradable_target_price >= raw_target_price",
            name="ck_trade_tradable_target",
        ),
        sa.CheckConstraint("quantity > 0", name="ck_trade_quantity_positive"),
        sa.CheckConstraint("state IN ('open', 'closed')", name="ck_trade_state"),
        sa.CheckConstraint(
            "(state = 'open' AND closed_at IS NULL AND exit_id IS NULL) OR "
            "(state = 'closed' AND closed_at IS NOT NULL AND exit_id IS NOT NULL)",
            name="ck_trade_close_metadata",
        ),
        sa.ForeignKeyConstraint(
            ["entry_fill_id"],
            ["fills.fill_id"],
            name="fk_trades_entry_fill_id_fills",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["runs.run_id"],
            name="fk_trades_run_id_runs",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["signal_id"],
            ["signals.signal_id"],
            name="fk_trades_signal_id_signals",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("trade_id", name="pk_trades"),
        sa.UniqueConstraint("entry_fill_id", name="uq_trades_entry_fill"),
    )

    op.create_table(
        "positions",
        sa.Column("position_id", sa.String(_ID), nullable=False),
        sa.Column("trade_id", sa.String(_ID), nullable=False),
        sa.Column("run_id", sa.String(_ID), nullable=False),
        sa.Column("instrument_id", sa.String(_INSTRUMENT), nullable=False),
        sa.Column("quantity", sa.BigInteger(), nullable=False),
        sa.Column("average_entry_price", _price(), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("state", sa.String(_STATE), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("average_entry_price > 0", name="ck_position_entry_positive"),
        sa.CheckConstraint("quantity > 0", name="ck_position_quantity_positive"),
        sa.CheckConstraint("state IN ('open', 'closed')", name="ck_position_state"),
        sa.CheckConstraint(
            "(state = 'open' AND closed_at IS NULL) OR "
            "(state = 'closed' AND closed_at IS NOT NULL)",
            name="ck_position_close_metadata",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["runs.run_id"],
            name="fk_positions_run_id_runs",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["trade_id"],
            ["trades.trade_id"],
            name="fk_positions_trade_id_trades",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("position_id", name="pk_positions"),
        sa.UniqueConstraint("trade_id", name="uq_positions_trade"),
    )

    op.create_table(
        "exits",
        sa.Column("exit_id", sa.String(_ID), nullable=False),
        sa.Column("exit_fill_id", sa.String(_ID), nullable=False),
        sa.Column("trade_id", sa.String(_ID), nullable=False),
        sa.Column("position_id", sa.String(_ID), nullable=False),
        sa.Column("run_id", sa.String(_ID), nullable=False),
        sa.Column("instrument_id", sa.String(_INSTRUMENT), nullable=False),
        sa.Column("reason", sa.String(_STATE), nullable=False),
        sa.Column("reference_price", _price(), nullable=False),
        sa.Column("fill_price", _price(), nullable=False),
        sa.Column("quantity", sa.BigInteger(), nullable=False),
        sa.Column("execution_mode", sa.String(16), nullable=False),
        sa.Column("exited_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("realised_pnl", _price(), nullable=False),
        sa.Column("realised_r", _price(), nullable=False),
        sa.CheckConstraint("reference_price > 0", name="ck_exit_reference_positive"),
        sa.CheckConstraint("fill_price > 0", name="ck_exit_fill_positive"),
        sa.CheckConstraint("quantity > 0", name="ck_exit_quantity_positive"),
        sa.CheckConstraint(
            "reason IN ('stop', 'target', 'forced_session_exit')",
            name="ck_exit_reason",
        ),
        sa.CheckConstraint("execution_mode IN ('paper', 'live')", name="ck_exit_execution_mode"),
        sa.ForeignKeyConstraint(
            ["position_id"],
            ["positions.position_id"],
            name="fk_exits_position_id_positions",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["runs.run_id"],
            name="fk_exits_run_id_runs",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["trade_id"],
            ["trades.trade_id"],
            name="fk_exits_trade_id_trades",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("exit_id", name="pk_exits"),
        sa.UniqueConstraint("exit_fill_id", name="uq_exits_exit_fill"),
        sa.UniqueConstraint("position_id", name="uq_exits_position"),
        sa.UniqueConstraint("trade_id", name="uq_exits_trade"),
    )

    op.create_foreign_key(
        "fk_trades_exit_id_exits",
        "trades",
        "exits",
        ["exit_id"],
        ["exit_id"],
        ondelete="RESTRICT",
    )

    op.create_table(
        "state_transitions",
        sa.Column("transition_id", sa.String(_ID), nullable=False),
        sa.Column("run_id", sa.String(_ID), nullable=False),
        sa.Column("entity_type", sa.String(_STATE), nullable=False),
        sa.Column("entity_id", sa.String(_ID), nullable=False),
        sa.Column("from_state", sa.String(_STATE), nullable=False),
        sa.Column("to_state", sa.String(_STATE), nullable=False),
        sa.Column("cause_type", sa.String(_STATE), nullable=False),
        sa.Column("cause_id", sa.String(_ID), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("from_state <> to_state", name="ck_transition_changes_state"),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["runs.run_id"],
            name="fk_state_transitions_run_id_runs",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("transition_id", name="pk_state_transitions"),
    )

    op.create_table(
        "indicator_checkpoints",
        sa.Column("run_id", sa.String(_ID), nullable=False),
        sa.Column("instrument_id", sa.String(_INSTRUMENT), nullable=False),
        sa.Column("interval_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("interval_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("calculation_version", sa.String(128), nullable=False),
        sa.Column("continuity_state", sa.String(_STATE), nullable=False),
        sa.Column("completed_candle_count", sa.BigInteger(), nullable=False),
        sa.Column("ema9", _price(), nullable=True),
        sa.Column("ema20", _price(), nullable=True),
        sa.Column("ema50", _price(), nullable=True),
        sa.Column("rsi14", _price(), nullable=True),
        sa.Column("adx14", _price(), nullable=True),
        sa.Column("macd_line", _price(), nullable=True),
        sa.Column("macd_signal", _price(), nullable=True),
        sa.Column("macd_histogram", _price(), nullable=True),
        sa.Column("state_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.CheckConstraint("interval_end > interval_start", name="ck_indicator_interval_order"),
        sa.CheckConstraint("completed_candle_count >= 0", name="ck_indicator_count_nonnegative"),
        sa.CheckConstraint(
            "continuity_state IN ('healthy', 'broken')",
            name="ck_indicator_continuity_state",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["runs.run_id"],
            name="fk_indicator_checkpoints_run_id_runs",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("run_id", "instrument_id", name="pk_indicator_checkpoints"),
    )

    op.create_table(
        "lifecycle_state",
        sa.Column("run_id", sa.String(_ID), nullable=False),
        sa.Column("instrument_id", sa.String(_INSTRUMENT), nullable=False),
        sa.Column("state", sa.String(_STATE), nullable=False),
        sa.Column("current_signal_id", sa.String(_ID), nullable=True),
        sa.Column("current_trade_id", sa.String(_ID), nullable=True),
        sa.Column("current_position_id", sa.String(_ID), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "state IN ('idle', 'armed', 'triggered', 'expired', 'open', 'closed')",
            name="ck_lifecycle_state",
        ),
        sa.ForeignKeyConstraint(
            ["current_position_id"],
            ["positions.position_id"],
            name="fk_lifecycle_current_position",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["current_signal_id"],
            ["signals.signal_id"],
            name="fk_lifecycle_current_signal",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["current_trade_id"],
            ["trades.trade_id"],
            name="fk_lifecycle_current_trade",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["runs.run_id"],
            name="fk_lifecycle_state_run_id_runs",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("run_id", "instrument_id", name="pk_lifecycle_state"),
    )


def downgrade() -> None:
    """Drop the initial runtime persistence schema in dependency order."""

    op.drop_table("lifecycle_state")
    op.drop_table("indicator_checkpoints")
    op.drop_table("state_transitions")
    op.drop_constraint("fk_trades_exit_id_exits", "trades", type_="foreignkey")
    op.drop_table("exits")
    op.drop_table("positions")
    op.drop_table("trades")
    op.drop_table("fills")
    op.drop_table("entry_intents")
    op.drop_table("trigger_events")
    op.drop_table("armed_setups")
    op.drop_table("signals")
    op.drop_table("strategy_evaluations")
    op.drop_table("runs")
    op.drop_table("strategy_configs")
