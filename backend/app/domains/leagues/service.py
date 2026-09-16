"""League-scoped creation and selection queries."""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.app.core.errors import NotFoundError, PermissionDeniedError
from backend.app.db.audit import AuditWriter
from backend.app.db.transactions import domain_transaction
from backend.app.domains.identity.service import CurrentAccount


@dataclass(frozen=True)
class LeagueDetail:
    id: UUID
    name: str
    season_name: str
    state: str
    roster_locked: bool
    is_commissioner: bool
    participation_state: str
    read_only: bool


class LeagueService:
    def create(
        self, db: Session, account: CurrentAccount, *, name: str, season_name: str
    ) -> LeagueDetail:
        if not account.is_system_owner:
            raise PermissionDeniedError()
        with domain_transaction(db):
            league_id = db.execute(
                text(
                    """
                    INSERT INTO app.league (name, season_name, state, roster_locked)
                    VALUES (:name, :season_name, 'active', false)
                    RETURNING id
                    """
                ),
                {"name": name, "season_name": season_name},
            ).scalar_one()
            db.execute(
                text(
                    """
                    INSERT INTO app.league_membership
                        (account_id, league_id, is_commissioner, participation_state)
                    VALUES (:account_id, :league_id, true, 'non_playing')
                    """
                ),
                {"account_id": account.id, "league_id": league_id},
            )
            AuditWriter(db).write(
                actor_account_id=account.id,
                league_id=league_id,
                event_type="league.created",
                entity_type="league",
                entity_id=league_id,
                after_state={"name": name, "season_name": season_name, "state": "active"},
            )
        return LeagueDetail(
            id=league_id,
            name=name,
            season_name=season_name,
            state="active",
            roster_locked=False,
            is_commissioner=True,
            participation_state="non_playing",
            read_only=False,
        )

    def get_for_account(self, db: Session, *, account_id: UUID, league_id: UUID) -> LeagueDetail:
        row = (
            db.execute(
                text(
                    """
                SELECT league.id, league.name, league.season_name, league.state,
                       league.roster_locked, membership.is_commissioner,
                       membership.participation_state, league.state = 'completed' AS read_only
                FROM app.league_membership AS membership
                JOIN app.league AS league ON league.id = membership.league_id
                WHERE membership.account_id = :account_id
                  AND membership.league_id = :league_id
                  AND membership.deleted_at IS NULL
                  AND league.deleted_at IS NULL
                """
                ),
                {"account_id": account_id, "league_id": league_id},
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise NotFoundError()
        return LeagueDetail(**row)
