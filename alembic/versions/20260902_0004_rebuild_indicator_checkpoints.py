"""Rebuild indicator checkpoints as lossless numerical state.

Revision ID: 20260902_0004
Revises: 20260902_0003
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260902_0004"
down_revision: str | None = "20260902_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DECIMAL_COLUMNS = (
    "ema9_value",
    "ema9_seed_sum",
    "ema20_value",
    "ema20_seed_sum",
    "ema50_value",
    "ema50_seed_sum",
    "rsi_previous_close",
    "rsi_seed_gain_sum",
    "rsi_seed_loss_sum",
    "rsi_average_gain",
    "rsi_average_loss",
    "adx_previous_high",
    "adx_previous_low",
    "adx_previous_close",
    "adx_seed_tr_sum",
    "adx_seed_plus_dm_sum",
    "adx_seed_minus_dm_sum",
    "adx_smoothed_tr",
    "adx_smoothed_plus_dm",
    "adx_smoothed_minus_dm",
    "adx_dx_seed_sum",
    "adx",
    "macd_fast_value",
    "macd_fast_seed_sum",
    "macd_slow_value",
    "macd_slow_seed_sum",
    "macd_signal_value",
    "macd_signal_seed_sum",
)
_REQUIRED_DECIMALS = {name for name in _DECIMAL_COLUMNS if "seed" in name}

_REQUIRED_DECIMALS.update({"adx_seed_tr_sum", "adx_seed_plus_dm_sum", "adx_seed_minus_dm_sum"})


def upgrade() -> None:
    # Placeholder rows are absent; rounded/JSON state is deliberately not converted.
    op.drop_table("indicator_checkpoints")
    op.create_table(
        "indicator_checkpoints",
        sa.Column("run_id", sa.String(64), nullable=False),
        sa.Column("instrument_id", sa.String(128), nullable=False),
        sa.Column("calculation_version", sa.String(128), nullable=False),
        sa.Column("continuity_state", sa.String(32), nullable=False),
        sa.Column("last_interval_start", sa.DateTime(timezone=True)),
        sa.Column("last_interval_end", sa.DateTime(timezone=True)),
        sa.Column("completed_candle_count", sa.BigInteger(), nullable=False),
        sa.Column("adx_dx_seed_count", sa.BigInteger(), nullable=False),
        *(
            sa.Column(name, sa.Numeric(), nullable=name not in _REQUIRED_DECIMALS)
            for name in _DECIMAL_COLUMNS
        ),
        sa.CheckConstraint("completed_candle_count >= 0", name="ck_indicator_count_nonnegative"),
        sa.CheckConstraint(
            "continuity_state IN ('healthy', 'broken')", name="ck_indicator_continuity_state"
        ),
        sa.CheckConstraint("adx_dx_seed_count >= 0", name="ck_indicator_dx_seed_count_nonnegative"),
        sa.CheckConstraint(
            "(completed_candle_count = 0 AND last_interval_start IS NULL AND "
            "last_interval_end IS NULL) OR (completed_candle_count > 0 AND "
            "last_interval_start IS NOT NULL AND last_interval_end IS NOT NULL AND "
            "last_interval_end > last_interval_start)",
            name="ck_indicator_interval_presence",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["runs.run_id"],
            ondelete="CASCADE",
            name="fk_indicator_checkpoints_run_id_runs",
        ),
        sa.PrimaryKeyConstraint("run_id", "instrument_id", name="pk_indicator_checkpoints"),
    )


def downgrade() -> None:
    op.drop_table("indicator_checkpoints")
    op.create_table(
        "indicator_checkpoints",
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("instrument_id", sa.String(length=64), nullable=False),
        sa.Column("interval_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("interval_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("calculation_version", sa.String(length=128), nullable=False),
        sa.Column("continuity_state", sa.String(length=32), nullable=False),
        sa.Column("completed_candle_count", sa.BigInteger(), nullable=False),
        sa.Column("ema9", sa.Numeric(24, 12), nullable=True),
        sa.Column("ema20", sa.Numeric(24, 12), nullable=True),
        sa.Column("ema50", sa.Numeric(24, 12), nullable=True),
        sa.Column("rsi14", sa.Numeric(24, 12), nullable=True),
        sa.Column("adx14", sa.Numeric(24, 12), nullable=True),
        sa.Column("macd_line", sa.Numeric(24, 12), nullable=True),
        sa.Column("macd_signal", sa.Numeric(24, 12), nullable=True),
        sa.Column("macd_histogram", sa.Numeric(24, 12), nullable=True),
        sa.Column("state_payload", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("run_id", "instrument_id", name="pk_indicator_checkpoints"),
    )
