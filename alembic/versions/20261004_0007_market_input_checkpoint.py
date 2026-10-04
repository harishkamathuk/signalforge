"""Add authoritative market-input/forming-candle checkpoint.

Revision ID: 20261004_0007
Revises: 20261003_0006
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20261004_0007"
down_revision: str | None = "20261003_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add one current restart-safe market-input checkpoint per run/instrument."""

    op.create_table(
        "market_input_checkpoints",
        sa.Column("run_id", sa.String(64), nullable=False),
        sa.Column("instrument_id", sa.String(128), nullable=False),
        sa.Column("source_id", sa.String(128), nullable=False),
        sa.Column("sequence", sa.BigInteger(), nullable=False),
        sa.Column("source_event_id", sa.String(256), nullable=False),
        sa.Column("payload_fingerprint", sa.String(128), nullable=False),
        sa.Column(
            "candle_state_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "sequence >= 0",
            name="ck_market_input_sequence_nonnegative",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["runs.run_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "run_id",
            "instrument_id",
            name="pk_market_input_checkpoints",
        ),
    )


def downgrade() -> None:
    """Drop the restart-safe market-input checkpoint."""

    op.drop_table("market_input_checkpoints")
