from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from backend.app.domains.identity.auth import AuthenticationError, VerifiedIdentity
from backend.app.domains.identity.service import IdentityService


class Result:
    def __init__(
        self, row: dict[str, Any] | None = None, rows: list[dict[str, Any]] | None = None
    ) -> None:
        self.row = row
        self.rows = rows or []

    def mappings(self) -> Result:
        return self

    def one_or_none(self) -> dict[str, Any] | None:
        return self.row

    def all(self) -> list[dict[str, Any]]:
        return self.rows


class Session:
    def __init__(self, account: dict[str, Any] | None, leagues: list[dict[str, Any]]) -> None:
        self.account = account
        self.leagues = leagues
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.commits = 0

    def execute(self, statement: Any, params: dict[str, Any]) -> Result:
        self.calls.append((statement.text, params))
        if "FROM app.account" in statement.text:
            return Result(row=self.account)
        if "FROM app.league_membership" in statement.text:
            return Result(rows=self.leagues)
        return Result()

    def commit(self) -> None:
        self.commits += 1


def test_resolves_only_active_memberships_and_refreshes_email() -> None:
    account_id, subject, league_id = uuid4(), uuid4(), uuid4()
    db = Session(
        {
            "id": account_id,
            "email": "old@example.com",
            "display_name": "Player",
            "is_system_owner": False,
        },
        [
            {
                "id": league_id,
                "name": "Active league",
                "season_name": "48",
                "state": "active",
                "roster_locked": True,
                "is_commissioner": True,
                "participation_state": "active",
                "read_only": False,
            }
        ],
    )

    result = IdentityService().resolve_session(
        db, VerifiedIdentity(supabase_user_id=subject, email=" User@Example.COM ")
    )

    assert result.account.email == "user@example.com"
    assert result.leagues[0].id == league_id
    assert db.commits == 1
    assert any("membership.deleted_at IS NULL" in call[0] for call in db.calls)
    assert any("league.deleted_at IS NULL" in call[0] for call in db.calls)
    assert any("CASE league.state" in call[0] for call in db.calls)


def test_unchanged_email_does_not_commit_and_missing_account_is_denied() -> None:
    subject = uuid4()
    unchanged = Session(
        {
            "id": uuid4(),
            "email": "user@example.com",
            "display_name": "Player",
            "is_system_owner": False,
        },
        [],
    )
    result = IdentityService().resolve_session(
        unchanged, VerifiedIdentity(supabase_user_id=subject, email="USER@example.com")
    )
    assert result.leagues == []
    assert unchanged.commits == 0

    with pytest.raises(AuthenticationError):
        IdentityService().resolve_session(
            Session(None, []), VerifiedIdentity(subject, "user@example.com")
        )
