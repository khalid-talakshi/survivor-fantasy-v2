import os
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from psycopg import sql
from sqlalchemy.engine import URL, make_url

REPOSITORY_ROOT = Path(__file__).parents[3]
FROZEN_TIME = datetime(2026, 9, 16, 12, 0, tzinfo=UTC)


@dataclass(frozen=True)
class SeededDomain:
    """Stable identifiers for the standard two-league integration-test fixture."""

    commissioner_account_id: UUID
    player_account_id: UUID
    other_league_account_id: UUID
    primary_league_id: UUID
    secondary_league_id: UUID
    commissioner_membership_id: UUID
    player_membership_id: UUID
    secondary_membership_id: UUID
    primary_bucket_id: UUID
    secondary_bucket_id: UUID
    primary_castaway_id: UUID
    secondary_castaway_id: UUID
    primary_action_id: UUID
    primary_audit_event_id: UUID


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo[object]) -> Iterator[None]:
    """Make the test result available to fixtures during teardown."""
    outcome = yield
    setattr(item, f"rep_{call.when}", outcome.get_result())


def _admin_url() -> URL:
    value = os.environ.get("TEST_DATABASE_URL")
    if value is None:
        pytest.skip("TEST_DATABASE_URL is required for PostgreSQL integration tests")
    return make_url(value)


def _psycopg_url(url: URL) -> str:
    return url.set(drivername="postgresql").render_as_string(hide_password=False)


def _alembic_config(database_url: URL) -> Config:
    config = Config(REPOSITORY_ROOT / "alembic.ini")
    rendered_url = database_url.set(drivername="postgresql+psycopg").render_as_string(
        hide_password=False
    )
    config.attributes["migration_database_url"] = rendered_url
    config.set_main_option(
        "sqlalchemy.url",
        rendered_url.replace("%", "%%"),
    )
    return config


@pytest.fixture
def empty_database() -> Iterator[URL]:
    admin_url = _admin_url()
    database_name = f"survivor_fantasy_test_{uuid4().hex}"

    with psycopg.connect(_psycopg_url(admin_url), autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))

    database_url = admin_url.set(database=database_name)
    try:
        yield database_url
    finally:
        with psycopg.connect(_psycopg_url(admin_url), autocommit=True) as admin:
            admin.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(database_name))
            )


@pytest.fixture
def migrated_database(
    empty_database: URL, request: pytest.FixtureRequest
) -> Iterator[psycopg.Connection[tuple[object, ...]]]:
    command.upgrade(_alembic_config(empty_database), "head")
    with psycopg.connect(_psycopg_url(empty_database)) as connection:
        yield connection
        report = getattr(request.node, "rep_call", None)
        if report is not None and report.failed:
            connection.rollback()
            table_count = connection.execute(
                "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'app'"
            ).fetchone()
            migration_version = connection.execute(
                "SELECT version_num FROM alembic_version"
            ).fetchone()
            print(
                "PostgreSQL test diagnostics: "
                f"database={empty_database.database} app_tables={table_count} "
                f"migration={migration_version}"
            )


@pytest.fixture
def frozen_time() -> datetime:
    """A UTC instant tests can use instead of depending on the wall clock."""
    return FROZEN_TIME


@pytest.fixture
def seeded_domain(
    migrated_database: psycopg.Connection[tuple[object, ...]], frozen_time: datetime
) -> SeededDomain:
    """Create two isolated leagues with the common domain records needed by services."""
    commissioner_account_id = uuid4()
    player_account_id = uuid4()
    other_league_account_id = uuid4()
    primary_league_id = uuid4()
    secondary_league_id = uuid4()
    commissioner_membership_id = uuid4()
    player_membership_id = uuid4()
    secondary_membership_id = uuid4()
    primary_bucket_id = uuid4()
    secondary_bucket_id = uuid4()
    primary_castaway_id = uuid4()
    secondary_castaway_id = uuid4()
    primary_action_id = uuid4()
    primary_audit_event_id = uuid4()

    migrated_database.execute(
        """
        INSERT INTO app.account (id, supabase_user_id, email, display_name)
        VALUES
            (%s, %s, 'commissioner@example.com', 'Commissioner'),
            (%s, %s, 'player@example.com', 'Player'),
            (%s, %s, 'other@example.com', 'Other Player')
        """,
        (
            commissioner_account_id,
            uuid4(),
            player_account_id,
            uuid4(),
            other_league_account_id,
            uuid4(),
        ),
    )
    migrated_database.execute(
        """
        INSERT INTO app.league (id, name, season_name)
        VALUES
            (%s, 'Primary League', 'Survivor 50'),
            (%s, 'Secondary League', 'Survivor 49')
        """,
        (primary_league_id, secondary_league_id),
    )
    migrated_database.execute(
        """
        INSERT INTO app.league_membership
            (id, account_id, league_id, is_commissioner, participation_state, activated_at)
        VALUES
            (%s, %s, %s, true, 'active', %s),
            (%s, %s, %s, false, 'active', %s),
            (%s, %s, %s, false, 'active', %s)
        """,
        (
            commissioner_membership_id,
            commissioner_account_id,
            primary_league_id,
            frozen_time,
            player_membership_id,
            player_account_id,
            primary_league_id,
            frozen_time,
            secondary_membership_id,
            other_league_account_id,
            secondary_league_id,
            frozen_time,
        ),
    )
    migrated_database.execute(
        """
        INSERT INTO app.bucket (id, league_id, name, display_order)
        VALUES (%s, %s, 'Primary tribe', 0), (%s, %s, 'Secondary tribe', 0)
        """,
        (primary_bucket_id, primary_league_id, secondary_bucket_id, secondary_league_id),
    )
    migrated_database.execute(
        """
        INSERT INTO app.castaway (id, league_id, bucket_id, name)
        VALUES
            (%s, %s, %s, 'Primary castaway'),
            (%s, %s, %s, 'Secondary castaway')
        """,
        (
            primary_castaway_id,
            primary_league_id,
            primary_bucket_id,
            secondary_castaway_id,
            secondary_league_id,
            secondary_bucket_id,
        ),
    )
    migrated_database.execute(
        """
        INSERT INTO app.scoring_action (id, league_id, name, points)
        VALUES (%s, %s, 'Challenge win', 1.0)
        """,
        (primary_action_id, primary_league_id),
    )
    migrated_database.execute(
        """
        INSERT INTO app.audit_event
            (id, actor_account_id, league_id, event_type, occurred_at)
        VALUES (%s, %s, %s, 'fixture.seeded', %s)
        """,
        (primary_audit_event_id, commissioner_account_id, primary_league_id, frozen_time),
    )
    migrated_database.commit()
    return SeededDomain(
        commissioner_account_id=commissioner_account_id,
        player_account_id=player_account_id,
        other_league_account_id=other_league_account_id,
        primary_league_id=primary_league_id,
        secondary_league_id=secondary_league_id,
        commissioner_membership_id=commissioner_membership_id,
        player_membership_id=player_membership_id,
        secondary_membership_id=secondary_membership_id,
        primary_bucket_id=primary_bucket_id,
        secondary_bucket_id=secondary_bucket_id,
        primary_castaway_id=primary_castaway_id,
        secondary_castaway_id=secondary_castaway_id,
        primary_action_id=primary_action_id,
        primary_audit_event_id=primary_audit_event_id,
    )


@pytest.fixture
def runtime_database_url(
    migrated_database: psycopg.Connection[tuple[object, ...]], empty_database: URL
) -> URL:
    runtime_password = f"test-{uuid4().hex}"
    migrated_database.execute(
        sql.SQL("ALTER ROLE survivor_fantasy_runtime PASSWORD {}").format(
            sql.Literal(runtime_password)
        )
    )
    migrated_database.commit()
    return empty_database.set(
        username="survivor_fantasy_runtime",
        password=runtime_password,
    )
