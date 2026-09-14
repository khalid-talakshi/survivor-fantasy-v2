import os
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from psycopg import sql
from sqlalchemy.engine import URL, make_url

REPOSITORY_ROOT = Path(__file__).parents[3]


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
def migrated_database(empty_database: URL) -> Iterator[psycopg.Connection[tuple[object, ...]]]:
    command.upgrade(_alembic_config(empty_database), "head")
    with psycopg.connect(_psycopg_url(empty_database)) as connection:
        yield connection


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
