"""Idempotent provisioning of the initial system owner and league."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.app.db.audit import AuditWriter
from backend.app.db.transactions import domain_transaction
from backend.app.domains.identity.service import normalize_email

BOOTSTRAP_ADVISORY_LOCK_KEY = 578198482


class BootstrapConflictError(ValueError):
    """Raised when existing state cannot safely be recovered by bootstrap."""


@dataclass(frozen=True)
class BootstrapRequest:
    supabase_user_id: UUID
    email: str
    display_name: str
    league_name: str
    season_name: str

    def normalized(self) -> BootstrapRequest:
        return BootstrapRequest(
            supabase_user_id=self.supabase_user_id,
            email=normalize_email(_required_text(self.email, "email")),
            display_name=_required_text(self.display_name, "display name"),
            league_name=_required_text(self.league_name, "league name"),
            season_name=_required_text(self.season_name, "season name"),
        )


@dataclass(frozen=True)
class BootstrapResult:
    account_id: UUID
    league_id: UUID
    membership_id: UUID


@dataclass(frozen=True)
class SystemOwnerState:
    role_exists: bool
    initial_league_id: UUID | None


def _required_text(value: str, name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{name} must not be blank")
    return normalized


class AccountProvisioner:
    """Create or verify the local projection of an external identity."""

    def ensure(self, db: Session, request: BootstrapRequest) -> UUID:
        rows = db.execute(
            text(
                """
                SELECT id, supabase_user_id, email, display_name, deleted_at
                FROM app.account
                WHERE supabase_user_id = :supabase_user_id
                   OR lower(btrim(email)) = :email
                FOR UPDATE
                """
            ),
            {"supabase_user_id": request.supabase_user_id, "email": request.email},
        ).mappings().all()
        if len(rows) > 1:
            raise BootstrapConflictError("Supabase user ID and email identify different accounts")
        if not rows:
            return db.execute(
                text(
                    """
                    INSERT INTO app.account (supabase_user_id, email, display_name)
                    VALUES (:supabase_user_id, :email, :display_name)
                    RETURNING id
                    """
                ),
                {
                    "supabase_user_id": request.supabase_user_id,
                    "email": request.email,
                    "display_name": request.display_name,
                },
            ).scalar_one()

        account = rows[0]
        if account["deleted_at"] is not None:
            raise BootstrapConflictError("matching account is soft-deleted")
        if (
            account["supabase_user_id"] != request.supabase_user_id
            or normalize_email(account["email"]) != request.email
            or account["display_name"] != request.display_name
        ):
            raise BootstrapConflictError(
                "matching account does not match bootstrap identity values"
            )
        return account["id"]


class SystemOwnerProvisioner:
    """Ensure the singleton application-owned global role belongs to the account."""

    def state(self, db: Session, account_id: UUID) -> SystemOwnerState:
        role = db.execute(
            text(
                """
                SELECT account_id
                FROM app.system_role
                """
            )
        ).mappings().one_or_none()
        if role is None:
            return SystemOwnerState(role_exists=False, initial_league_id=None)
        if role["account_id"] != account_id:
            raise BootstrapConflictError("a different account is already the system owner")
        marker = db.execute(
            text(
                """
                SELECT league_id
                FROM app.system_owner_initial_league
                WHERE account_id = :account_id
                """
            ),
            {"account_id": account_id},
        ).scalar_one_or_none()
        return SystemOwnerState(role_exists=True, initial_league_id=marker)

    def create(self, db: Session, account_id: UUID) -> None:
        db.execute(
            text(
                """
                INSERT INTO app.system_role (account_id, is_system_owner)
                VALUES (:account_id, true)
                """
            ),
            {"account_id": account_id},
        )

    def associate(self, db: Session, account_id: UUID, league_id: UUID) -> None:
        db.execute(
            text(
                """
                INSERT INTO app.system_owner_initial_league (account_id, league_id)
                VALUES (:account_id, :league_id)
                """
            ),
            {"account_id": account_id, "league_id": league_id},
        )


class LeagueProvisioner:
    """Create or verify the configured active initial league."""

    def ensure(
        self,
        db: Session,
        initial_league_id: UUID | None,
        request: BootstrapRequest,
        allow_completed_recovery: bool = False,
    ) -> UUID:
        if initial_league_id is not None:
            league = db.execute(
                text(
                    """
                    SELECT id, name, season_name, state, deleted_at
                    FROM app.league
                    WHERE id = :league_id
                    FOR UPDATE
                    """
                ),
                {"league_id": initial_league_id},
            ).mappings().one_or_none()
            if league is None:
                raise BootstrapConflictError("system owner initial league no longer exists")
            if league["deleted_at"] is not None:
                raise BootstrapConflictError("matching initial league is deleted")
            if (
                league["name"] != request.league_name
                or league["season_name"] != request.season_name
            ):
                raise BootstrapConflictError(
                    "initial league does not match bootstrap league values"
                )
            return league["id"]

        rows = db.execute(
            text(
                """
                SELECT id, name, season_name, state, deleted_at
                FROM app.league
                WHERE lower(btrim(name)) = lower(btrim(:league_name))
                   OR lower(btrim(season_name)) = lower(btrim(:season_name))
                FOR UPDATE
                """
            ),
            {"league_name": request.league_name, "season_name": request.season_name},
        ).mappings().all()
        matches = [
            row
            for row in rows
            if row["name"] == request.league_name and row["season_name"] == request.season_name
        ]
        if len(matches) > 1:
            raise BootstrapConflictError("multiple leagues match the bootstrap league values")
        if rows and not matches:
            raise BootstrapConflictError("existing league conflicts with bootstrap league values")
        if not matches:
            return db.execute(
                text(
                    """
                    INSERT INTO app.league (name, season_name)
                    VALUES (:league_name, :season_name)
                    RETURNING id
                    """
                ),
                {"league_name": request.league_name, "season_name": request.season_name},
            ).scalar_one()

        league = matches[0]
        if league["deleted_at"] is not None:
            raise BootstrapConflictError("matching initial league is deleted")
        if league["state"] != "active" and not (
            allow_completed_recovery and league["state"] == "completed"
        ):
            raise BootstrapConflictError("matching initial league is not active")
        return league["id"]


class CommissionerMembershipProvisioner:
    """Create or verify the owner's commissioner membership for the initial league."""

    def ensure(self, db: Session, account_id: UUID, league_id: UUID) -> UUID:
        rows = db.execute(
            text(
                """
                SELECT id, is_commissioner, participation_state, deleted_at
                FROM app.league_membership
                WHERE account_id = :account_id AND league_id = :league_id
                FOR UPDATE
                """
            ),
            {"account_id": account_id, "league_id": league_id},
        ).mappings().all()
        if len(rows) > 1:
            raise BootstrapConflictError("multiple memberships match the initial owner and league")
        if not rows:
            return db.execute(
                text(
                    """
                    INSERT INTO app.league_membership (account_id, league_id, is_commissioner)
                    VALUES (:account_id, :league_id, true)
                    RETURNING id
                    """
                ),
                {"account_id": account_id, "league_id": league_id},
            ).scalar_one()

        membership = rows[0]
        if membership["deleted_at"] is not None or not membership["is_commissioner"]:
            membership_id = db.execute(
                text(
                    """
                    UPDATE app.league_membership
                    SET deleted_at = NULL, is_commissioner = true, version = version + 1
                    WHERE id = :membership_id
                    RETURNING id
                    """
                ),
                {"membership_id": membership["id"]},
            ).scalar_one()
            AuditWriter(db).write(
                actor_account_id=account_id,
                league_id=league_id,
                event_type="league_membership.commissioner_recovered",
                entity_type="league_membership",
                entity_id=membership_id,
                before_state={
                    "deleted_at": _timestamp_value(membership["deleted_at"]),
                    "is_commissioner": membership["is_commissioner"],
                },
                after_state={"deleted_at": None, "is_commissioner": True},
            )
            return membership_id
        return membership["id"]


def _timestamp_value(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


class BootstrapService:
    """Compose reusable provisioners in the one required domain transaction."""

    def __init__(self) -> None:
        self.accounts = AccountProvisioner()
        self.system_owners = SystemOwnerProvisioner()
        self.leagues = LeagueProvisioner()
        self.memberships = CommissionerMembershipProvisioner()

    def provision(self, db: Session, request: BootstrapRequest) -> BootstrapResult:
        request = request.normalized()
        with domain_transaction(db):
            db.execute(
                text("SELECT pg_advisory_xact_lock(:lock_key)"),
                {"lock_key": BOOTSTRAP_ADVISORY_LOCK_KEY},
            )
            account_id = self.accounts.ensure(db, request)
            owner = self.system_owners.state(db, account_id)
            league_id = self.leagues.ensure(
                db,
                owner.initial_league_id,
                request,
                allow_completed_recovery=owner.role_exists,
            )
            if not owner.role_exists:
                self.system_owners.create(db, account_id)
            if owner.initial_league_id is None:
                self.system_owners.associate(db, account_id, league_id)
            membership_id = self.memberships.ensure(db, account_id, league_id)
        return BootstrapResult(
            account_id=account_id,
            league_id=league_id,
            membership_id=membership_id,
        )
