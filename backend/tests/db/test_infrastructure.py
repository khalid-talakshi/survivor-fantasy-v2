from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from threading import Barrier
from uuid import UUID

import psycopg
from psycopg.errors import SerializationFailure
from sqlalchemy.engine import URL

from backend.tests.db.conftest import SeededDomain, _psycopg_url


def test_seeded_domain_fixture_has_isolated_leagues_and_controlled_time(
    migrated_database: psycopg.Connection[tuple[object, ...]],
    seeded_domain: SeededDomain,
    frozen_time: datetime,
) -> None:
    memberships = migrated_database.execute(
        """
        SELECT league_id, count(*)
        FROM app.league_membership
        WHERE league_id IN (%s, %s)
        GROUP BY league_id
        ORDER BY league_id
        """,
        (seeded_domain.primary_league_id, seeded_domain.secondary_league_id),
    ).fetchall()
    bucket_leagues = migrated_database.execute(
        """
        SELECT bucket.league_id, castaway.league_id
        FROM app.bucket AS bucket
        JOIN app.castaway AS castaway ON castaway.bucket_id = bucket.id
        ORDER BY bucket.league_id
        """
    ).fetchall()
    occurred_at = migrated_database.execute(
        "SELECT occurred_at FROM app.audit_event WHERE id = %s",
        (seeded_domain.primary_audit_event_id,),
    ).fetchone()

    assert set(memberships) == {
        (seeded_domain.primary_league_id, 2),
        (seeded_domain.secondary_league_id, 1),
    }
    assert set(bucket_leagues) == {
        (seeded_domain.primary_league_id, seeded_domain.primary_league_id),
        (seeded_domain.secondary_league_id, seeded_domain.secondary_league_id),
    }
    assert occurred_at == (frozen_time,)


def _concurrent_version_update(database_url: URL, league_id: UUID, barrier: Barrier) -> bool:
    try:
        with psycopg.connect(_psycopg_url(database_url)) as connection:
            connection.execute("BEGIN ISOLATION LEVEL SERIALIZABLE")
            connection.execute("SELECT version FROM app.league WHERE id = %s", (league_id,))
            barrier.wait(timeout=5)
            connection.execute(
                "UPDATE app.league SET version = version + 1 WHERE id = %s", (league_id,)
            )
            connection.commit()
            return True
    except SerializationFailure:
        return False


def test_serializable_transactions_use_separate_connections_and_a_barrier(
    empty_database: URL, seeded_domain: SeededDomain
) -> None:
    barrier = Barrier(2)

    def update() -> bool:
        return _concurrent_version_update(empty_database, seeded_domain.primary_league_id, barrier)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(update) for _ in range(2)]
        results = [future.result() for future in futures]

    assert sorted(results) == [False, True]
