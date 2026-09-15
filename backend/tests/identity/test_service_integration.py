from uuid import UUID, uuid4

import psycopg
from sqlalchemy import create_engine
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session

from backend.app.domains.identity.auth import VerifiedIdentity
from backend.app.domains.identity.service import IdentityService


def _insert_projection_data(
    connection: psycopg.Connection[tuple[object, ...]],
) -> tuple[UUID, UUID]:
    account_id, subject = uuid4(), uuid4()
    other_account_id = uuid4()
    active_alpha, active_zulu, completed, deleted = (uuid4() for _ in range(4))

    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO app.account (id, supabase_user_id, email, display_name)
            VALUES (%s, %s, %s, %s), (%s, %s, %s, %s)
            """,
            (
                account_id,
                subject,
                "old@example.com",
                "Player",
                other_account_id,
                uuid4(),
                "other@example.com",
                "Other player",
            ),
        )
        cursor.execute(
            """
            INSERT INTO app.league (id, name, season_name, state, roster_locked, deleted_at)
            VALUES
                (%s, 'Zulu', '48', 'active', true, NULL),
                (%s, 'Alpha', '47', 'active', false, NULL),
                (%s, 'History', '46', 'completed', true, NULL),
                (%s, 'Deleted', '45', 'active', false, CURRENT_TIMESTAMP)
            """,
            (active_zulu, active_alpha, completed, deleted),
        )
        cursor.execute(
            """
            INSERT INTO app.system_role (account_id, is_system_owner)
            VALUES (%s, true)
            """,
            (account_id,),
        )
        cursor.execute(
            """
            INSERT INTO app.league_membership (
                account_id, league_id, is_commissioner, participation_state,
                activated_at, deleted_at
            )
            VALUES
                (%s, %s, true, 'active', CURRENT_TIMESTAMP, NULL),
                (%s, %s, false, 'pending_roster', NULL, NULL),
                (%s, %s, false, 'non_playing', NULL, NULL),
                (%s, %s, true, 'active', CURRENT_TIMESTAMP, NULL),
                (%s, %s, true, 'active', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
                (%s, %s, true, 'active', CURRENT_TIMESTAMP, NULL)
            """,
            (
                account_id,
                active_zulu,
                account_id,
                active_alpha,
                account_id,
                completed,
                account_id,
                deleted,
                account_id,
                active_alpha,
                other_account_id,
                active_zulu,
            ),
        )
    connection.commit()
    return account_id, subject


def test_session_projection_uses_only_active_authorized_records(
    migrated_database: psycopg.Connection[tuple[object, ...]], runtime_database_url: URL
) -> None:
    account_id, subject = _insert_projection_data(migrated_database)
    engine = create_engine(runtime_database_url.set(drivername="postgresql+psycopg"))
    try:
        with Session(engine) as session:
            result = IdentityService().resolve_session(
                session,
                VerifiedIdentity(subject, " Player@Example.COM "),
            )

        assert result.account.id == account_id
        assert result.account.email == "player@example.com"
        assert result.account.is_system_owner is True
        assert [(league.name, league.state) for league in result.leagues] == [
            ("Alpha", "active"),
            ("Zulu", "active"),
            ("History", "completed"),
        ]
        assert result.leagues[0].participation_state == "pending_roster"
        assert result.leagues[1].is_commissioner is True
        assert result.leagues[2].participation_state == "non_playing"

        stored_email = migrated_database.execute(
            "SELECT email FROM app.account WHERE id = %s", (account_id,)
        ).fetchone()
        assert stored_email == ("player@example.com",)
    finally:
        engine.dispose()
