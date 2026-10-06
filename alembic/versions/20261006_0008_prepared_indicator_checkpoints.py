"""Add immutable prepared indicator checkpoints and live-run provenance.

Revision ID: 20261006_0008
Revises: 20261004_0007
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20261006_0008"
down_revision: str | None = "20261004_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add run-independent prepared indicator state without changing run checkpoints."""

    op.create_table(
        "prepared_indicator_checkpoints",
        sa.Column("checkpoint_id", sa.String(64), nullable=False),
        sa.Column("instrument_id", sa.String(128), nullable=False),
        sa.Column("exchange", sa.String(16), nullable=False),
        sa.Column("requirements_hash", sa.String(64), nullable=False),
        sa.Column("calculation_version", sa.String(128), nullable=False),
        sa.Column("target_trading_date", sa.Date(), nullable=False),
        sa.Column("continuity_state", sa.String(64), nullable=False),
        sa.Column("last_interval_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_interval_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_candle_count", sa.BigInteger(), nullable=False),
        sa.Column("requirements_manifest", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("state_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("historical_source", sa.String(128), nullable=False),
        sa.Column("requested_from", sa.Date(), nullable=False),
        sa.Column("requested_to", sa.Date(), nullable=False),
        sa.Column("first_accepted_interval_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("first_accepted_interval_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("final_accepted_interval_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("final_accepted_interval_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_candle_count", sa.BigInteger(), nullable=False),
        sa.Column("candle_sequence_digest", sa.String(64), nullable=False),
        sa.Column("prepared_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "completed_candle_count >= 0",
            name="ck_prepared_indicator_count_nonnegative",
        ),
        sa.CheckConstraint(
            "accepted_candle_count > 0",
            name="ck_prepared_indicator_accepted_positive",
        ),
        sa.CheckConstraint(
            "continuity_state = 'healthy'",
            name="ck_prepared_indicator_continuity_healthy",
        ),
        sa.CheckConstraint(
            "last_interval_end > last_interval_start",
            name="ck_prepared_indicator_interval_order",
        ),
        sa.CheckConstraint(
            "first_accepted_interval_end > first_accepted_interval_start",
            name="ck_prepared_indicator_first_interval_order",
        ),
        sa.CheckConstraint(
            "final_accepted_interval_end > final_accepted_interval_start",
            name="ck_prepared_indicator_final_interval_order",
        ),
        sa.PrimaryKeyConstraint(
            "checkpoint_id",
            name="pk_prepared_indicator_checkpoints",
        ),
        sa.UniqueConstraint(
            "instrument_id",
            "requirements_hash",
            "calculation_version",
            "last_interval_start",
            "last_interval_end",
            name="uq_prepared_indicator_checkpoint_logical_identity",
        ),
    )

    op.create_table(
        "run_prepared_indicator_checkpoints",
        sa.Column("run_id", sa.String(64), nullable=False),
        sa.Column("checkpoint_id", sa.String(64), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["runs.run_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["checkpoint_id"],
            ["prepared_indicator_checkpoints.checkpoint_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("run_id", name="pk_run_prepared_indicator_checkpoints"),
    )


def downgrade() -> None:
    """Remove SF-073 prepared-state persistence only."""

    op.drop_table("run_prepared_indicator_checkpoints")
    op.drop_table("prepared_indicator_checkpoints")
