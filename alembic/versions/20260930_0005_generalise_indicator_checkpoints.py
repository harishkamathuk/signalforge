"""Generalise indicator checkpoints with self-describing requirement/state payloads.

Revision ID: 20260930_0005
Revises: 20260902_0004
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260930_0005"
down_revision: str | None = "20260902_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_LEGACY_REQUIRED_COLUMNS = (
    "ema9_seed_sum",
    "ema20_seed_sum",
    "ema50_seed_sum",
    "rsi_seed_gain_sum",
    "rsi_seed_loss_sum",
    "adx_seed_tr_sum",
    "adx_seed_plus_dm_sum",
    "adx_seed_minus_dm_sum",
    "adx_dx_seed_sum",
    "adx_dx_seed_count",
    "macd_fast_seed_sum",
    "macd_slow_seed_sum",
    "macd_signal_seed_sum",
)


def upgrade() -> None:
    """Add generic payloads while preserving legacy Strategy V1 checkpoint columns."""

    op.add_column(
        "indicator_checkpoints",
        sa.Column("requirements_manifest", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "indicator_checkpoints",
        sa.Column("state_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    # Non-V1 requirement sets do not have values for every historical fixed
    # column. Existing rows remain untouched and are read through the legacy
    # compatibility mapper until they next advance.
    for name in _LEGACY_REQUIRED_COLUMNS:
        existing_type: sa.types.TypeEngine[object]
        if name == "adx_dx_seed_count":
            existing_type = sa.BigInteger()
        else:
            existing_type = sa.Numeric()
        op.alter_column(
            "indicator_checkpoints",
            name,
            existing_type=existing_type,
            nullable=True,
        )


def downgrade() -> None:
    """Remove generic payload support when no generic-only checkpoint exists."""

    bind = op.get_bind()
    null_checks = " OR ".join(f"{name} IS NULL" for name in _LEGACY_REQUIRED_COLUMNS)
    generic_only = bind.execute(
        sa.text(f"SELECT count(*) FROM indicator_checkpoints WHERE {null_checks}")
    ).scalar_one()
    if generic_only:
        raise RuntimeError(
            "Cannot downgrade SF-063 while generic indicator checkpoints exist"
        )

    op.drop_column("indicator_checkpoints", "state_payload")
    op.drop_column("indicator_checkpoints", "requirements_manifest")
    for name in _LEGACY_REQUIRED_COLUMNS:
        existing_type: sa.types.TypeEngine[object]
        if name == "adx_dx_seed_count":
            existing_type = sa.BigInteger()
        else:
            existing_type = sa.Numeric()
        op.alter_column(
            "indicator_checkpoints",
            name,
            existing_type=existing_type,
            nullable=False,
        )
