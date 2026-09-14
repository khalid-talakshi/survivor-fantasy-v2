"""Create the private application schema.

Revision ID: 20260913_0001
Revises:
Create Date: 2026-09-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260913_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "app"
RUNTIME_ROLE = "survivor_fantasy_runtime"

league_state = postgresql.ENUM(
    "active", "completed", name="league_state", schema=SCHEMA, create_type=False
)
participation_state = postgresql.ENUM(
    "pending_roster",
    "active",
    "non_playing",
    name="participation_state",
    schema=SCHEMA,
    create_type=False,
)
castaway_status = postgresql.ENUM(
    "active", "eliminated", name="castaway_status", schema=SCHEMA, create_type=False
)
budget_source = postgresql.ENUM(
    "initial",
    "carry_forward",
    "late_entry",
    name="budget_source",
    schema=SCHEMA,
    create_type=False,
)
notification_type = postgresql.ENUM(
    "existing_user_added", name="notification_type", schema=SCHEMA, create_type=False
)
notification_status = postgresql.ENUM(
    "pending", "sent", "failed", name="notification_status", schema=SCHEMA, create_type=False
)

UUID = postgresql.UUID(as_uuid=True)
TIMESTAMPTZ = sa.DateTime(timezone=True)


def _id() -> sa.Column[object]:
    return sa.Column("id", UUID, primary_key=True, server_default=sa.text("gen_random_uuid()"))


def upgrade() -> None:
    op.execute(sa.schema.CreateSchema(SCHEMA))
    op.execute(
        sa.text(
            """
            DO $role$
            DECLARE
                runtime_role pg_roles%ROWTYPE;
            BEGIN
                SELECT * INTO runtime_role
                FROM pg_roles
                WHERE rolname = 'survivor_fantasy_runtime';

                IF NOT FOUND THEN
                    CREATE ROLE survivor_fantasy_runtime LOGIN
                        NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT
                        NOREPLICATION NOBYPASSRLS;
                ELSE
                    IF runtime_role.rolsuper
                        OR runtime_role.rolcreatedb
                        OR runtime_role.rolcreaterole
                        OR runtime_role.rolreplication
                        OR runtime_role.rolbypassrls
                    THEN
                        RAISE EXCEPTION
                            'existing survivor_fantasy_runtime role has privileged attributes';
                    END IF;

                    IF EXISTS (
                        SELECT 1
                        FROM pg_auth_members AS membership
                        WHERE membership.member = runtime_role.oid
                           OR membership.roleid = runtime_role.oid
                    ) THEN
                        RAISE EXCEPTION
                            'existing survivor_fantasy_runtime role has role memberships';
                    END IF;

                    IF EXISTS (
                        SELECT 1
                        FROM pg_database
                        WHERE datname = current_database()
                          AND datdba = runtime_role.oid
                    ) THEN
                        RAISE EXCEPTION
                            'existing survivor_fantasy_runtime role owns the current database';
                    END IF;

                    IF EXISTS (
                        SELECT 1
                        FROM pg_namespace
                        WHERE nspowner = runtime_role.oid
                          AND nspname !~ '^pg_'
                          AND nspname <> 'information_schema'
                    ) THEN
                        RAISE EXCEPTION
                            'existing survivor_fantasy_runtime role owns a non-system schema';
                    END IF;

                    ALTER ROLE survivor_fantasy_runtime PASSWORD NULL;

                    ALTER ROLE survivor_fantasy_runtime LOGIN
                        NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT
                        NOREPLICATION NOBYPASSRLS;
                END IF;

                ALTER ROLE survivor_fantasy_runtime SET search_path TO pg_catalog, app;
            END
            $role$;
            """
        )
    )
    op.execute("REVOKE ALL ON SCHEMA app FROM PUBLIC")
    op.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
    op.execute("REVOKE CREATE ON SCHEMA public FROM survivor_fantasy_runtime")
    op.execute(
        """
        DO $database_grant$
        BEGIN
            EXECUTE format(
                'REVOKE CREATE ON DATABASE %I FROM survivor_fantasy_runtime',
                current_database()
            );
            EXECUTE format(
                'GRANT CONNECT ON DATABASE %I TO survivor_fantasy_runtime',
                current_database()
            );
        END
        $database_grant$;
        """
    )

    for enum_type in (
        league_state,
        participation_state,
        castaway_status,
        budget_source,
        notification_type,
        notification_status,
    ):
        enum_type.create(op.get_bind(), checkfirst=False)

    op.create_table(
        "account",
        _id(),
        sa.Column("supabase_user_id", UUID, nullable=False, unique=True),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("deleted_at", TIMESTAMPTZ),
        sa.CheckConstraint("btrim(email) <> ''", name="ck_account_email_not_blank"),
        sa.CheckConstraint("btrim(display_name) <> ''", name="ck_account_display_name_not_blank"),
        schema=SCHEMA,
    )
    op.create_table(
        "league",
        _id(),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("season_name", sa.Text(), nullable=False),
        sa.Column("state", league_state, nullable=False, server_default="active"),
        sa.Column("roster_locked", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("deleted_at", TIMESTAMPTZ),
        sa.CheckConstraint("btrim(name) <> ''", name="ck_league_name_not_blank"),
        sa.CheckConstraint("btrim(season_name) <> ''", name="ck_league_season_name_not_blank"),
        sa.UniqueConstraint("id", "state", name="uq_league_id_state"),
        schema=SCHEMA,
    )
    op.create_table(
        "league_membership",
        _id(),
        sa.Column("account_id", UUID, nullable=False),
        sa.Column("league_id", UUID, nullable=False),
        sa.Column("is_commissioner", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "participation_state",
            participation_state,
            nullable=False,
            server_default="pending_roster",
        ),
        sa.Column("activated_at", TIMESTAMPTZ),
        sa.Column("deleted_at", TIMESTAMPTZ),
        sa.ForeignKeyConstraint(["account_id"], ["app.account.id"]),
        sa.ForeignKeyConstraint(["league_id"], ["app.league.id"]),
        sa.CheckConstraint(
            "participation_state <> 'active' OR activated_at IS NOT NULL",
            name="ck_membership_active_has_activation",
        ),
        sa.UniqueConstraint("id", "league_id", name="uq_membership_id_league"),
        schema=SCHEMA,
    )
    op.create_table(
        "system_role",
        sa.Column("account_id", UUID, primary_key=True),
        sa.Column("is_system_owner", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["app.account.id"]),
        sa.CheckConstraint("is_system_owner", name="ck_system_role_owner_true"),
        sa.UniqueConstraint("is_system_owner", name="uq_single_system_owner"),
        schema=SCHEMA,
    )
    op.create_table(
        "bucket",
        _id(),
        sa.Column("league_id", UUID, nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("display_order", sa.Integer(), nullable=False),
        sa.Column("deleted_at", TIMESTAMPTZ),
        sa.ForeignKeyConstraint(["league_id"], ["app.league.id"]),
        sa.CheckConstraint("btrim(name) <> ''", name="ck_bucket_name_not_blank"),
        sa.CheckConstraint("display_order >= 0", name="ck_bucket_display_order_nonnegative"),
        sa.UniqueConstraint("id", "league_id", name="uq_bucket_id_league"),
        schema=SCHEMA,
    )
    op.create_table(
        "castaway",
        _id(),
        sa.Column("league_id", UUID, nullable=False),
        sa.Column("bucket_id", UUID, nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("image_url", sa.Text()),
        sa.Column("age", sa.Integer()),
        sa.Column("city", sa.Text()),
        sa.Column("state_or_region", sa.Text()),
        sa.Column("occupation", sa.Text()),
        sa.Column("description", sa.Text()),
        sa.Column("hobbies", sa.Text()),
        sa.Column("tribes", sa.Text()),
        sa.Column("status", castaway_status, nullable=False, server_default="active"),
        sa.Column("placement", sa.Integer()),
        sa.Column("deleted_at", TIMESTAMPTZ),
        sa.ForeignKeyConstraint(
            ["bucket_id", "league_id"], ["app.bucket.id", "app.bucket.league_id"]
        ),
        sa.CheckConstraint("btrim(name) <> ''", name="ck_castaway_name_not_blank"),
        sa.CheckConstraint("age IS NULL OR age > 0", name="ck_castaway_age_positive"),
        sa.CheckConstraint(
            "placement IS NULL OR placement > 0", name="ck_castaway_placement_positive"
        ),
        sa.UniqueConstraint("id", "league_id", name="uq_castaway_id_league"),
        sa.UniqueConstraint(
            "id", "bucket_id", "league_id", name="uq_castaway_id_bucket_league"
        ),
        schema=SCHEMA,
    )
    op.create_table(
        "roster_pick",
        _id(),
        sa.Column("league_id", UUID, nullable=False),
        sa.Column("membership_id", UUID, nullable=False),
        sa.Column("bucket_id", UUID, nullable=False),
        sa.Column("castaway_id", UUID, nullable=False),
        sa.Column("deletion_batch_id", UUID),
        sa.Column("deleted_at", TIMESTAMPTZ),
        sa.ForeignKeyConstraint(
            ["membership_id", "league_id"],
            ["app.league_membership.id", "app.league_membership.league_id"],
        ),
        sa.ForeignKeyConstraint(
            ["bucket_id", "league_id"], ["app.bucket.id", "app.bucket.league_id"]
        ),
        sa.ForeignKeyConstraint(
            ["castaway_id", "bucket_id", "league_id"],
            ["app.castaway.id", "app.castaway.bucket_id", "app.castaway.league_id"],
        ),
        schema=SCHEMA,
    )
    op.create_table(
        "scoring_action",
        _id(),
        sa.Column("league_id", UUID, nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("points", sa.Numeric(6, 1), nullable=False),
        sa.Column("deletion_batch_id", UUID),
        sa.Column("deleted_at", TIMESTAMPTZ),
        sa.ForeignKeyConstraint(["league_id"], ["app.league.id"]),
        sa.CheckConstraint("btrim(name) <> ''", name="ck_scoring_action_name_not_blank"),
        sa.CheckConstraint(
            "points * 2 = round(points * 2)", name="ck_scoring_action_half_point"
        ),
        sa.UniqueConstraint("id", "league_id", name="uq_scoring_action_id_league"),
        schema=SCHEMA,
    )
    op.create_table(
        "scoring_event",
        _id(),
        sa.Column("league_id", UUID, nullable=False),
        sa.Column("action_id", UUID, nullable=False),
        sa.Column("castaway_id", UUID, nullable=False),
        sa.Column("episode", sa.Integer(), nullable=False),
        sa.Column("note", sa.Text()),
        sa.Column("deletion_batch_id", UUID),
        sa.Column("deleted_at", TIMESTAMPTZ),
        sa.ForeignKeyConstraint(
            ["action_id", "league_id"],
            ["app.scoring_action.id", "app.scoring_action.league_id"],
        ),
        sa.ForeignKeyConstraint(
            ["castaway_id", "league_id"],
            ["app.castaway.id", "app.castaway.league_id"],
        ),
        sa.CheckConstraint("episode > 0", name="ck_scoring_event_episode_positive"),
        schema=SCHEMA,
    )
    op.create_table(
        "betting_config",
        sa.Column("league_id", UUID, primary_key=True),
        sa.Column("player_budget", sa.Integer(), nullable=False),
        sa.Column("castaway_cap", sa.Integer(), nullable=False),
        sa.Column("late_entry_budget", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.ForeignKeyConstraint(["league_id"], ["app.league.id"]),
        sa.CheckConstraint("player_budget >= 0", name="ck_betting_config_player_budget"),
        sa.CheckConstraint("castaway_cap >= 0", name="ck_betting_config_castaway_cap"),
        sa.CheckConstraint("late_entry_budget >= 0", name="ck_betting_config_late_entry_budget"),
        schema=SCHEMA,
    )
    op.create_table(
        "wager_set",
        _id(),
        sa.Column("league_id", UUID, nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("locked", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("eligibility_closed_at", TIMESTAMPTZ),
        sa.Column("finalized_at", TIMESTAMPTZ),
        sa.Column("reset_from_set_id", UUID),
        sa.ForeignKeyConstraint(["league_id"], ["app.betting_config.league_id"]),
        sa.CheckConstraint("sequence_number > 0", name="ck_wager_set_sequence_positive"),
        sa.CheckConstraint(
            "finalized_at IS NULL OR locked", name="ck_wager_set_finalized_is_locked"
        ),
        sa.UniqueConstraint("id", "league_id", name="uq_wager_set_id_league"),
        sa.UniqueConstraint("league_id", "sequence_number", name="uq_wager_set_league_sequence"),
        schema=SCHEMA,
    )
    op.create_foreign_key(
        "fk_wager_set_reset_same_league",
        "wager_set",
        "wager_set",
        ["reset_from_set_id", "league_id"],
        ["id", "league_id"],
        source_schema=SCHEMA,
        referent_schema=SCHEMA,
    )
    op.create_table(
        "betting_participation",
        _id(),
        sa.Column("league_id", UUID, nullable=False),
        sa.Column("membership_id", UUID, nullable=False),
        sa.Column("wager_set_id", UUID, nullable=False),
        sa.Column("budget", sa.Integer(), nullable=False),
        sa.Column("budget_source", budget_source, nullable=False),
        sa.Column("submitted_at", TIMESTAMPTZ),
        sa.Column("deleted_at", TIMESTAMPTZ),
        sa.ForeignKeyConstraint(
            ["membership_id", "league_id"],
            ["app.league_membership.id", "app.league_membership.league_id"],
        ),
        sa.ForeignKeyConstraint(
            ["wager_set_id", "league_id"], ["app.wager_set.id", "app.wager_set.league_id"]
        ),
        sa.CheckConstraint("budget >= 0", name="ck_betting_participation_budget_nonnegative"),
        sa.UniqueConstraint("id", "league_id", name="uq_betting_participation_id_league"),
        schema=SCHEMA,
    )
    op.create_table(
        "wager",
        _id(),
        sa.Column("league_id", UUID, nullable=False),
        sa.Column("participation_id", UUID, nullable=False),
        sa.Column("castaway_id", UUID, nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("deleted_at", TIMESTAMPTZ),
        sa.ForeignKeyConstraint(
            ["participation_id", "league_id"],
            ["app.betting_participation.id", "app.betting_participation.league_id"],
        ),
        sa.ForeignKeyConstraint(
            ["castaway_id", "league_id"],
            ["app.castaway.id", "app.castaway.league_id"],
        ),
        sa.CheckConstraint("amount >= 0", name="ck_wager_amount_nonnegative"),
        schema=SCHEMA,
    )
    op.create_table(
        "audit_event",
        _id(),
        sa.Column("actor_account_id", UUID, nullable=False),
        sa.Column("league_id", UUID, nullable=False),
        sa.Column("entity_type", sa.Text()),
        sa.Column("entity_id", UUID),
        sa.Column("correlation_id", UUID, nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text()),
        sa.Column("before_state", postgresql.JSONB()),
        sa.Column("after_state", postgresql.JSONB()),
        sa.Column(
            "occurred_at", TIMESTAMPTZ, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")
        ),
        sa.ForeignKeyConstraint(["actor_account_id"], ["app.account.id"]),
        sa.ForeignKeyConstraint(["league_id"], ["app.league.id"]),
        sa.CheckConstraint("btrim(event_type) <> ''", name="ck_audit_event_type_not_blank"),
        sa.CheckConstraint(
            "(entity_type IS NULL) = (entity_id IS NULL)", name="ck_audit_event_target_pair"
        ),
        schema=SCHEMA,
    )
    op.create_table(
        "notification_dispatch",
        _id(),
        sa.Column("league_id", UUID, nullable=False),
        sa.Column("account_id", UUID, nullable=False),
        sa.Column("notification_type", notification_type, nullable=False),
        sa.Column("status", notification_status, nullable=False, server_default="pending"),
        sa.Column("provider_message_id", sa.Text()),
        sa.Column("deduplication_key", sa.Text(), nullable=False, unique=True),
        sa.Column("last_error", sa.Text()),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at", TIMESTAMPTZ, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")
        ),
        sa.Column(
            "updated_at", TIMESTAMPTZ, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")
        ),
        sa.ForeignKeyConstraint(["league_id"], ["app.league.id"]),
        sa.ForeignKeyConstraint(["account_id"], ["app.account.id"]),
        sa.CheckConstraint(
            "btrim(deduplication_key) <> ''", name="ck_notification_deduplication_key_not_blank"
        ),
        sa.CheckConstraint("retry_count >= 0", name="ck_notification_retry_count_nonnegative"),
        schema=SCHEMA,
    )

    partial_indexes = (
        "CREATE UNIQUE INDEX uq_account_active_email ON app.account "
        "(lower(btrim(email))) WHERE deleted_at IS NULL",
        "CREATE UNIQUE INDEX uq_membership_active_account_league ON app.league_membership "
        "(league_id, account_id) WHERE deleted_at IS NULL",
        "CREATE UNIQUE INDEX uq_roster_pick_active_membership_bucket ON app.roster_pick "
        "(membership_id, bucket_id) WHERE deleted_at IS NULL",
        "CREATE UNIQUE INDEX uq_castaway_active_name ON app.castaway "
        "(league_id, lower(btrim(name))) WHERE deleted_at IS NULL",
        "CREATE UNIQUE INDEX uq_castaway_active_placement ON app.castaway "
        "(league_id, placement) WHERE deleted_at IS NULL AND placement IS NOT NULL",
        "CREATE UNIQUE INDEX uq_scoring_action_active_name ON app.scoring_action "
        "(league_id, lower(btrim(name))) WHERE deleted_at IS NULL",
        "CREATE UNIQUE INDEX uq_betting_participation_active_membership_set "
        "ON app.betting_participation (membership_id, wager_set_id) WHERE deleted_at IS NULL",
        "CREATE UNIQUE INDEX uq_wager_active_participation_castaway ON app.wager "
        "(participation_id, castaway_id) WHERE deleted_at IS NULL",
        "CREATE UNIQUE INDEX uq_wager_set_current_league ON app.wager_set "
        "(league_id) WHERE finalized_at IS NULL",
    )
    for statement in partial_indexes:
        op.execute(statement)

    op.create_index(
        "ix_audit_event_target",
        "audit_event",
        ["league_id", "entity_type", "entity_id"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_audit_event_correlation", "audit_event", ["correlation_id"], schema=SCHEMA
    )
    op.create_index(
        "ix_notification_dispatch_league_status",
        "notification_dispatch",
        ["league_id", "status"],
        schema=SCHEMA,
    )

    op.execute(f"GRANT USAGE ON SCHEMA {SCHEMA} TO {RUNTIME_ROLE}")
    mutable_tables = (
        "account",
        "league",
        "league_membership",
        "bucket",
        "castaway",
        "roster_pick",
        "scoring_action",
        "scoring_event",
        "betting_config",
        "wager_set",
        "betting_participation",
        "wager",
        "notification_dispatch",
    )
    for table_name in mutable_tables:
        op.execute(
            f"GRANT SELECT, INSERT, UPDATE ON {SCHEMA}.{table_name} TO {RUNTIME_ROLE}"
        )
    op.execute(f"GRANT SELECT, INSERT ON {SCHEMA}.system_role TO {RUNTIME_ROLE}")
    op.execute(f"GRANT SELECT, INSERT ON {SCHEMA}.audit_event TO {RUNTIME_ROLE}")


def downgrade() -> None:
    op.execute(f"REVOKE ALL ON ALL TABLES IN SCHEMA {SCHEMA} FROM {RUNTIME_ROLE}")
    op.execute(f"REVOKE USAGE ON SCHEMA {SCHEMA} FROM {RUNTIME_ROLE}")
    op.execute(sa.schema.DropSchema(SCHEMA, cascade=True))
    op.execute(
        """
        DO $database_grant$
        BEGIN
            EXECUTE format(
                'REVOKE CONNECT ON DATABASE %I FROM survivor_fantasy_runtime',
                current_database()
            );
        END
        $database_grant$;
        """
    )
