from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

from backend.app.api.identity import get_identity_service, get_token_verifier
from backend.app.db.session import get_db
from backend.app.domains.identity.auth import AuthenticationError, VerifiedIdentity
from backend.app.domains.identity.service import (
    CurrentAccount,
    IdentityService,
    LeagueSummary,
    SessionProjection,
)
from backend.app.main import create_app


class Verifier:
    def verify(self, token: str) -> VerifiedIdentity:
        if token != "valid":
            if token == "unknown":
                return VerifiedIdentity(uuid4(), "missing@example.com")
            if token == "deleted":
                return VerifiedIdentity(uuid4(), "deleted@example.com")
            raise AuthenticationError
        return VerifiedIdentity(uuid4(), "user@example.com")


class Service(IdentityService):
    def resolve_session(self, _db: object, identity: VerifiedIdentity) -> SessionProjection:
        if identity.email in {"missing@example.com", "deleted@example.com"}:
            raise AuthenticationError
        return SessionProjection(
            account=CurrentAccount(uuid4(), identity.email, "Player", False),
            leagues=[
                LeagueSummary(
                    id=uuid4(),
                    name="League",
                    season_name="48",
                    state="active",
                    roster_locked=False,
                    is_commissioner=True,
                    participation_state="active",
                )
            ],
        )


def client() -> TestClient:
    application = create_app()
    application.dependency_overrides[get_token_verifier] = lambda: Verifier()
    application.dependency_overrides[get_identity_service] = Service
    application.dependency_overrides[get_db] = lambda: object()
    return TestClient(application)


def test_session_missing_malformed_and_invalid_credentials_have_safe_401() -> None:
    test_client = client()
    responses = [
        test_client.get("/api/v1/session"),
        test_client.get("/api/v1/session", headers={"Authorization": "Basic token"}),
        test_client.get("/api/v1/session", headers={"Authorization": "Bearer invalid"}),
        test_client.get("/api/v1/session", headers={"Authorization": "Bearer unknown"}),
        test_client.get("/api/v1/session", headers={"Authorization": "Bearer deleted"}),
    ]

    assert [response.status_code for response in responses] == [401, 401, 401, 401, 401]
    assert {response.json()["error"]["code"] for response in responses} == {"unauthenticated"}
    assert {response.json()["error"]["details"] == {} for response in responses} == {True}
    request_ids_match = {
        response.json()["request_id"] == response.headers["X-Request-ID"]
        for response in responses
    }
    assert request_ids_match == {
        True
    }
    assert {response.headers["www-authenticate"] for response in responses} == {"Bearer"}


def test_session_returns_only_navigation_projection() -> None:
    response = client().get("/api/v1/session", headers={"Authorization": "Bearer valid"})

    assert response.status_code == 200
    assert set(response.json()) == {"account", "leagues"}
    assert set(response.json()["account"]) == {"id", "email", "display_name", "is_system_owner"}
    assert response.json()["leagues"] == [
        {
            "id": response.json()["leagues"][0]["id"],
            "name": "League",
            "season_name": "48",
            "state": "active",
            "roster_locked": False,
            "is_commissioner": True,
            "participation_state": "active",
        }
    ]
