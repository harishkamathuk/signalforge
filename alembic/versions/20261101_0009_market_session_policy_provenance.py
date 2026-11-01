"""Bind market/session policy identity to durable run provenance.

Revision ID: 20261101_0009
Revises: 20261006_0008
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20261101_0009"
down_revision: str | None = "20261006_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "runs",
        sa.Column(
            "market_session_policy_id",
            sa.String(length=128),
            nullable=False,
            server_default="nse_intraday",
        ),
    )
    op.add_column(
        "runs",
        sa.Column(
            "market_session_policy_version",
            sa.String(length=64),
            nullable=False,
            server_default="1.0.0",
        ),
    )
    op.alter_column("runs", "market_session_policy_id", server_default=None)
    op.alter_column("runs", "market_session_policy_version", server_default=None)


def downgrade() -> None:
    op.drop_column("runs", "market_session_policy_version")
    op.drop_column("runs", "market_session_policy_id")
