"""Add durable immutable outcomes for completed position-open attempts.

Revision ID: 20260902_0003
Revises: 20260901_0002
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260902_0003"
down_revision: str | None = "20260901_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "position_open_outcomes",
        sa.Column("outcome_id", sa.String(length=64), nullable=False),
        sa.Column("fill_id", sa.String(length=64), nullable=False),
        sa.Column("signal_id", sa.String(length=64), nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("outcome", sa.String(length=64), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "outcome IN ('opened', 'rejected_non_positive_risk')",
            name="ck_position_open_outcomes_outcome",
        ),
        sa.ForeignKeyConstraint(
            ["fill_id"],
            ["fills.fill_id"],
            name="fk_position_open_outcomes_fill_id_fills",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["signal_id"],
            ["signals.signal_id"],
            name="fk_position_open_outcomes_signal_id_signals",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["runs.run_id"],
            name="fk_position_open_outcomes_run_id_runs",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("outcome_id", name="pk_position_open_outcomes"),
        sa.UniqueConstraint("fill_id", name="uq_position_open_outcomes_fill"),
    )


def downgrade() -> None:
    op.drop_table("position_open_outcomes")
