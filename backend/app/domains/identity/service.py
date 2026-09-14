from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.app.domains.identity.auth import AuthenticationError, VerifiedIdentity


@dataclass(frozen=True)
class CurrentAccount:
    id: UUID
    email: str
    display_name: str
    is_system_owner: bool


@dataclass(frozen=True)
class LeagueSummary:
    id: UUID
    name: str
    season_name: str
    state: str
    roster_locked: bool
    is_commissioner: bool
    participation_state: str


@dataclass(frozen=True)
class SessionProjection:
    account: CurrentAccount
    leagues: list[LeagueSummary]


def normalize_email(email: str) -> str:
    return email.strip().lower()


class IdentityService:
    def resolve_session(self, db: Session, identity: VerifiedIdentity) -> SessionProjection:
        row = db.execute(
            text(
                """
                SELECT account.id, account.email, account.display_name,
                       COALESCE(system_role.is_system_owner, false) AS is_system_owner
                FROM app.account AS account
                LEFT JOIN app.system_role AS system_role ON system_role.account_id = account.id
                WHERE account.supabase_user_id = :supabase_user_id
                  AND account.deleted_at IS NULL
                """
            ),
            {"supabase_user_id": identity.supabase_user_id},
        ).mappings().one_or_none()
        if row is None:
            raise AuthenticationError

        email = normalize_email(identity.email)
        if row["email"] != email:
            db.execute(
                text("UPDATE app.account SET email = :email WHERE id = :account_id"),
                {"email": email, "account_id": row["id"]},
            )
            db.commit()

        account = CurrentAccount(
            id=row["id"],
            email=email,
            display_name=row["display_name"],
            is_system_owner=row["is_system_owner"],
        )
        leagues = [
            LeagueSummary(**league)
            for league in db.execute(
                text(
                    """
                    SELECT league.id, league.name, league.season_name, league.state,
                           league.roster_locked, membership.is_commissioner,
                           membership.participation_state
                    FROM app.league_membership AS membership
                    JOIN app.league AS league ON league.id = membership.league_id
                    WHERE membership.account_id = :account_id
                      AND membership.deleted_at IS NULL
                      AND league.deleted_at IS NULL
                    ORDER BY CASE league.state WHEN 'active' THEN 0 ELSE 1 END,
                             lower(league.name), league.id
                    """
                ),
                {"account_id": account.id},
            ).mappings().all()
        ]
        return SessionProjection(account=account, leagues=leagues)
