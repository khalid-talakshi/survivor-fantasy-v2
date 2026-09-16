"""Index active membership navigation lookups by account."""

from collections.abc import Sequence

from alembic import op

revision: str = "20260916_0004"
down_revision: str | None = "20260914_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX ix_membership_active_account_league "
        "ON app.league_membership (account_id, league_id) WHERE deleted_at IS NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX app.ix_membership_active_account_league")
