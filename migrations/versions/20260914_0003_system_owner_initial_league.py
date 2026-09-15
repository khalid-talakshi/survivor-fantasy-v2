"""Associate the system owner with its immutable initial league.

Revision ID: 20260914_0003
Revises: 20260914_0002
Create Date: 2026-09-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260914_0003"
down_revision: str | None = "20260914_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "app"


def upgrade() -> None:
    op.add_column(
        "system_role",
        sa.Column("initial_league_id", postgresql.UUID(as_uuid=True), nullable=True),
        schema=SCHEMA,
    )
    op.execute(
        """
        UPDATE app.system_role AS system_role
        SET initial_league_id = association.league_id
        FROM (
            SELECT account_id, min(league_id::text)::uuid AS league_id
            FROM app.league_membership AS membership
            JOIN app.league AS league ON league.id = membership.league_id
            WHERE membership.is_commissioner = true
              AND membership.deleted_at IS NULL
              AND league.deleted_at IS NULL
            GROUP BY account_id
            HAVING count(DISTINCT league_id) = 1
        ) AS association
        WHERE association.account_id = system_role.account_id
        """
    )
    op.execute(
        """
        DO $migration$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM app.system_role
                WHERE initial_league_id IS NULL
            ) THEN
                RAISE EXCEPTION
                    'cannot associate an existing system owner with exactly one initial league; '
                    'ensure exactly one distinct owner league membership and retry the migration';
            END IF;
        END
        $migration$;
        """
    )
    op.create_foreign_key(
        "fk_system_role_initial_league",
        "system_role",
        "league",
        ["initial_league_id"],
        ["id"],
        source_schema=SCHEMA,
        referent_schema=SCHEMA,
    )
    op.alter_column(
        "system_role",
        "initial_league_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=False,
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.alter_column(
        "system_role",
        "initial_league_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=True,
        schema=SCHEMA,
    )
    op.drop_constraint("fk_system_role_initial_league", "system_role", schema=SCHEMA)
    op.drop_column("system_role", "initial_league_id", schema=SCHEMA)
