from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session

from backend.app.api.identity import get_token_verifier
from backend.app.core.errors import NotFoundError
from backend.app.db.audit import AuditWriter
from backend.app.db.session import get_db
from backend.app.domains.identity.auth import VerifiedIdentity
from backend.app.domains.identity.service import CurrentAccount
from backend.app.domains.leagues.service import LeagueService
from backend.app.main import create_app


def test_selection_requires_membership_in_the_requested_league(
    migrated_database: psycopg.Connection[tuple[object, ...]], runtime_database_url: URL
) -> None:
    account_id = uuid4()
    member_league_id = uuid4()
    other_league_id = uuid4()
    with migrated_database.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO app.account (id, supabase_user_id, email, display_name)
            VALUES (%s, %s, 'member@example.com', 'Member')
            """,
            (account_id, uuid4()),
        )
        cursor.execute(
            """
            INSERT INTO app.league (id, name, season_name)
            VALUES (%s, 'Member league', '48'), (%s, 'Other league', '47')
            """,
            (member_league_id, other_league_id),
        )
        cursor.execute(
            """
            INSERT INTO app.league_membership (account_id, league_id, participation_state)
            VALUES (%s, %s, 'non_playing')
            """,
            (account_id, member_league_id),
        )
    migrated_database.commit()

    engine = create_engine(runtime_database_url.set(drivername="postgresql+psycopg"))
    try:
        with Session(engine) as session:
            selected = LeagueService().get_for_account(
                session, account_id=account_id, league_id=member_league_id
            )
            assert selected.id == member_league_id
            with pytest.raises(NotFoundError):
                LeagueService().get_for_account(
                    session, account_id=account_id, league_id=other_league_id
                )
    finally:
        engine.dispose()


def test_owner_can_create_a_league_after_authenticated_account_resolution(
    migrated_database: psycopg.Connection[tuple[object, ...]], runtime_database_url: URL
) -> None:
    account_id, subject = uuid4(), uuid4()
    migrated_database.execute(
        """
        INSERT INTO app.account (id, supabase_user_id, email, display_name)
        VALUES (%s, %s, 'owner@example.com', 'Owner')
        """,
        (account_id, subject),
    )
    migrated_database.execute(
        "INSERT INTO app.system_role (account_id, is_system_owner) VALUES (%s, true)",
        (account_id,),
    )
    migrated_database.commit()

    class Verifier:
        def verify(self, _: str) -> VerifiedIdentity:
            return VerifiedIdentity(subject, "owner@example.com")

    engine = create_engine(runtime_database_url.set(drivername="postgresql+psycopg"))

    def database_session():
        with Session(engine) as session:
            yield session

    application = create_app()
    application.dependency_overrides[get_token_verifier] = lambda: Verifier()
    application.dependency_overrides[get_db] = database_session
    try:
        response = TestClient(application).post(
            "/api/v1/leagues",
            headers={"Authorization": "Bearer valid"},
            json={"name": "New league", "season_name": "49"},
        )
        assert response.status_code == 201
        assert response.json()["participation_state"] == "non_playing"
        league_id = response.json()["id"]
        league = migrated_database.execute(
            "SELECT state, roster_locked FROM app.league WHERE id = %s", (league_id,)
        ).fetchone()
        membership = migrated_database.execute(
            """
            SELECT is_commissioner, participation_state
            FROM app.league_membership WHERE account_id = %s AND league_id = %s
            """,
            (account_id, league_id),
        ).fetchone()
        audit = migrated_database.execute(
            """
            SELECT actor_account_id, league_id, event_type, entity_type, entity_id
            FROM app.audit_event WHERE league_id = %s
            """,
            (league_id,),
        ).fetchone()
        assert league == ("active", False)
        assert membership == (True, "non_playing")
        assert audit == (account_id, league_id, "league.created", "league", league_id)
    finally:
        engine.dispose()


def test_create_rolls_back_when_audit_write_fails(
    migrated_database: psycopg.Connection[tuple[object, ...]],
    runtime_database_url: URL,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    account_id = uuid4()
    migrated_database.execute(
        """
        INSERT INTO app.account (id, supabase_user_id, email, display_name)
        VALUES (%s, %s, 'owner@example.com', 'Owner')
        """,
        (account_id, uuid4()),
    )
    migrated_database.execute(
        "INSERT INTO app.system_role (account_id, is_system_owner) VALUES (%s, true)",
        (account_id,),
    )
    migrated_database.commit()
    engine = create_engine(runtime_database_url.set(drivername="postgresql+psycopg"))

    def audit_failure(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr(AuditWriter, "write", audit_failure)
    try:
        with Session(engine) as session, pytest.raises(RuntimeError, match="audit unavailable"):
            LeagueService().create(
                session,
                CurrentAccount(account_id, "owner@example.com", "Owner", True),
                name="New league",
                season_name="49",
            )
        league_count = migrated_database.execute(
            "SELECT count(*) FROM app.league WHERE season_name = '49'"
        ).fetchone()
        assert league_count == (0,)
    finally:
        engine.dispose()
