"""Store realised R without an arbitrary fractional scale limit.

Revision ID: 20260901_0002
Revises: 20260831_0001
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260901_0002"
down_revision: str | None = "20260831_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Remove the scale limit that could round valid finite domain Decimals."""
    op.alter_column(
        "exits",
        "realised_r",
        existing_type=sa.Numeric(38, 18),
        type_=sa.Numeric(),
        existing_nullable=False,
        postgresql_using="realised_r::numeric",
    )


def downgrade() -> None:
    """Restore the SF-044 bounded realised-R representation."""
    op.alter_column(
        "exits",
        "realised_r",
        existing_type=sa.Numeric(),
        type_=sa.Numeric(38, 18),
        postgresql_using="realised_r::numeric(38, 18)",
        existing_nullable=False,
    )
