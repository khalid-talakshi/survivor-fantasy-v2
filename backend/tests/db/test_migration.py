import os
from collections.abc import Callable
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.engine import URL
from sqlalchemy.exc import DBAPIError

from backend.tests.db.conftest import REPOSITORY_ROOT, _alembic_config, _psycopg_url

EXPECTED_TABLES = {
    "account",
    "audit_event",
    "betting_config",
    "betting_participation",
    "bucket",
    "castaway",
    "league",
    "league_membership",
    "notification_dispatch",
    "roster_pick",
    "scoring_action",
    "scoring_event",
    "system_role",
    "wager",
    "wager_set",
}

VERSIONED_TABLES = {
    "betting_config",
    "bucket",
    "castaway",
    "league",
    "league_membership",
    "scoring_action",
    "scoring_event",
}

EXPECTED_COLUMNS = {
    "account": {"id", "supabase_user_id", "email", "display_name", "deleted_at"},
    "audit_event": {
        "id",
        "actor_account_id",
        "league_id",
        "entity_type",
        "entity_id",
        "correlation_id",
        "event_type",
        "reason",
        "before_state",
        "after_state",
        "occurred_at",
    },
    "betting_config": {
        "league_id",
        "player_budget",
        "castaway_cap",
        "late_entry_budget",
        "enabled",
        "version",
    },
    "betting_participation": {
        "id",
        "league_id",
        "membership_id",
        "wager_set_id",
        "budget",
        "budget_source",
        "submitted_at",
        "deleted_at",
    },
    "bucket": {"id", "league_id", "name", "display_order", "deleted_at", "version"},
    "castaway": {
        "id",
        "league_id",
        "bucket_id",
        "name",
        "image_url",
        "age",
        "city",
        "state_or_region",
        "occupation",
        "description",
        "hobbies",
        "tribes",
        "status",
        "placement",
        "deleted_at",
        "version",
    },
    "league": {"id", "name", "season_name", "state", "roster_locked", "deleted_at", "version"},
    "league_membership": {
        "id",
        "account_id",
        "league_id",
        "is_commissioner",
        "participation_state",
        "activated_at",
        "deleted_at",
        "version",
    },
    "notification_dispatch": {
        "id",
        "league_id",
        "account_id",
        "notification_type",
        "status",
        "provider_message_id",
        "deduplication_key",
        "last_error",
        "retry_count",
        "created_at",
        "updated_at",
    },
    "roster_pick": {
        "id",
        "league_id",
        "membership_id",
        "bucket_id",
        "castaway_id",
        "deletion_batch_id",
        "deleted_at",
    },
    "scoring_action": {
        "id",
        "league_id",
        "name",
        "points",
        "deletion_batch_id",
        "deleted_at",
        "version",
    },
    "scoring_event": {
        "id",
        "league_id",
        "action_id",
        "castaway_id",
        "episode",
        "note",
        "deletion_batch_id",
        "deleted_at",
        "version",
    },
    "system_role": {"account_id", "is_system_owner", "initial_league_id"},
    "wager": {"id", "league_id", "participation_id", "castaway_id", "amount", "deleted_at"},
    "wager_set": {
        "id",
        "league_id",
        "sequence_number",
        "locked",
        "eligibility_closed_at",
        "finalized_at",
        "reset_from_set_id",
    },
}

EXPECTED_ENUMS = {
    "budget_source": ["initial", "carry_forward", "late_entry"],
    "castaway_status": ["active", "eliminated"],
    "league_state": ["active", "completed"],
    "notification_status": ["pending", "sent", "failed"],
    "notification_type": ["existing_user_added"],
    "participation_state": ["pending_roster", "active", "non_playing"],
}

EXPECTED_PARTIAL_INDEXES = {
    "uq_account_active_email",
    "uq_betting_participation_active_membership_set",
    "uq_castaway_active_name",
    "uq_castaway_active_placement",
    "uq_membership_active_account_league",
    "uq_roster_pick_active_membership_bucket",
    "uq_scoring_action_active_name",
    "uq_wager_active_participation_castaway",
    "uq_wager_set_current_league",
}

EXPECTED_CHECK_CONSTRAINTS = {
    "ck_account_display_name_not_blank",
    "ck_account_email_not_blank",
    "ck_audit_event_target_pair",
    "ck_audit_event_type_not_blank",
    "ck_betting_config_castaway_cap",
    "ck_betting_config_late_entry_budget",
    "ck_betting_config_player_budget",
    "ck_betting_config_version_positive",
    "ck_betting_participation_budget_nonnegative",
    "ck_bucket_display_order_nonnegative",
    "ck_bucket_name_not_blank",
    "ck_bucket_version_positive",
    "ck_castaway_age_positive",
    "ck_castaway_name_not_blank",
    "ck_castaway_placement_positive",
    "ck_castaway_version_positive",
    "ck_league_name_not_blank",
    "ck_league_season_name_not_blank",
    "ck_league_version_positive",
    "ck_membership_active_has_activation",
    "ck_league_membership_version_positive",
    "ck_notification_deduplication_key_not_blank",
    "ck_notification_retry_count_nonnegative",
    "ck_scoring_action_half_point",
    "ck_scoring_action_name_not_blank",
    "ck_scoring_action_version_positive",
    "ck_scoring_event_episode_positive",
    "ck_scoring_event_version_positive",
    "ck_system_role_owner_true",
    "ck_wager_amount_nonnegative",
    "ck_wager_set_finalized_is_locked",
    "ck_wager_set_sequence_positive",
}

EXPECTED_PARTIAL_INDEX_DEFINITIONS = {
    "uq_account_active_email": (
        "CREATE UNIQUE INDEX uq_account_active_email ON app.account USING btree "
        "(lower(btrim(email))) WHERE (deleted_at IS NULL)"
    ),
    "uq_betting_participation_active_membership_set": (
        "CREATE UNIQUE INDEX uq_betting_participation_active_membership_set ON "
        "app.betting_participation USING btree (membership_id, wager_set_id) "
        "WHERE (deleted_at IS NULL)"
    ),
    "uq_castaway_active_name": (
        "CREATE UNIQUE INDEX uq_castaway_active_name ON app.castaway USING btree "
        "(league_id, lower(btrim(name))) WHERE (deleted_at IS NULL)"
    ),
    "uq_castaway_active_placement": (
        "CREATE UNIQUE INDEX uq_castaway_active_placement ON app.castaway USING btree "
        "(league_id, placement) WHERE ((deleted_at IS NULL) AND (placement IS NOT NULL))"
    ),
    "uq_membership_active_account_league": (
        "CREATE UNIQUE INDEX uq_membership_active_account_league ON app.league_membership "
        "USING btree (league_id, account_id) WHERE (deleted_at IS NULL)"
    ),
    "uq_roster_pick_active_membership_bucket": (
        "CREATE UNIQUE INDEX uq_roster_pick_active_membership_bucket ON app.roster_pick "
        "USING btree (membership_id, bucket_id) WHERE (deleted_at IS NULL)"
    ),
    "uq_scoring_action_active_name": (
        "CREATE UNIQUE INDEX uq_scoring_action_active_name ON app.scoring_action USING btree "
        "(league_id, lower(btrim(name))) WHERE (deleted_at IS NULL)"
    ),
    "uq_wager_active_participation_castaway": (
        "CREATE UNIQUE INDEX uq_wager_active_participation_castaway ON app.wager USING btree "
        "(participation_id, castaway_id) WHERE (deleted_at IS NULL)"
    ),
    "uq_wager_set_current_league": (
        "CREATE UNIQUE INDEX uq_wager_set_current_league ON app.wager_set USING btree "
        "(league_id) WHERE (finalized_at IS NULL)"
    ),
}

EXPECTED_FOREIGN_KEY_RELATIONSHIPS = {
    ("app.audit_event", "app.account"),
    ("app.audit_event", "app.league"),
    ("app.betting_config", "app.league"),
    ("app.betting_participation", "app.league_membership"),
    ("app.betting_participation", "app.wager_set"),
    ("app.bucket", "app.league"),
    ("app.castaway", "app.bucket"),
    ("app.league_membership", "app.account"),
    ("app.league_membership", "app.league"),
    ("app.notification_dispatch", "app.account"),
    ("app.notification_dispatch", "app.league"),
    ("app.roster_pick", "app.bucket"),
    ("app.roster_pick", "app.castaway"),
    ("app.roster_pick", "app.league_membership"),
    ("app.scoring_action", "app.league"),
    ("app.scoring_event", "app.castaway"),
    ("app.scoring_event", "app.scoring_action"),
    ("app.system_role", "app.account"),
    ("app.system_role", "app.league"),
    ("app.wager", "app.betting_participation"),
    ("app.wager", "app.castaway"),
    ("app.wager_set", "app.betting_config"),
    ("app.wager_set", "app.wager_set"),
}


def test_upgrade_and_downgrade_from_empty_database(empty_database: URL) -> None:
    config = _alembic_config(empty_database)

    command.upgrade(config, "head")
    with psycopg.connect(_psycopg_url(empty_database)) as connection:
        assert connection.execute("SELECT to_regnamespace('app')").fetchone() == ("app",)
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            "20260914_0003",
        )

    command.downgrade(config, "base")
    with psycopg.connect(_psycopg_url(empty_database)) as connection:
        assert connection.execute("SELECT to_regnamespace('app')").fetchone() == (None,)
        assert connection.execute("SELECT count(*) FROM alembic_version").fetchone() == (0,)
        assert connection.execute(
            "SELECT rolcanlogin FROM pg_roles WHERE rolname = 'survivor_fantasy_runtime'"
        ).fetchone() == (True,)
        database_acl = connection.execute(
            "SELECT coalesce(datacl::text, '') FROM pg_database WHERE datname = current_database()"
        ).fetchone()
        assert database_acl is not None
        assert "survivor_fantasy_runtime" not in cast(str, database_acl[0])


def test_alembic_falls_back_to_database_url(
    empty_database: URL, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url = empty_database.set(drivername="postgresql+psycopg").render_as_string(
        hide_password=False
    )
    monkeypatch.delenv("MIGRATION_DATABASE_URL", raising=False)
    monkeypatch.setenv("DATABASE_URL", database_url)

    command.upgrade(Config(REPOSITORY_ROOT / "alembic.ini"), "head")

    with psycopg.connect(_psycopg_url(empty_database)) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            "20260914_0003",
        )


def test_initial_league_marker_migration_backfills_an_unambiguous_owner_membership(
    empty_database: URL,
) -> None:
    config = _alembic_config(empty_database)
    command.upgrade(config, "20260914_0002")
    account_id, league_id = uuid4(), uuid4()

    with psycopg.connect(_psycopg_url(empty_database)) as connection:
        connection.execute(
            """
            INSERT INTO app.account (id, supabase_user_id, email, display_name)
            VALUES (%s, %s, %s, %s)
            """,
            (account_id, uuid4(), "owner@example.com", "Owner"),
        )
        connection.execute(
            "INSERT INTO app.league (id, name, season_name) VALUES (%s, %s, %s)",
            (league_id, "Initial league", "Season 49"),
        )
        connection.execute(
            "INSERT INTO app.system_role (account_id, is_system_owner) VALUES (%s, true)",
            (account_id,),
        )
        connection.execute(
            """
            INSERT INTO app.league_membership (account_id, league_id, is_commissioner)
            VALUES (%s, %s, true)
            """,
            (account_id, league_id),
        )
        connection.commit()

    command.upgrade(config, "head")

    with psycopg.connect(_psycopg_url(empty_database)) as connection:
        assert connection.execute(
            "SELECT initial_league_id FROM app.system_role WHERE account_id = %s", (account_id,)
        ).fetchone() == (league_id,)
        assert connection.execute(
            """
            SELECT is_nullable
            FROM information_schema.columns
            WHERE table_schema = 'app'
              AND table_name = 'system_role'
              AND column_name = 'initial_league_id'
            """
        ).fetchone() == ("NO",)


def test_initial_league_marker_migration_rejects_ambiguous_owner_memberships(
    empty_database: URL,
) -> None:
    config = _alembic_config(empty_database)
    command.upgrade(config, "20260914_0002")
    account_id, first_league_id, second_league_id = uuid4(), uuid4(), uuid4()

    with psycopg.connect(_psycopg_url(empty_database)) as connection:
        connection.execute(
            """
            INSERT INTO app.account (id, supabase_user_id, email, display_name)
            VALUES (%s, %s, %s, %s)
            """,
            (account_id, uuid4(), "owner@example.com", "Owner"),
        )
        connection.execute(
            """
            INSERT INTO app.league (id, name, season_name)
            VALUES (%s, %s, %s), (%s, %s, %s)
            """,
            (
                first_league_id,
                "First league",
                "Season 49",
                second_league_id,
                "Second league",
                "Season 50",
            ),
        )
        connection.execute(
            "INSERT INTO app.system_role (account_id, is_system_owner) VALUES (%s, true)",
            (account_id,),
        )
        connection.execute(
            """
            INSERT INTO app.league_membership (account_id, league_id, is_commissioner)
            VALUES (%s, %s, true), (%s, %s, true)
            """,
            (account_id, first_league_id, account_id, second_league_id),
        )
        connection.commit()

    with pytest.raises(DBAPIError, match="exactly one initial league"):
        command.upgrade(config, "head")


@pytest.mark.parametrize(
    ("is_commissioner", "deleted_at"),
    [(False, None), (True, datetime.now(UTC))],
    ids=["non_commissioner", "soft_deleted_commissioner"],
)
def test_initial_league_marker_migration_rejects_ineligible_owner_membership(
    empty_database: URL, is_commissioner: bool, deleted_at: datetime | None
) -> None:
    config = _alembic_config(empty_database)
    command.upgrade(config, "20260914_0002")
    account_id, league_id = uuid4(), uuid4()

    with psycopg.connect(_psycopg_url(empty_database)) as connection:
        connection.execute(
            """
            INSERT INTO app.account (id, supabase_user_id, email, display_name)
            VALUES (%s, %s, %s, %s)
            """,
            (account_id, uuid4(), "owner@example.com", "Owner"),
        )
        connection.execute(
            "INSERT INTO app.league (id, name, season_name) VALUES (%s, %s, %s)",
            (league_id, "Initial league", "Season 49"),
        )
        connection.execute(
            "INSERT INTO app.system_role (account_id, is_system_owner) VALUES (%s, true)",
            (account_id,),
        )
        connection.execute(
            """
            INSERT INTO app.league_membership
                (account_id, league_id, is_commissioner, deleted_at)
            VALUES (%s, %s, %s, %s)
            """,
            (account_id, league_id, is_commissioner, deleted_at),
        )
        connection.commit()

    with pytest.raises(DBAPIError, match="exactly one initial league"):
        command.upgrade(config, "head")


def test_private_schema_contains_every_designed_table_and_enum(
    migrated_database: psycopg.Connection[tuple[object, ...]],
) -> None:
    tables = {
        row[0]
        for row in migrated_database.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'app'"
        ).fetchall()
    }
    public_tables = migrated_database.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
    ).fetchall()
    column_rows = migrated_database.execute(
        """
        SELECT table_name, column_name
        FROM information_schema.columns
        WHERE table_schema = 'app'
        """
    ).fetchall()
    enum_rows = migrated_database.execute(
        """
        SELECT t.typname, array_agg(e.enumlabel ORDER BY e.enumsortorder)
        FROM pg_type AS t
        JOIN pg_namespace AS n ON n.oid = t.typnamespace
        JOIN pg_enum AS e ON e.enumtypid = t.oid
        WHERE n.nspname = 'app'
        GROUP BY t.typname
        """
    ).fetchall()

    assert tables == EXPECTED_TABLES
    assert public_tables == [("alembic_version",)]
    assert {name: labels for name, labels in enum_rows} == EXPECTED_ENUMS
    assert {
        table_name: {column for table, column in column_rows if table == table_name}
        for table_name in EXPECTED_TABLES
    } == EXPECTED_COLUMNS


def test_versioned_tables_default_to_one(
    migrated_database: psycopg.Connection[tuple[object, ...]],
) -> None:
    rows = migrated_database.execute(
        """
        SELECT table_name, column_default
        FROM information_schema.columns
        WHERE table_schema = 'app' AND column_name = 'version'
        """
    ).fetchall()

    assert {table_name for table_name, _ in rows} == VERSIONED_TABLES
    assert {default for _, default in rows} == {"1"}


def test_schema_has_required_indexes_types_and_least_privilege_grants(
    migrated_database: psycopg.Connection[tuple[object, ...]],
) -> None:
    partial_indexes = {
        row[0]: row[1]
        for row in migrated_database.execute(
            """
            SELECT indexname, indexdef
            FROM pg_indexes
            WHERE schemaname = 'app' AND indexdef LIKE '% WHERE %'
            """
        ).fetchall()
    }
    ordinary_indexes = {
        row[0]
        for row in migrated_database.execute(
            """
            SELECT indexname
            FROM pg_indexes
            WHERE schemaname = 'app'
              AND indexname IN (
                  'ix_audit_event_target',
                  'ix_audit_event_correlation',
                  'ix_notification_dispatch_league_status'
              )
            """
        ).fetchall()
    }
    numeric_metadata = migrated_database.execute(
        """
        SELECT data_type, numeric_precision, numeric_scale
        FROM information_schema.columns
        WHERE table_schema = 'app'
          AND table_name = 'scoring_action'
          AND column_name = 'points'
        """
    ).fetchone()
    public_schema_access = migrated_database.execute(
        "SELECT has_schema_privilege('public', 'app', 'USAGE')"
    ).fetchone()
    public_schema_create = migrated_database.execute(
        """
        SELECT EXISTS (
            SELECT 1
            FROM pg_namespace AS schema
            CROSS JOIN LATERAL aclexplode(
                coalesce(schema.nspacl, acldefault('n', schema.nspowner))
            ) AS privilege
            WHERE schema.nspname = 'public'
              AND privilege.grantee = 0
              AND privilege.privilege_type = 'CREATE'
        )
        """
    ).fetchone()
    runtime_public_schema_create = migrated_database.execute(
        """
        SELECT EXISTS (
            SELECT 1
            FROM pg_namespace AS schema
            CROSS JOIN LATERAL aclexplode(
                coalesce(schema.nspacl, acldefault('n', schema.nspowner))
            ) AS privilege
            WHERE schema.nspname = 'public'
              AND privilege.grantee = (
                  SELECT oid FROM pg_roles WHERE rolname = 'survivor_fantasy_runtime'
              )
              AND privilege.privilege_type = 'CREATE'
        )
        """
    ).fetchone()
    runtime_table_grants = migrated_database.execute(
        """
            SELECT table_name, array_agg(privilege_type::text ORDER BY privilege_type)
        FROM information_schema.role_table_grants
        WHERE table_schema = 'app' AND grantee = 'survivor_fantasy_runtime'
        GROUP BY table_name
        """
    ).fetchall()
    check_constraints = {
        row[0]
        for row in migrated_database.execute(
            """
            SELECT conname
            FROM pg_constraint
            WHERE contype = 'c'
              AND connamespace = 'app'::regnamespace
            """
        ).fetchall()
    }
    foreign_key_rows = migrated_database.execute(
        """
        SELECT conrelid::regclass::text, confrelid::regclass::text, cardinality(conkey)
        FROM pg_constraint
        WHERE contype = 'f'
          AND connamespace = 'app'::regnamespace
        """
    ).fetchall()
    runtime_role = migrated_database.execute(
        """
        SELECT
            rolcanlogin,
            rolsuper,
            rolcreatedb,
            rolcreaterole,
            rolinherit,
            rolreplication,
            rolbypassrls,
            rolconfig
        FROM pg_roles
        WHERE rolname = 'survivor_fantasy_runtime'
        """
    ).fetchone()
    runtime_memberships = migrated_database.execute(
        """
        SELECT parent.rolname, member.rolname
        FROM pg_auth_members AS membership
        JOIN pg_roles AS member ON member.oid = membership.member
        JOIN pg_roles AS parent ON parent.oid = membership.roleid
        WHERE member.rolname = 'survivor_fantasy_runtime'
           OR parent.rolname = 'survivor_fantasy_runtime'
        """
    ).fetchall()
    runtime_database_privileges = migrated_database.execute(
        """
        SELECT
            has_database_privilege('survivor_fantasy_runtime', current_database(), 'CONNECT'),
            has_database_privilege('survivor_fantasy_runtime', current_database(), 'CREATE')
        """
    ).fetchone()
    runtime_default_privileges = migrated_database.execute(
        """
        SELECT count(*)
        FROM pg_default_acl
        WHERE array_to_string(defaclacl, ',') LIKE '%survivor_fantasy_runtime%'
        """
    ).fetchone()

    assert set(partial_indexes) == EXPECTED_PARTIAL_INDEXES
    assert partial_indexes == EXPECTED_PARTIAL_INDEX_DEFINITIONS
    assert ordinary_indexes == {
        "ix_audit_event_target",
        "ix_audit_event_correlation",
        "ix_notification_dispatch_league_status",
    }
    assert numeric_metadata == ("numeric", 6, 1)
    assert check_constraints == EXPECTED_CHECK_CONSTRAINTS
    assert public_schema_access == (False,)
    assert public_schema_create == (False,)
    assert runtime_public_schema_create == (False,)
    assert len(runtime_table_grants) == len(EXPECTED_TABLES)
    runtime_grants = {
        cast(str, table_name): cast(list[str], grants)
        for table_name, grants in runtime_table_grants
    }
    assert runtime_grants == {
        **{
            table_name: ["INSERT", "SELECT", "UPDATE"]
            for table_name in EXPECTED_TABLES - {"audit_event", "system_role"}
        },
        "audit_event": ["INSERT", "SELECT"],
        "system_role": ["INSERT", "SELECT"],
    }
    assert runtime_role == (
        True,
        False,
        False,
        False,
        False,
        False,
        False,
        ["search_path=pg_catalog, app"],
    )
    assert runtime_memberships == []
    assert runtime_database_privileges == (True, False)
    assert runtime_default_privileges == (0,)
    assert {(source, target) for source, target, _ in foreign_key_rows} == (
        EXPECTED_FOREIGN_KEY_RELATIONSHIPS
    )
    assert len(foreign_key_rows) == len(EXPECTED_FOREIGN_KEY_RELATIONSHIPS)
    composite_ownership_counts = [
        column_count
        for source, target, column_count in foreign_key_rows
        if source
        in {
            "app.betting_participation",
            "app.castaway",
            "app.roster_pick",
            "app.scoring_event",
            "app.wager",
        }
        and target not in {"app.account", "app.league"}
    ]
    assert composite_ownership_counts
    assert all(isinstance(column_count, int) for column_count in composite_ownership_counts)
    assert all(
        column_count > 1
        for column_count in composite_ownership_counts
        if isinstance(column_count, int)
    )


@contextmanager
def _expect_integrity_error(
    connection: psycopg.Connection[tuple[object, ...]],
) -> Any:
    with pytest.raises(psycopg.IntegrityError), connection.transaction():
        yield


def _insert_returning_id(
    connection: psycopg.Connection[tuple[object, ...]],
    statement: str,
    parameters: tuple[object, ...],
) -> UUID:
    row = connection.execute(statement, parameters).fetchone()
    assert row is not None
    value = row[0]
    assert isinstance(value, UUID)
    return value


def _seed_two_leagues(
    connection: psycopg.Connection[tuple[object, ...]],
) -> dict[str, UUID]:
    values: dict[str, UUID] = {}
    for suffix in ("one", "two"):
        values[f"account_{suffix}"] = _insert_returning_id(
            connection,
            """
            INSERT INTO app.account (supabase_user_id, email, display_name)
            VALUES (%s, %s, %s) RETURNING id
            """,
            (uuid4(), f"{suffix}@example.com", f"Player {suffix}"),
        )
        values[f"league_{suffix}"] = _insert_returning_id(
            connection,
            "INSERT INTO app.league (name, season_name) VALUES (%s, %s) RETURNING id",
            (f"League {suffix}", f"Season {suffix}"),
        )
        values[f"membership_{suffix}"] = _insert_returning_id(
            connection,
            """
            INSERT INTO app.league_membership
                (account_id, league_id, participation_state, activated_at)
            VALUES (%s, %s, 'active', CURRENT_TIMESTAMP) RETURNING id
            """,
            (values[f"account_{suffix}"], values[f"league_{suffix}"]),
        )
        values[f"bucket_{suffix}"] = _insert_returning_id(
            connection,
            """
            INSERT INTO app.bucket (league_id, name, display_order)
            VALUES (%s, %s, 0) RETURNING id
            """,
            (values[f"league_{suffix}"], f"Bucket {suffix}"),
        )
        values[f"castaway_{suffix}"] = _insert_returning_id(
            connection,
            """
            INSERT INTO app.castaway (league_id, bucket_id, name)
            VALUES (%s, %s, %s) RETURNING id
            """,
            (values[f"league_{suffix}"], values[f"bucket_{suffix}"], f"Castaway {suffix}"),
        )
        values[f"action_{suffix}"] = _insert_returning_id(
            connection,
            """
            INSERT INTO app.scoring_action (league_id, name, points)
            VALUES (%s, %s, 1.5) RETURNING id
            """,
            (values[f"league_{suffix}"], f"Action {suffix}"),
        )
        connection.execute(
            """
            INSERT INTO app.betting_config
                (league_id, player_budget, castaway_cap, late_entry_budget, enabled)
            VALUES (%s, 10, 20, 5, true)
            """,
            (values[f"league_{suffix}"],),
        )
        values[f"wager_set_{suffix}"] = _insert_returning_id(
            connection,
            """
            INSERT INTO app.wager_set (league_id, sequence_number)
            VALUES (%s, 1) RETURNING id
            """,
            (values[f"league_{suffix}"],),
        )
        values[f"participation_{suffix}"] = _insert_returning_id(
            connection,
            """
            INSERT INTO app.betting_participation
                (league_id, membership_id, wager_set_id, budget, budget_source)
            VALUES (%s, %s, %s, 10, 'initial') RETURNING id
            """,
            (
                values[f"league_{suffix}"],
                values[f"membership_{suffix}"],
                values[f"wager_set_{suffix}"],
            ),
        )
    connection.commit()
    return values


def test_positive_constraints_accept_valid_domain_rows(
    migrated_database: psycopg.Connection[tuple[object, ...]],
) -> None:
    values = _seed_two_leagues(migrated_database)

    migrated_database.execute(
        """
        INSERT INTO app.roster_pick
            (league_id, membership_id, bucket_id, castaway_id)
        VALUES (%s, %s, %s, %s)
        """,
        (
            values["league_one"],
            values["membership_one"],
            values["bucket_one"],
            values["castaway_one"],
        ),
    )
    migrated_database.execute(
        """
        INSERT INTO app.scoring_event (league_id, action_id, castaway_id, episode)
        VALUES (%s, %s, %s, 1)
        """,
        (values["league_one"], values["action_one"], values["castaway_one"]),
    )
    migrated_database.execute(
        """
        INSERT INTO app.wager (league_id, participation_id, castaway_id, amount)
        VALUES (%s, %s, %s, 10)
        """,
        (values["league_one"], values["participation_one"], values["castaway_one"]),
    )
    migrated_database.execute(
        "INSERT INTO app.scoring_action (league_id, name, points) VALUES (%s, 'Penalty', -0.5)",
        (values["league_one"],),
    )

    migrated_database.commit()


def test_runtime_login_has_effective_least_privilege_access(
    migrated_database: psycopg.Connection[tuple[object, ...]], runtime_database_url: URL
) -> None:
    values = _seed_two_leagues(migrated_database)
    migrated_database.execute("CREATE TABLE app.runtime_permission_probe (id integer)")
    migrated_database.commit()

    with psycopg.connect(_psycopg_url(runtime_database_url)) as runtime:
        assert runtime.execute("SELECT session_user, current_user").fetchone() == (
            "survivor_fantasy_runtime",
            "survivor_fantasy_runtime",
        )
        runtime.execute("RESET ROLE")
        assert runtime.execute("SELECT current_user").fetchone() == (
            "survivor_fantasy_runtime",
        )
        assert runtime.execute("SELECT count(*) FROM app.league").fetchone() == (2,)
        runtime.execute(
            "UPDATE app.account SET display_name = 'Runtime update' WHERE id = %s",
            (values["account_one"],),
        )
        audit_id = _insert_returning_id(
            runtime,
            """
            INSERT INTO app.audit_event
                (actor_account_id, league_id, correlation_id, event_type)
            VALUES (%s, %s, %s, 'runtime_test')
            RETURNING id
            """,
            (values["account_one"], values["league_one"], uuid4()),
        )
        runtime.commit()

        denied_statements: tuple[tuple[str, tuple[object, ...]], ...] = (
            ("UPDATE app.audit_event SET reason = 'tampered' WHERE id = %s", (audit_id,)),
            ("DELETE FROM app.audit_event WHERE id = %s", (audit_id,)),
            ("DELETE FROM app.account WHERE id = %s", (values["account_one"],)),
            ("ALTER TABLE app.account ADD COLUMN escaped boolean", ()),
            ("SELECT * FROM app.runtime_permission_probe", ()),
            ("CREATE TABLE public.runtime_escape (id integer)", ()),
            ("CREATE SCHEMA runtime_escape", ()),
            ("ALTER SCHEMA app RENAME TO runtime_escape", ()),
            ("CREATE ROLE runtime_escape", ()),
            ("ALTER ROLE survivor_fantasy_runtime CREATEROLE", ()),
        )
        for statement, parameters in denied_statements:
            with pytest.raises(psycopg.errors.InsufficientPrivilege), runtime.transaction():
                runtime.execute(statement, parameters)

        runtime.execute(
            """
            INSERT INTO app.system_role (account_id, is_system_owner, initial_league_id)
            VALUES (%s, true, %s)
            """,
            (values["account_one"], values["league_one"]),
        )
        runtime.commit()
        with pytest.raises(psycopg.errors.InsufficientPrivilege), runtime.transaction():
            runtime.execute(
                "UPDATE app.system_role SET is_system_owner = true WHERE account_id = %s",
                (values["account_one"],),
            )


def test_migration_rejects_a_preexisting_privileged_runtime_role(empty_database: URL) -> None:
    with psycopg.connect(_psycopg_url(empty_database), autocommit=True) as connection:
        connection.execute(
            """
            DO $role$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_roles WHERE rolname = 'survivor_fantasy_runtime'
                ) THEN
                    CREATE ROLE survivor_fantasy_runtime LOGIN;
                END IF;
            END
            $role$;
            """
        )
        connection.execute("ALTER ROLE survivor_fantasy_runtime CREATEROLE")

    try:
        with pytest.raises(DBAPIError, match="privileged attributes"):
            command.upgrade(_alembic_config(empty_database), "head")
    finally:
        with psycopg.connect(_psycopg_url(empty_database), autocommit=True) as connection:
            connection.execute(
                """
                ALTER ROLE survivor_fantasy_runtime
                    NOCREATEROLE NOSUPERUSER NOCREATEDB NOREPLICATION NOBYPASSRLS NOINHERIT LOGIN
                """
            )


def test_migration_revokes_a_preexisting_direct_public_create_grant(empty_database: URL) -> None:
    runtime_password = f"runtime-{uuid4().hex}"
    with psycopg.connect(_psycopg_url(empty_database), autocommit=True) as connection:
        connection.execute(
            """
            DO $role$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_roles WHERE rolname = 'survivor_fantasy_runtime'
                ) THEN
                    CREATE ROLE survivor_fantasy_runtime LOGIN;
                END IF;
            END
            $role$;
            """
        )
        connection.execute(
            psycopg.sql.SQL("ALTER ROLE survivor_fantasy_runtime PASSWORD {}").format(
                psycopg.sql.Literal(runtime_password)
            )
        )
        connection.execute("GRANT CREATE ON SCHEMA public TO survivor_fantasy_runtime")

    command.upgrade(_alembic_config(empty_database), "head")

    with psycopg.connect(_psycopg_url(empty_database)) as connection:
        assert connection.execute(
            "SELECT has_schema_privilege('survivor_fantasy_runtime', 'public', 'CREATE')"
        ).fetchone() == (False,)

    runtime_url = empty_database.set(username="survivor_fantasy_runtime", password=runtime_password)
    with pytest.raises(psycopg.OperationalError):
        psycopg.connect(_psycopg_url(runtime_url), connect_timeout=2)

    live_password = f"runtime-live-{uuid4().hex}"
    with psycopg.connect(_psycopg_url(empty_database), autocommit=True) as connection:
        connection.execute(
            psycopg.sql.SQL("ALTER ROLE survivor_fantasy_runtime PASSWORD {}").format(
                psycopg.sql.Literal(live_password)
            )
        )

    live_runtime_url = empty_database.set(
        username="survivor_fantasy_runtime", password=live_password
    )
    with (
        psycopg.connect(_psycopg_url(live_runtime_url)) as runtime_connection,
        pytest.raises(psycopg.errors.InsufficientPrivilege),
    ):
        runtime_connection.execute(
            "CREATE TABLE public.runtime_direct_grant_escape (id integer)"
        )


def test_migration_rejects_a_runtime_role_that_owns_public_schema(empty_database: URL) -> None:
    with psycopg.connect(_psycopg_url(empty_database), autocommit=True) as connection:
        original_owner = connection.execute(
            "SELECT nspowner::regrole::text FROM pg_namespace WHERE nspname = 'public'"
        ).fetchone()
        assert original_owner is not None
        connection.execute(
            """
            DO $role$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_roles WHERE rolname = 'survivor_fantasy_runtime'
                ) THEN
                    CREATE ROLE survivor_fantasy_runtime LOGIN;
                END IF;
            END
            $role$;
            """
        )
        connection.execute("ALTER SCHEMA public OWNER TO survivor_fantasy_runtime")

    try:
        with pytest.raises(DBAPIError, match="owns a non-system schema"):
            command.upgrade(_alembic_config(empty_database), "head")
    finally:
        with psycopg.connect(_psycopg_url(empty_database), autocommit=True) as connection:
            connection.execute(
                psycopg.sql.SQL("ALTER SCHEMA public OWNER TO {}").format(
                    psycopg.sql.Identifier(cast(str, original_owner[0]))
                )
            )


def test_migration_rejects_a_runtime_role_that_owns_the_current_database(
    empty_database: URL,
) -> None:
    database_name = empty_database.database
    assert database_name is not None
    with psycopg.connect(_psycopg_url(empty_database), autocommit=True) as connection:
        original_owner = connection.execute(
            "SELECT datdba::regrole::text FROM pg_database WHERE datname = current_database()"
        ).fetchone()
        assert original_owner is not None
        connection.execute(
            """
            DO $role$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_roles WHERE rolname = 'survivor_fantasy_runtime'
                ) THEN
                    CREATE ROLE survivor_fantasy_runtime LOGIN;
                END IF;
            END
            $role$;
            """
        )
        connection.execute(
            psycopg.sql.SQL("ALTER DATABASE {} OWNER TO survivor_fantasy_runtime").format(
                psycopg.sql.Identifier(database_name)
            )
        )

    try:
        with pytest.raises(DBAPIError, match="owns the current database"):
            command.upgrade(_alembic_config(empty_database), "head")
    finally:
        with psycopg.connect(_psycopg_url(empty_database), autocommit=True) as connection:
            connection.execute(
                psycopg.sql.SQL("ALTER DATABASE {} OWNER TO {}").format(
                    psycopg.sql.Identifier(database_name),
                    psycopg.sql.Identifier(cast(str, original_owner[0])),
                )
            )


@pytest.mark.parametrize("login_attribute", ["NOLOGIN", "LOGIN"])
def test_migration_clears_stale_password_for_accepted_preexisting_role(
    empty_database: URL, login_attribute: str
) -> None:
    stale_password = f"stale-{uuid4().hex}"
    with psycopg.connect(_psycopg_url(empty_database), autocommit=True) as connection:
        connection.execute(
            """
            DO $role$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_roles WHERE rolname = 'survivor_fantasy_runtime'
                ) THEN
                    CREATE ROLE survivor_fantasy_runtime NOLOGIN;
                END IF;
            END
            $role$;
            """
        )
        connection.execute(
            psycopg.sql.SQL(
                "ALTER ROLE survivor_fantasy_runtime {} PASSWORD {}"
            ).format(psycopg.sql.SQL(login_attribute), psycopg.sql.Literal(stale_password))
        )

    command.upgrade(_alembic_config(empty_database), "head")

    with psycopg.connect(_psycopg_url(empty_database)) as connection:
        assert connection.execute(
            """
            SELECT
                roles.rolcanlogin,
                roles.rolsuper,
                roles.rolcreatedb,
                roles.rolcreaterole,
                roles.rolbypassrls,
                auth.rolpassword
            FROM pg_roles AS roles
            JOIN pg_authid AS auth ON auth.oid = roles.oid
            WHERE roles.rolname = 'survivor_fantasy_runtime'
            """
        ).fetchone() == (True, False, False, False, False, None)

    if os.environ.get("TEST_DATABASE_AUTHENTICATION") == "password":
        stale_runtime_url = empty_database.set(
            username="survivor_fantasy_runtime", password=stale_password
        )
        with pytest.raises(psycopg.OperationalError):
            psycopg.connect(_psycopg_url(stale_runtime_url), connect_timeout=2)


def test_migration_rejects_runtime_membership_in_a_parent_role(empty_database: URL) -> None:
    parent_role = f"survivor_test_parent_{uuid4().hex}"
    with psycopg.connect(_psycopg_url(empty_database), autocommit=True) as connection:
        connection.execute(
            """
            DO $role$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_roles WHERE rolname = 'survivor_fantasy_runtime'
                ) THEN
                    CREATE ROLE survivor_fantasy_runtime LOGIN;
                END IF;
            END
            $role$;
            """
        )
        connection.execute(
            psycopg.sql.SQL("CREATE ROLE {}").format(psycopg.sql.Identifier(parent_role))
        )
        connection.execute(
            psycopg.sql.SQL("GRANT {} TO survivor_fantasy_runtime").format(
                psycopg.sql.Identifier(parent_role)
            )
        )

    try:
        with pytest.raises(DBAPIError, match="role memberships"):
            command.upgrade(_alembic_config(empty_database), "head")
    finally:
        with psycopg.connect(_psycopg_url(empty_database), autocommit=True) as connection:
            connection.execute(
                psycopg.sql.SQL("REVOKE {} FROM survivor_fantasy_runtime").format(
                    psycopg.sql.Identifier(parent_role)
                )
            )
            connection.execute(
                psycopg.sql.SQL("DROP ROLE {}").format(psycopg.sql.Identifier(parent_role))
            )


def test_migration_rejects_child_membership_in_the_runtime_role(empty_database: URL) -> None:
    child_role = f"survivor_test_child_{uuid4().hex}"
    with psycopg.connect(_psycopg_url(empty_database), autocommit=True) as connection:
        connection.execute(
            """
            DO $role$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_roles WHERE rolname = 'survivor_fantasy_runtime'
                ) THEN
                    CREATE ROLE survivor_fantasy_runtime LOGIN;
                END IF;
            END
            $role$;
            """
        )
        connection.execute(
            psycopg.sql.SQL("CREATE ROLE {} LOGIN").format(psycopg.sql.Identifier(child_role))
        )
        connection.execute(
            psycopg.sql.SQL("GRANT survivor_fantasy_runtime TO {}").format(
                psycopg.sql.Identifier(child_role)
            )
        )

    try:
        with pytest.raises(DBAPIError, match="role memberships"):
            command.upgrade(_alembic_config(empty_database), "head")
    finally:
        with psycopg.connect(_psycopg_url(empty_database), autocommit=True) as connection:
            connection.execute(
                psycopg.sql.SQL("REVOKE survivor_fantasy_runtime FROM {}").format(
                    psycopg.sql.Identifier(child_role)
                )
            )
            connection.execute(
                psycopg.sql.SQL("DROP ROLE {}").format(psycopg.sql.Identifier(child_role))
            )


@pytest.mark.parametrize(
    ("statement_factory", "parameter_keys"),
    [
        (
            lambda: """
                INSERT INTO app.castaway (league_id, bucket_id, name)
                VALUES (%s, %s, 'Cross-league castaway')
            """,
            ("league_one", "bucket_two"),
        ),
        (
            lambda: """
                INSERT INTO app.roster_pick
                    (league_id, membership_id, bucket_id, castaway_id)
                VALUES (%s, %s, %s, %s)
            """,
            ("league_one", "membership_one", "bucket_one", "castaway_two"),
        ),
        (
            lambda: """
                INSERT INTO app.roster_pick
                    (league_id, membership_id, bucket_id, castaway_id)
                VALUES (%s, %s, %s, %s)
            """,
            ("league_one", "membership_two", "bucket_one", "castaway_one"),
        ),
        (
            lambda: """
                INSERT INTO app.scoring_event (league_id, action_id, castaway_id, episode)
                VALUES (%s, %s, %s, 1)
            """,
            ("league_one", "action_one", "castaway_two"),
        ),
        (
            lambda: """
                INSERT INTO app.scoring_event (league_id, action_id, castaway_id, episode)
                VALUES (%s, %s, %s, 1)
            """,
            ("league_one", "action_two", "castaway_one"),
        ),
        (
            lambda: """
                INSERT INTO app.betting_participation
                    (league_id, membership_id, wager_set_id, budget, budget_source)
                VALUES (%s, %s, %s, 10, 'initial')
            """,
            ("league_one", "membership_one", "wager_set_two"),
        ),
        (
            lambda: """
                INSERT INTO app.betting_participation
                    (league_id, membership_id, wager_set_id, budget, budget_source)
                VALUES (%s, %s, %s, 10, 'initial')
            """,
            ("league_one", "membership_two", "wager_set_one"),
        ),
        (
            lambda: """
                INSERT INTO app.wager (league_id, participation_id, castaway_id, amount)
                VALUES (%s, %s, %s, 10)
            """,
            ("league_one", "participation_one", "castaway_two"),
        ),
        (
            lambda: """
                INSERT INTO app.wager (league_id, participation_id, castaway_id, amount)
                VALUES (%s, %s, %s, 10)
            """,
            ("league_one", "participation_two", "castaway_one"),
        ),
    ],
)
def test_cross_league_references_are_rejected(
    migrated_database: psycopg.Connection[tuple[object, ...]],
    statement_factory: Callable[[], str],
    parameter_keys: tuple[str, ...],
) -> None:
    values = _seed_two_leagues(migrated_database)

    with _expect_integrity_error(migrated_database):
        migrated_database.execute(
            statement_factory(), tuple(values[key] for key in parameter_keys)
        )


def test_scoring_points_require_half_point_increments(
    migrated_database: psycopg.Connection[tuple[object, ...]],
) -> None:
    values = _seed_two_leagues(migrated_database)

    with _expect_integrity_error(migrated_database):
        migrated_database.execute(
            "INSERT INTO app.scoring_action (league_id, name, points) VALUES (%s, 'Invalid', 1.3)",
            (values["league_one"],),
        )


def test_reset_from_wager_set_must_belong_to_same_league(
    migrated_database: psycopg.Connection[tuple[object, ...]],
) -> None:
    values = _seed_two_leagues(migrated_database)
    migrated_database.execute(
        """
        UPDATE app.wager_set
        SET locked = true, finalized_at = CURRENT_TIMESTAMP
        WHERE id = %s
        """,
        (values["wager_set_one"],),
    )
    migrated_database.commit()

    with _expect_integrity_error(migrated_database):
        migrated_database.execute(
            """
            INSERT INTO app.wager_set (league_id, sequence_number, reset_from_set_id)
            VALUES (%s, 2, %s)
            """,
            (values["league_one"], values["wager_set_two"]),
        )


def test_soft_delete_uniqueness_allows_reuse_but_rejects_two_active_rows(
    migrated_database: psycopg.Connection[tuple[object, ...]],
) -> None:
    values = _seed_two_leagues(migrated_database)
    original_account_id = values["account_one"]

    with _expect_integrity_error(migrated_database):
        migrated_database.execute(
            """
            INSERT INTO app.account (supabase_user_id, email, display_name)
            VALUES (%s, ' ONE@example.com ', 'Duplicate')
            """,
            (uuid4(),),
        )

    migrated_database.execute(
        "UPDATE app.account SET deleted_at = CURRENT_TIMESTAMP WHERE id = %s",
        (original_account_id,),
    )
    migrated_database.execute(
        """
        INSERT INTO app.account (supabase_user_id, email, display_name)
        VALUES (%s, ' ONE@example.com ', 'Replacement')
        """,
        (uuid4(),),
    )
    migrated_database.commit()


def test_every_active_record_unique_key_allows_reuse_only_after_soft_delete(
    migrated_database: psycopg.Connection[tuple[object, ...]],
) -> None:
    values = _seed_two_leagues(migrated_database)

    with _expect_integrity_error(migrated_database):
        migrated_database.execute(
            """
            INSERT INTO app.league_membership
                (account_id, league_id, participation_state, activated_at)
            VALUES (%s, %s, 'active', CURRENT_TIMESTAMP)
            """,
            (values["account_one"], values["league_one"]),
        )
    migrated_database.execute(
        "UPDATE app.league_membership SET deleted_at = CURRENT_TIMESTAMP WHERE id = %s",
        (values["membership_one"],),
    )
    replacement_membership = _insert_returning_id(
        migrated_database,
        """
        INSERT INTO app.league_membership
            (account_id, league_id, participation_state, activated_at)
        VALUES (%s, %s, 'active', CURRENT_TIMESTAMP) RETURNING id
        """,
        (values["account_one"], values["league_one"]),
    )

    roster_parameters = (
        values["league_one"],
        replacement_membership,
        values["bucket_one"],
        values["castaway_one"],
    )
    roster_id = _insert_returning_id(
        migrated_database,
        """
        INSERT INTO app.roster_pick (league_id, membership_id, bucket_id, castaway_id)
        VALUES (%s, %s, %s, %s) RETURNING id
        """,
        roster_parameters,
    )
    with _expect_integrity_error(migrated_database):
        migrated_database.execute(
            """
            INSERT INTO app.roster_pick (league_id, membership_id, bucket_id, castaway_id)
            VALUES (%s, %s, %s, %s)
            """,
            roster_parameters,
        )
    migrated_database.execute(
        "UPDATE app.roster_pick SET deleted_at = CURRENT_TIMESTAMP WHERE id = %s", (roster_id,)
    )
    _insert_returning_id(
        migrated_database,
        """
        INSERT INTO app.roster_pick (league_id, membership_id, bucket_id, castaway_id)
        VALUES (%s, %s, %s, %s) RETURNING id
        """,
        roster_parameters,
    )

    with _expect_integrity_error(migrated_database):
        migrated_database.execute(
            """
            INSERT INTO app.castaway (league_id, bucket_id, name)
            VALUES (%s, %s, ' CASTAWAY ONE ')
            """,
            (values["league_one"], values["bucket_one"]),
        )
    migrated_database.execute(
        "UPDATE app.castaway SET deleted_at = CURRENT_TIMESTAMP WHERE id = %s",
        (values["castaway_one"],),
    )
    replacement_castaway = _insert_returning_id(
        migrated_database,
        """
        INSERT INTO app.castaway (league_id, bucket_id, name, placement)
        VALUES (%s, %s, ' CASTAWAY ONE ', 1) RETURNING id
        """,
        (values["league_one"], values["bucket_one"]),
    )
    with _expect_integrity_error(migrated_database):
        migrated_database.execute(
            """
            INSERT INTO app.castaway (league_id, bucket_id, name, placement)
            VALUES (%s, %s, 'Different name', 1)
            """,
            (values["league_one"], values["bucket_one"]),
        )
    migrated_database.execute(
        "UPDATE app.castaway SET deleted_at = CURRENT_TIMESTAMP WHERE id = %s",
        (replacement_castaway,),
    )
    replacement_castaway = _insert_returning_id(
        migrated_database,
        """
        INSERT INTO app.castaway (league_id, bucket_id, name, placement)
        VALUES (%s, %s, 'Different name', 1) RETURNING id
        """,
        (values["league_one"], values["bucket_one"]),
    )

    with _expect_integrity_error(migrated_database):
        migrated_database.execute(
            """
            INSERT INTO app.scoring_action (league_id, name, points)
            VALUES (%s, ' ACTION ONE ', 0)
            """,
            (values["league_one"],),
        )
    migrated_database.execute(
        "UPDATE app.scoring_action SET deleted_at = CURRENT_TIMESTAMP WHERE id = %s",
        (values["action_one"],),
    )
    _insert_returning_id(
        migrated_database,
        """
        INSERT INTO app.scoring_action (league_id, name, points)
        VALUES (%s, ' ACTION ONE ', 0) RETURNING id
        """,
        (values["league_one"],),
    )

    participation_parameters = (
        values["league_one"],
        values["membership_one"],
        values["wager_set_one"],
    )
    with _expect_integrity_error(migrated_database):
        migrated_database.execute(
            """
            INSERT INTO app.betting_participation
                (league_id, membership_id, wager_set_id, budget, budget_source)
            VALUES (%s, %s, %s, 0, 'initial')
            """,
            participation_parameters,
        )
    migrated_database.execute(
        "UPDATE app.betting_participation SET deleted_at = CURRENT_TIMESTAMP WHERE id = %s",
        (values["participation_one"],),
    )
    replacement_participation = _insert_returning_id(
        migrated_database,
        """
        INSERT INTO app.betting_participation
            (league_id, membership_id, wager_set_id, budget, budget_source)
        VALUES (%s, %s, %s, 0, 'initial') RETURNING id
        """,
        participation_parameters,
    )

    wager_parameters = (values["league_one"], replacement_participation, replacement_castaway)
    wager_id = _insert_returning_id(
        migrated_database,
        """
        INSERT INTO app.wager (league_id, participation_id, castaway_id, amount)
        VALUES (%s, %s, %s, 0) RETURNING id
        """,
        wager_parameters,
    )
    with _expect_integrity_error(migrated_database):
        migrated_database.execute(
            """
            INSERT INTO app.wager (league_id, participation_id, castaway_id, amount)
            VALUES (%s, %s, %s, 0)
            """,
            wager_parameters,
        )
    migrated_database.execute(
        "UPDATE app.wager SET deleted_at = CURRENT_TIMESTAMP WHERE id = %s", (wager_id,)
    )
    _insert_returning_id(
        migrated_database,
        """
        INSERT INTO app.wager (league_id, participation_id, castaway_id, amount)
        VALUES (%s, %s, %s, 0) RETURNING id
        """,
        wager_parameters,
    )
    migrated_database.commit()


def test_nonnegative_values_accept_zero_and_reject_negative(
    migrated_database: psycopg.Connection[tuple[object, ...]],
) -> None:
    values = _seed_two_leagues(migrated_database)

    zero_updates = (
        "UPDATE app.bucket SET display_order = 0 WHERE id = %s",
        "UPDATE app.betting_config SET player_budget = 0 WHERE league_id = %s",
        "UPDATE app.betting_config SET castaway_cap = 0 WHERE league_id = %s",
        "UPDATE app.betting_config SET late_entry_budget = 0 WHERE league_id = %s",
        "UPDATE app.betting_participation SET budget = 0 WHERE id = %s",
    )
    update_ids = (
        values["bucket_one"],
        values["league_one"],
        values["league_one"],
        values["league_one"],
        values["participation_one"],
    )
    for statement, record_id in zip(zero_updates, update_ids, strict=True):
        migrated_database.execute(statement, (record_id,))
    migrated_database.execute(
        """
        INSERT INTO app.wager (league_id, participation_id, castaway_id, amount)
        VALUES (%s, %s, %s, 0)
        """,
        (values["league_one"], values["participation_one"], values["castaway_one"]),
    )
    dispatch_id = _insert_returning_id(
        migrated_database,
        """
        INSERT INTO app.notification_dispatch
            (league_id, account_id, notification_type, deduplication_key, retry_count)
        VALUES (%s, %s, 'existing_user_added', %s, 0) RETURNING id
        """,
        (values["league_one"], values["account_one"], uuid4().hex),
    )
    migrated_database.commit()

    negative_updates = (
        ("UPDATE app.bucket SET display_order = -1 WHERE id = %s", values["bucket_one"]),
        (
            "UPDATE app.betting_config SET player_budget = -1 WHERE league_id = %s",
            values["league_one"],
        ),
        (
            "UPDATE app.betting_config SET castaway_cap = -1 WHERE league_id = %s",
            values["league_one"],
        ),
        (
            "UPDATE app.betting_config SET late_entry_budget = -1 WHERE league_id = %s",
            values["league_one"],
        ),
        (
            "UPDATE app.betting_participation SET budget = -1 WHERE id = %s",
            values["participation_one"],
        ),
        (
            "UPDATE app.wager SET amount = -1 WHERE participation_id = %s",
            values["participation_one"],
        ),
        (
            "UPDATE app.notification_dispatch SET retry_count = -1 WHERE id = %s",
            dispatch_id,
        ),
    )
    for statement, record_id in negative_updates:
        with _expect_integrity_error(migrated_database):
            migrated_database.execute(statement, (record_id,))


def test_only_one_current_wager_set_per_league(
    migrated_database: psycopg.Connection[tuple[object, ...]],
) -> None:
    values = _seed_two_leagues(migrated_database)

    with _expect_integrity_error(migrated_database):
        migrated_database.execute(
            "INSERT INTO app.wager_set (league_id, sequence_number) VALUES (%s, 2)",
            (values["league_one"],),
        )

    migrated_database.execute(
        """
        UPDATE app.wager_set
        SET locked = true, finalized_at = CURRENT_TIMESTAMP
        WHERE id = %s
        """,
        (values["wager_set_one"],),
    )
    migrated_database.execute(
        """
        INSERT INTO app.wager_set (league_id, sequence_number, reset_from_set_id)
        VALUES (%s, 2, %s)
        """,
        (values["league_one"], values["wager_set_one"]),
    )
    migrated_database.commit()
