from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Barrier
from uuid import UUID, uuid4

import psycopg
import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session

from backend.app.domains.bootstrap.service import (
    BootstrapConflictError,
    BootstrapRequest,
    BootstrapResult,
    BootstrapService,
)


def _request(subject: UUID | None = None) -> BootstrapRequest:
    return BootstrapRequest(
        supabase_user_id=subject or uuid4(),
        email=" Owner@Example.COM ",
        display_name="Owner",
        league_name="Survivor Pool",
        season_name="Season 49",
    )


def _provision(database_url: URL, request: BootstrapRequest):
    engine = create_engine(database_url.set(drivername="postgresql+psycopg"))
    try:
        with Session(engine) as session:
            return BootstrapService().provision(session, request)
    finally:
        engine.dispose()


def _recovery_audit(
    connection: psycopg.Connection[tuple[object, ...]], membership_id: UUID
) -> tuple[object, ...]:
    event = connection.execute(
        """
        SELECT actor_account_id, league_id, entity_type, entity_id, event_type,
               before_state, after_state, correlation_id
        FROM app.audit_event
        WHERE entity_type = 'league_membership' AND entity_id = %s
        """,
        (membership_id,),
    ).fetchall()
    assert len(event) == 1
    return event[0]


def test_bootstrap_creates_initial_owner_league_and_pending_commissioner_membership(
    migrated_database: psycopg.Connection[tuple[object, ...]], empty_database: URL
) -> None:
    request = _request()
    result = _provision(empty_database, request)

    account = migrated_database.execute(
        "SELECT supabase_user_id, email, display_name FROM app.account WHERE id = %s",
        (result.account_id,),
    ).fetchone()
    role = migrated_database.execute(
        "SELECT account_id FROM app.system_role"
    ).fetchone()
    league = migrated_database.execute(
        "SELECT name, season_name, state FROM app.league WHERE id = %s", (result.league_id,)
    ).fetchone()
    membership = migrated_database.execute(
        """
        SELECT account_id, league_id, is_commissioner, participation_state
        FROM app.league_membership WHERE id = %s
        """,
        (result.membership_id,),
    ).fetchone()

    assert account == (request.supabase_user_id, "owner@example.com", "Owner")
    assert role == (result.account_id,)
    assert migrated_database.execute(
        "SELECT account_id, league_id FROM app.system_owner_initial_league"
    ).fetchone() == (result.account_id, result.league_id)
    assert league == ("Survivor Pool", "Season 49", "active")
    assert membership == (result.account_id, result.league_id, True, "pending_roster")


def test_bootstrap_first_run_works_with_restricted_runtime_role(
    migrated_database: psycopg.Connection[tuple[object, ...]], runtime_database_url: URL
) -> None:
    request = _request()
    result = _provision(runtime_database_url, request)
    repeated = _provision(runtime_database_url, request)

    assert repeated == result
    assert migrated_database.execute("SELECT count(*) FROM app.account").fetchone() == (1,)
    assert migrated_database.execute(
        "SELECT account_id FROM app.system_role"
    ).fetchone() == (result.account_id,)
    assert migrated_database.execute("SELECT id FROM app.league").fetchone() == (result.league_id,)
    assert migrated_database.execute(
        "SELECT id FROM app.league_membership"
    ).fetchone() == (result.membership_id,)
    assert migrated_database.execute(
        "SELECT account_id, league_id FROM app.system_owner_initial_league"
    ).fetchone() == (result.account_id, result.league_id)


def test_bootstrap_is_idempotent_and_recovers_missing_role_league_and_membership(
    migrated_database: psycopg.Connection[tuple[object, ...]], empty_database: URL
) -> None:
    request = _request()
    account_id = uuid4()
    migrated_database.execute(
        """
        INSERT INTO app.account (id, supabase_user_id, email, display_name)
        VALUES (%s, %s, %s, %s)
        """,
        (account_id, request.supabase_user_id, "owner@example.com", request.display_name),
    )
    migrated_database.commit()

    first = _provision(empty_database, request)
    second = _provision(empty_database, request)

    assert first == second
    assert first.account_id == account_id
    assert migrated_database.execute("SELECT count(*) FROM app.account").fetchone() == (1,)
    assert migrated_database.execute("SELECT count(*) FROM app.system_role").fetchone() == (1,)
    assert migrated_database.execute("SELECT count(*) FROM app.league").fetchone() == (1,)
    assert (
        migrated_database.execute("SELECT count(*) FROM app.league_membership").fetchone()
        == (1,)
    )


def test_bootstrap_recovers_existing_owner_role_without_initial_league(
    migrated_database: psycopg.Connection[tuple[object, ...]], empty_database: URL
) -> None:
    request = _request()
    account_id = uuid4()
    migrated_database.execute(
        """
        INSERT INTO app.account (id, supabase_user_id, email, display_name)
        VALUES (%s, %s, %s, %s)
        """,
        (account_id, request.supabase_user_id, "owner@example.com", request.display_name),
    )
    migrated_database.execute(
        "INSERT INTO app.system_role (account_id, is_system_owner) VALUES (%s, true)",
        (account_id,),
    )
    migrated_database.commit()

    result = _provision(empty_database, request)

    assert result.account_id == account_id
    assert migrated_database.execute(
        "SELECT account_id, league_id FROM app.system_owner_initial_league"
    ).fetchone() == (account_id, result.league_id)


def test_bootstrap_ignores_soft_deleted_email_history(
    migrated_database: psycopg.Connection[tuple[object, ...]], empty_database: URL
) -> None:
    request = _request()
    migrated_database.execute(
        """
        INSERT INTO app.account (supabase_user_id, email, display_name, deleted_at)
        VALUES (%s, %s, %s, CURRENT_TIMESTAMP)
        """,
        (uuid4(), "owner@example.com", "Former Owner"),
    )
    migrated_database.commit()

    result = _provision(empty_database, request)

    assert migrated_database.execute("SELECT count(*) FROM app.account").fetchone() == (2,)
    assert migrated_database.execute(
        "SELECT supabase_user_id, deleted_at FROM app.account WHERE id = %s",
        (result.account_id,),
    ).fetchone() == (request.supabase_user_id, None)


def test_bootstrap_rejects_second_existing_league_for_same_owner(
    migrated_database: psycopg.Connection[tuple[object, ...]], empty_database: URL
) -> None:
    request = _request()
    initial = _provision(empty_database, request)
    second_league_id = uuid4()
    migrated_database.execute(
        "INSERT INTO app.league (id, name, season_name) VALUES (%s, %s, %s)",
        (second_league_id, "Different League", "Season 50"),
    )
    migrated_database.commit()
    second_league = BootstrapRequest(
        supabase_user_id=request.supabase_user_id,
        email=request.email,
        display_name=request.display_name,
        league_name="Different League",
        season_name="Season 50",
    )

    with pytest.raises(BootstrapConflictError, match="initial league does not match"):
        _provision(empty_database, second_league)

    assert migrated_database.execute("SELECT count(*) FROM app.account").fetchone() == (1,)
    assert migrated_database.execute(
        "SELECT account_id FROM app.system_role"
    ).fetchone() == (initial.account_id,)
    assert migrated_database.execute("SELECT count(*) FROM app.league").fetchone() == (2,)
    assert migrated_database.execute(
        "SELECT count(*) FROM app.league_membership WHERE league_id = %s", (second_league_id,)
    ).fetchone() == (0,)
    assert migrated_database.execute(
        "SELECT id FROM app.league_membership"
    ).fetchone() == (initial.membership_id,)


def test_bootstrap_recovers_an_exact_completed_initial_league(
    migrated_database: psycopg.Connection[tuple[object, ...]], empty_database: URL
) -> None:
    request = _request()
    initial = _provision(empty_database, request)
    migrated_database.execute(
        "UPDATE app.league SET state = 'completed' WHERE id = %s", (initial.league_id,)
    )
    migrated_database.execute(
        "UPDATE app.league_membership SET is_commissioner = false WHERE id = %s",
        (initial.membership_id,),
    )
    migrated_database.commit()

    restored = _provision(empty_database, request)

    assert restored == initial
    assert migrated_database.execute(
        "SELECT state FROM app.league WHERE id = %s", (initial.league_id,)
    ).fetchone() == ("completed",)
    assert migrated_database.execute(
        "SELECT is_commissioner FROM app.league_membership WHERE id = %s",
        (initial.membership_id,),
    ).fetchone() == (True,)


def test_bootstrap_binds_markerless_existing_owner_to_completed_league(
    migrated_database: psycopg.Connection[tuple[object, ...]], empty_database: URL
) -> None:
    request = _request()
    account_id, league_id = uuid4(), uuid4()
    migrated_database.execute(
        """
        INSERT INTO app.account (id, supabase_user_id, email, display_name)
        VALUES (%s, %s, %s, %s)
        """,
        (account_id, request.supabase_user_id, "owner@example.com", request.display_name),
    )
    migrated_database.execute(
        """
        INSERT INTO app.league (id, name, season_name, state)
        VALUES (%s, %s, %s, 'completed')
        """,
        (league_id, request.league_name, request.season_name),
    )
    migrated_database.execute(
        "INSERT INTO app.system_role (account_id, is_system_owner) VALUES (%s, true)",
        (account_id,),
    )
    migrated_database.commit()

    result = _provision(empty_database, request)

    assert result.account_id == account_id
    assert result.league_id == league_id
    assert migrated_database.execute(
        "SELECT account_id, league_id FROM app.system_owner_initial_league"
    ).fetchone() == (account_id, league_id)
    assert migrated_database.execute(
        "SELECT is_commissioner FROM app.league_membership WHERE id = %s",
        (result.membership_id,),
    ).fetchone() == (True,)
    audit = _recovery_audit(migrated_database, result.membership_id)
    assert audit[5] == {"deleted_at": None, "is_commissioner": None}
    assert audit[6] == {"deleted_at": None, "is_commissioner": True}


def test_bootstrap_recovers_completed_league_when_owner_role_is_missing(
    migrated_database: psycopg.Connection[tuple[object, ...]], empty_database: URL
) -> None:
    request = _request()
    account_id, league_id, membership_id = uuid4(), uuid4(), uuid4()
    migrated_database.execute(
        """
        INSERT INTO app.account (id, supabase_user_id, email, display_name)
        VALUES (%s, %s, %s, %s)
        """,
        (account_id, request.supabase_user_id, "owner@example.com", request.display_name),
    )
    migrated_database.execute(
        """
        INSERT INTO app.league (id, name, season_name, state)
        VALUES (%s, %s, %s, 'completed')
        """,
        (league_id, request.league_name, request.season_name),
    )
    migrated_database.execute(
        """
        INSERT INTO app.league_membership (id, account_id, league_id, is_commissioner)
        VALUES (%s, %s, %s, false)
        """,
        (membership_id, account_id, league_id),
    )
    migrated_database.commit()

    result = _provision(empty_database, request)

    assert result == BootstrapResult(account_id, league_id, membership_id)
    assert migrated_database.execute(
        "SELECT account_id FROM app.system_role"
    ).fetchone() == (account_id,)
    assert _recovery_audit(migrated_database, membership_id)[4] == (
        "league_membership.commissioner_recovered"
    )


def test_bootstrap_rejects_completed_league_without_existing_owner_role(
    migrated_database: psycopg.Connection[tuple[object, ...]], empty_database: URL
) -> None:
    request = _request()
    league_id = uuid4()
    migrated_database.execute(
        """
        INSERT INTO app.league (id, name, season_name, state)
        VALUES (%s, %s, %s, 'completed')
        """,
        (league_id, request.league_name, request.season_name),
    )
    migrated_database.commit()

    with pytest.raises(BootstrapConflictError, match="not active"):
        _provision(empty_database, request)

    assert migrated_database.execute("SELECT count(*) FROM app.account").fetchone() == (0,)
    assert migrated_database.execute("SELECT count(*) FROM app.system_role").fetchone() == (0,)
    assert migrated_database.execute("SELECT count(*) FROM app.league_membership").fetchone() == (
        0,
    )


@pytest.mark.parametrize(
    ("is_commissioner", "deleted_at"),
    [(False, None), (False, datetime.now(UTC))],
    ids=["demoted", "soft_deleted"],
)
def test_bootstrap_recovers_markerless_completed_membership(
    migrated_database: psycopg.Connection[tuple[object, ...]],
    empty_database: URL,
    is_commissioner: bool,
    deleted_at: datetime | None,
) -> None:
    request = _request()
    account_id, league_id, membership_id = uuid4(), uuid4(), uuid4()
    migrated_database.execute(
        """
        INSERT INTO app.account (id, supabase_user_id, email, display_name)
        VALUES (%s, %s, %s, %s)
        """,
        (account_id, request.supabase_user_id, "owner@example.com", request.display_name),
    )
    migrated_database.execute(
        """
        INSERT INTO app.league (id, name, season_name, state)
        VALUES (%s, %s, %s, 'completed')
        """,
        (league_id, request.league_name, request.season_name),
    )
    migrated_database.execute(
        "INSERT INTO app.system_role (account_id, is_system_owner) VALUES (%s, true)",
        (account_id,),
    )
    migrated_database.execute(
        """
        INSERT INTO app.league_membership
            (id, account_id, league_id, is_commissioner, deleted_at)
        VALUES (%s, %s, %s, %s, %s)
        """,
        (membership_id, account_id, league_id, is_commissioner, deleted_at),
    )
    migrated_database.commit()

    result = _provision(empty_database, request)

    assert result.membership_id == membership_id
    assert _recovery_audit(migrated_database, membership_id)[4] == (
        "league_membership.commissioner_recovered"
    )


def test_bootstrap_recovers_membership_when_matching_owner_and_league_exist(
    migrated_database: psycopg.Connection[tuple[object, ...]], empty_database: URL
) -> None:
    request = _request()
    account_id, league_id = uuid4(), uuid4()
    migrated_database.execute(
        """
        INSERT INTO app.account (id, supabase_user_id, email, display_name)
        VALUES (%s, %s, %s, %s)
        """,
        (account_id, request.supabase_user_id, "owner@example.com", request.display_name),
    )
    migrated_database.execute(
        """
        INSERT INTO app.league (id, name, season_name)
        VALUES (%s, %s, %s)
        """,
        (league_id, request.league_name, request.season_name),
    )
    migrated_database.execute(
        """
        INSERT INTO app.system_role (account_id, is_system_owner)
        VALUES (%s, true)
        """,
        (account_id,),
    )
    migrated_database.commit()

    result = _provision(empty_database, request)

    assert result.account_id == account_id
    assert result.league_id == league_id
    assert migrated_database.execute("SELECT count(*) FROM app.account").fetchone() == (1,)
    assert migrated_database.execute("SELECT count(*) FROM app.system_role").fetchone() == (1,)
    assert migrated_database.execute("SELECT count(*) FROM app.league").fetchone() == (1,)
    assert (
        migrated_database.execute("SELECT count(*) FROM app.league_membership").fetchone()
        == (1,)
    )


def test_concurrent_identical_bootstrap_calls_create_one_aggregate(
    migrated_database: psycopg.Connection[tuple[object, ...]], empty_database: URL
) -> None:
    request = _request()
    start = Barrier(2)

    def provision() -> object:
        start.wait()
        return _provision(empty_database, request)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: provision(), range(2)))

    assert results[0] == results[1]
    assert migrated_database.execute("SELECT count(*) FROM app.account").fetchone() == (1,)
    assert migrated_database.execute("SELECT count(*) FROM app.system_role").fetchone() == (1,)
    assert migrated_database.execute("SELECT count(*) FROM app.league").fetchone() == (1,)
    assert (
        migrated_database.execute("SELECT count(*) FROM app.league_membership").fetchone()
        == (1,)
    )


def test_bootstrap_restores_a_demoted_matching_membership(
    migrated_database: psycopg.Connection[tuple[object, ...]], empty_database: URL
) -> None:
    request = _request()
    initial = _provision(empty_database, request)
    migrated_database.execute(
        "UPDATE app.league_membership SET is_commissioner = false WHERE id = %s",
        (initial.membership_id,),
    )
    migrated_database.commit()

    restored = _provision(empty_database, request)

    membership = migrated_database.execute(
        """
        SELECT id, is_commissioner, participation_state, deleted_at
        FROM app.league_membership WHERE id = %s
        """,
        (initial.membership_id,),
    ).fetchone()
    audit = _recovery_audit(migrated_database, initial.membership_id)
    assert restored.membership_id == initial.membership_id
    assert membership == (initial.membership_id, True, "pending_roster", None)
    assert audit[:5] == (
        initial.account_id,
        initial.league_id,
        "league_membership",
        initial.membership_id,
        "league_membership.commissioner_recovered",
    )
    assert audit[5] == {"deleted_at": None, "is_commissioner": False}
    assert audit[6] == {"deleted_at": None, "is_commissioner": True}
    assert audit[7] is not None


def test_bootstrap_restores_a_soft_deleted_matching_membership(
    migrated_database: psycopg.Connection[tuple[object, ...]], empty_database: URL
) -> None:
    request = _request()
    initial = _provision(empty_database, request)
    migrated_database.execute(
        """
        UPDATE app.league_membership
        SET is_commissioner = false, deleted_at = CURRENT_TIMESTAMP
        WHERE id = %s
        """,
        (initial.membership_id,),
    )
    migrated_database.commit()

    restored = _provision(empty_database, request)

    membership = migrated_database.execute(
        """
        SELECT id, is_commissioner, participation_state, deleted_at
        FROM app.league_membership WHERE id = %s
        """,
        (initial.membership_id,),
    ).fetchone()
    audit = _recovery_audit(migrated_database, initial.membership_id)
    assert restored.membership_id == initial.membership_id
    assert membership == (initial.membership_id, True, "pending_roster", None)
    assert audit[:5] == (
        initial.account_id,
        initial.league_id,
        "league_membership",
        initial.membership_id,
        "league_membership.commissioner_recovered",
    )
    assert audit[5]["is_commissioner"] is False
    assert isinstance(audit[5]["deleted_at"], str)
    assert audit[6] == {"deleted_at": None, "is_commissioner": True}
    assert audit[7] is not None


def test_bootstrap_prefers_active_membership_over_deleted_history(
    migrated_database: psycopg.Connection[tuple[object, ...]], empty_database: URL
) -> None:
    request = _request()
    initial = _provision(empty_database, request)
    migrated_database.execute(
        "UPDATE app.league_membership SET deleted_at = CURRENT_TIMESTAMP WHERE id = %s",
        (initial.membership_id,),
    )
    active_membership_id = uuid4()
    migrated_database.execute(
        """
        INSERT INTO app.league_membership
            (id, account_id, league_id, is_commissioner)
        VALUES (%s, %s, %s, true)
        """,
        (active_membership_id, initial.account_id, initial.league_id),
    )
    migrated_database.commit()

    restored = _provision(empty_database, request)

    assert restored.membership_id == active_membership_id
    assert migrated_database.execute(
        "SELECT count(*) FROM app.audit_event WHERE entity_type = 'league_membership'"
    ).fetchone() == (0,)


def test_conflict_rolls_back_all_new_bootstrap_records(
    migrated_database: psycopg.Connection[tuple[object, ...]], empty_database: URL
) -> None:
    conflicting_owner, unrelated_league_id = uuid4(), uuid4()
    migrated_database.execute(
        """
        INSERT INTO app.account (id, supabase_user_id, email, display_name)
        VALUES (%s, %s, %s, %s)
        """,
        (conflicting_owner, uuid4(), "other@example.com", "Other"),
    )
    migrated_database.execute(
        "INSERT INTO app.league (id, name, season_name) VALUES (%s, %s, %s)",
        (unrelated_league_id, "Existing league", "Season 1"),
    )
    migrated_database.execute(
        """
        INSERT INTO app.system_role (account_id, is_system_owner)
        VALUES (%s, true)
        """,
        (conflicting_owner,),
    )
    migrated_database.commit()

    with pytest.raises(BootstrapConflictError, match="different account"):
        _provision(empty_database, _request())

    assert migrated_database.execute("SELECT count(*) FROM app.account").fetchone() == (1,)
    assert migrated_database.execute("SELECT count(*) FROM app.league").fetchone() == (1,)
    assert (
        migrated_database.execute("SELECT count(*) FROM app.league_membership").fetchone()
        == (0,)
    )
