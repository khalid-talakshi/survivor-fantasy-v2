"""Associate the system owner with its immutable initial league."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260914_0003"
down_revision: str | None = "20260914_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "app"
RUNTIME_ROLE = "survivor_fantasy_runtime"


def upgrade() -> None:
    op.create_table(
        "system_owner_initial_league",
        sa.Column("account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("league_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["account_id"], ["app.system_role.account_id"],
            name="fk_system_owner_initial_league_role",
        ),
        sa.ForeignKeyConstraint(
            ["league_id"], ["app.league.id"],
            name="fk_system_owner_initial_league_league",
        ),
        sa.PrimaryKeyConstraint("account_id"),
        schema=SCHEMA,
    )
    op.execute(
        """
        WITH membership_counts AS (
            SELECT account_id, count(DISTINCT league_id) AS league_count
            FROM app.league_membership
            GROUP BY account_id
        ), association AS (
            SELECT membership.account_id, min(membership.league_id::text)::uuid AS league_id
            FROM app.league_membership AS membership
            JOIN app.league AS league ON league.id = membership.league_id
            JOIN membership_counts AS counts ON counts.account_id = membership.account_id
            WHERE membership.is_commissioner = true
              AND membership.deleted_at IS NULL
              AND league.deleted_at IS NULL
              AND counts.league_count = 1
            GROUP BY membership.account_id
            HAVING count(DISTINCT league_id) = 1
        )
        INSERT INTO app.system_owner_initial_league (account_id, league_id)
        SELECT role.account_id, association.league_id
        FROM app.system_role AS role JOIN association USING (account_id)
        ON CONFLICT (account_id) DO NOTHING
        """
    )
    op.execute(
        f"GRANT SELECT, INSERT ON {SCHEMA}.system_owner_initial_league TO {RUNTIME_ROLE}"
    )


def downgrade() -> None:
    op.execute(f"REVOKE ALL ON {SCHEMA}.system_owner_initial_league FROM {RUNTIME_ROLE}")
    op.drop_table("system_owner_initial_league", schema=SCHEMA)
