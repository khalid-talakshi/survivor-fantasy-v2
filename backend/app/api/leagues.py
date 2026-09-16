from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

from backend.app.api.identity import current_identity, get_identity_service
from backend.app.db.session import get_db
from backend.app.domains.identity.auth import AuthenticationError, VerifiedIdentity
from backend.app.domains.identity.service import CurrentAccount, IdentityService
from backend.app.domains.leagues.service import LeagueDetail, LeagueService

router = APIRouter(prefix="/api/v1/leagues", tags=["leagues"])


def get_league_service() -> LeagueService:
    return LeagueService()


class LeagueCreateRequest(BaseModel):
    name: str
    season_name: str

    @field_validator("name", "season_name")
    @classmethod
    def required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value


class LeagueResponse(BaseModel):
    id: str
    name: str
    season_name: str
    state: str
    roster_locked: bool
    is_commissioner: bool
    participation_state: str
    read_only: bool


def _response(league: LeagueDetail) -> LeagueResponse:
    return LeagueResponse(
        id=str(league.id),
        name=league.name,
        season_name=league.season_name,
        state=league.state,
        roster_locked=league.roster_locked,
        is_commissioner=league.is_commissioner,
        participation_state=league.participation_state,
        read_only=league.read_only,
    )


def _account(db: Session, identity: VerifiedIdentity, service: IdentityService) -> CurrentAccount:
    try:
        return service.resolve_account(db, identity)
    except AuthenticationError:
        from backend.app.api.identity import unauthorized

        raise unauthorized() from None


@router.post("", response_model=LeagueResponse, status_code=201)
def create_league(
    request: LeagueCreateRequest,
    identity: Annotated[VerifiedIdentity, Depends(current_identity)],
    db: Annotated[Session, Depends(get_db)],
    identity_service: Annotated[IdentityService, Depends(get_identity_service)],
    service: Annotated[LeagueService, Depends(get_league_service)],
) -> LeagueResponse:
    account = _account(db, identity, identity_service)
    # Resolving the account issues a read query, which starts SQLAlchemy's implicit
    # transaction. The league service owns the required outer write transaction.
    if db.in_transaction():
        db.rollback()
    return _response(
        service.create(
            db,
            account,
            name=request.name,
            season_name=request.season_name,
        )
    )


@router.get("/{league_id}", response_model=LeagueResponse)
def get_league(
    league_id: UUID,
    identity: Annotated[VerifiedIdentity, Depends(current_identity)],
    db: Annotated[Session, Depends(get_db)],
    identity_service: Annotated[IdentityService, Depends(get_identity_service)],
    service: Annotated[LeagueService, Depends(get_league_service)],
) -> LeagueResponse:
    account = _account(db, identity, identity_service)
    return _response(service.get_for_account(db, account_id=account.id, league_id=league_id))
