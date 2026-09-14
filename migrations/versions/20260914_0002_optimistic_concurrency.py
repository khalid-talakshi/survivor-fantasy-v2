"""Add optimistic concurrency columns to commissioner-managed aggregates.

Revision ID: 20260914_0002
Revises: 20260913_0001
Create Date: 2026-09-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260914_0002"
down_revision: str | None = "20260913_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "app"
VERSIONED_TABLES = (
    "league",
    "league_membership",
    "bucket",
    "castaway",
    "scoring_action",
    "scoring_event",
    "betting_config",
)


def upgrade() -> None:
    for table_name in VERSIONED_TABLES:
        constraint_name = f"ck_{table_name}_version_positive"
        op.add_column(
            table_name,
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
            schema=SCHEMA,
        )
        op.create_check_constraint(constraint_name, table_name, "version > 0", schema=SCHEMA)


def downgrade() -> None:
    for table_name in reversed(VERSIONED_TABLES):
        op.drop_constraint(f"ck_{table_name}_version_positive", table_name, schema=SCHEMA)
        op.drop_column(table_name, "version", schema=SCHEMA)
