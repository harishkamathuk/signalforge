"""Generalise strategy-evaluation persistence to strategy-neutral decision facts.

Revision ID: 20261003_0006
Revises: 20260930_0005
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20261003_0006"
down_revision: str | None = "20260930_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_V1_KIND = "intraday_momentum_v1.evaluation.v1"
_LEGACY_REQUIRED = (
    "trend_passed",
    "momentum_passed",
    "rsi_passed",
    "adx_passed",
    "setup_passed",
)


def upgrade() -> None:
    """Add generic decision identity/diagnostics and preserve legacy V1 rows."""

    op.add_column(
        "strategy_evaluations",
        sa.Column("decision_kind", sa.String(128), nullable=True),
    )
    op.add_column(
        "strategy_evaluations",
        sa.Column(
            "diagnostics",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )

    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            UPDATE strategy_evaluations
            SET decision_kind = :kind,
                diagnostics = jsonb_build_object(
                    'adx_passed', adx_passed,
                    'macd_signal_positive', macd_signal_positive,
                    'momentum_passed', momentum_passed,
                    'rsi_passed', rsi_passed,
                    'setup_passed', setup_passed,
                    'trend_passed', trend_passed
                )
            WHERE decision_kind IS NULL
            """
        ),
        {"kind": _V1_KIND},
    )

    op.alter_column("strategy_evaluations", "decision_kind", nullable=False)
    op.alter_column("strategy_evaluations", "diagnostics", nullable=False)
    for name in _LEGACY_REQUIRED:
        op.alter_column(
            "strategy_evaluations",
            name,
            existing_type=sa.Boolean(),
            nullable=True,
        )


def downgrade() -> None:
    """Restore the historical V1 shape only when every fact is losslessly V1."""

    bind = op.get_bind()
    non_v1 = bind.execute(
        sa.text(
            """
            SELECT count(*)
            FROM strategy_evaluations
            WHERE decision_kind <> :kind
            """
        ),
        {"kind": _V1_KIND},
    ).scalar_one()
    if non_v1:
        raise RuntimeError(
            "Cannot downgrade SF-066 while non-V1 strategy decision facts exist"
        )

    bind.execute(
        sa.text(
            """
            UPDATE strategy_evaluations
            SET trend_passed = (diagnostics ->> 'trend_passed')::boolean,
                momentum_passed = (diagnostics ->> 'momentum_passed')::boolean,
                rsi_passed = (diagnostics ->> 'rsi_passed')::boolean,
                adx_passed = (diagnostics ->> 'adx_passed')::boolean,
                macd_signal_positive = CASE
                    WHEN diagnostics ? 'macd_signal_positive'
                         AND diagnostics -> 'macd_signal_positive' <> 'null'::jsonb
                    THEN (diagnostics ->> 'macd_signal_positive')::boolean
                    ELSE NULL
                END,
                setup_passed = (diagnostics ->> 'setup_passed')::boolean
            """
        )
    )
    missing = bind.execute(
        sa.text(
            """
            SELECT count(*)
            FROM strategy_evaluations
            WHERE trend_passed IS NULL
               OR momentum_passed IS NULL
               OR rsi_passed IS NULL
               OR adx_passed IS NULL
               OR setup_passed IS NULL
            """
        )
    ).scalar_one()
    if missing:
        raise RuntimeError(
            "Cannot downgrade SF-066 because a V1 decision lacks legacy diagnostics"
        )

    op.drop_column("strategy_evaluations", "diagnostics")
    op.drop_column("strategy_evaluations", "decision_kind")
    for name in _LEGACY_REQUIRED:
        op.alter_column(
            "strategy_evaluations",
            name,
            existing_type=sa.Boolean(),
            nullable=False,
        )
