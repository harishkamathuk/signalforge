"""Align durable indicator continuity column width with ORM metadata.

Revision ID: 20261101_0010
Revises: 20261101_0009
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20261101_0010"
down_revision: str | None = "20261101_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Widen the state column without touching checkpoint rows or constraints."""
    op.alter_column(
        "indicator_checkpoints",
        "continuity_state",
        existing_type=sa.String(32),
        type_=sa.String(64),
        existing_nullable=False,
    )


def downgrade() -> None:
    """Only narrow when no persisted value would be truncated."""
    connection = op.get_bind()
    oversized = connection.execute(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM indicator_checkpoints "
            "WHERE char_length(continuity_state) > 32)"
        )
    ).scalar_one()
    if oversized:
        raise RuntimeError(
            "Cannot downgrade indicator continuity width: values exceed 32 characters"
        )
    op.alter_column(
        "indicator_checkpoints",
        "continuity_state",
        existing_type=sa.String(64),
        type_=sa.String(32),
        existing_nullable=False,
    )
