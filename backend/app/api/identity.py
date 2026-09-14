from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.app.core.config import get_settings
from backend.app.db.session import get_db
from backend.app.domains.identity.auth import (
    AuthenticationError,
    SupabaseTokenVerifier,
    VerifiedIdentity,
    fetch_jwks,
)
from backend.app.domains.identity.service import IdentityService

router = APIRouter(prefix="/api/v1", tags=["identity"])


def unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"code": "unauthorized", "message": "Unauthorized."},
        headers={"WWW-Authenticate": "Bearer"},
    )


@lru_cache
def get_token_verifier() -> SupabaseTokenVerifier:
    settings = get_settings()
    return SupabaseTokenVerifier(
        issuer=settings.supabase_jwt_issuer,
        audience=settings.supabase_jwt_audience,
        jwks_fetcher=lambda: fetch_jwks(settings.supabase_jwks_url),
        cache_seconds=settings.supabase_jwks_cache_seconds,
    )


def get_identity_service() -> IdentityService:
    return IdentityService()


def current_identity(
    verifier: Annotated[SupabaseTokenVerifier, Depends(get_token_verifier)],
    authorization: Annotated[str | None, Header()] = None,
):
    if authorization is None:
        raise unauthorized()
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token or token.strip() != token:
        raise unauthorized()
    try:
        return verifier.verify(token)
    except AuthenticationError:
        raise unauthorized() from None


class AccountResponse(BaseModel):
    id: str
    email: str
    display_name: str
    is_system_owner: bool


class LeagueResponse(BaseModel):
    id: str
    name: str
    season_name: str
    state: str
    roster_locked: bool
    is_commissioner: bool
    participation_state: str


class SessionResponse(BaseModel):
    account: AccountResponse
    leagues: list[LeagueResponse]


@router.get("/session", response_model=SessionResponse)
def session(
    identity: Annotated[VerifiedIdentity, Depends(current_identity)],
    db: Annotated[Session, Depends(get_db)],
    service: Annotated[IdentityService, Depends(get_identity_service)],
) -> SessionResponse:
    try:
        projection = service.resolve_session(db, identity)
    except AuthenticationError:
        raise unauthorized() from None
    return SessionResponse(
        account=AccountResponse(
            id=str(projection.account.id),
            email=projection.account.email,
            display_name=projection.account.display_name,
            is_system_owner=projection.account.is_system_owner,
        ),
        leagues=[
            LeagueResponse(id=str(league.id), **league.__dict__) for league in projection.leagues
        ],
    )
