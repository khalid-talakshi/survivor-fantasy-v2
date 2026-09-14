from uuid import UUID, uuid4

import pytest
from fastapi import APIRouter, HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel, field_validator
from sqlalchemy.exc import OperationalError, SQLAlchemyError

from backend.app.core.context import current_request_id, current_transaction_id
from backend.app.core.errors import (
    ConflictError,
    DatabaseUnavailableError,
    NotFoundError,
    PermissionDeniedError,
    StaleVersionError,
    UnauthenticatedError,
    ValidationError,
)
from backend.app.db.transactions import domain_transaction
from backend.app.main import create_app


def test_request_id_is_generated_and_returned() -> None:
    response = TestClient(create_app()).get("/api/v1")

    assert response.status_code == 200
    assert UUID(response.headers["X-Request-ID"])


def test_valid_request_id_is_propagated_and_invalid_one_is_replaced() -> None:
    supplied = uuid4()
    client = TestClient(create_app())

    assert client.get("/api/v1", headers={"X-Request-ID": str(supplied)}).headers[
        "X-Request-ID"
    ] == str(supplied)
    assert client.get("/api/v1", headers={"X-Request-ID": "not-a-uuid"}).headers[
        "X-Request-ID"
    ] != "not-a-uuid"


def test_domain_errors_have_stable_envelope_and_request_id() -> None:
    app = create_app()
    router = APIRouter()

    @router.get("/api/v1/forbidden")
    def forbidden() -> None:
        raise PermissionDeniedError()

    @router.get("/api/v1/stale")
    def stale() -> None:
        raise StaleVersionError()

    app.include_router(router)
    # Domain routers are registered before the API catch-all in production.
    # Move the two test routes ahead of it to exercise the shared handlers.
    app.router.routes.insert(0, app.router.routes.pop())
    client = TestClient(app)

    forbidden_response = client.get("/api/v1/forbidden")
    stale_response = client.get("/api/v1/stale")

    assert forbidden_response.status_code == 403
    assert forbidden_response.json()["error"]["code"] == "permission_denied"
    assert forbidden_response.json()["request_id"] == forbidden_response.headers["X-Request-ID"]
    assert stale_response.status_code == 409
    assert stale_response.json()["error"] == {
        "code": "stale_version",
        "message": "The record changed since it was loaded.",
        "details": {},
    }


@pytest.mark.parametrize(
    ("path", "status_code", "code"),
    [
        ("unauthenticated", 401, "unauthenticated"),
        ("validation", 422, "validation_error"),
        ("not-found", 404, "not_found"),
        ("conflict", 409, "conflict"),
        ("database", 503, "database_unavailable"),
        ("http-forbidden", 403, "permission_denied"),
    ],
)
def test_error_codes_have_stable_statuses(path: str, status_code: int, code: str) -> None:
    app = create_app()
    router = APIRouter()

    @router.get("/api/v1/unauthenticated")
    def unauthenticated() -> None:
        raise UnauthenticatedError()

    @router.get("/api/v1/validation")
    def validation() -> None:
        raise ValidationError()

    @router.get("/api/v1/not-found")
    def not_found() -> None:
        raise NotFoundError()

    @router.get("/api/v1/conflict")
    def conflict() -> None:
        raise ConflictError()

    @router.get("/api/v1/database")
    def database() -> None:
        raise DatabaseUnavailableError()

    @router.get("/api/v1/http-forbidden")
    def http_forbidden() -> None:
        raise HTTPException(status_code=403)

    app.include_router(router)
    app.router.routes.insert(0, app.router.routes.pop())
    response = TestClient(app).get(f"/api/v1/{path}")

    assert response.status_code == status_code
    assert response.json()["error"]["code"] == code


def test_validation_and_unexpected_errors_are_sanitized() -> None:
    app = create_app()
    router = APIRouter()

    @router.get("/api/v1/typed")
    def typed(value: int) -> None:
        del value

    @router.get("/api/v1/unexpected")
    def unexpected() -> None:
        raise RuntimeError("private implementation detail")

    class ValidatorInput(BaseModel):
        value: int

        @field_validator("value")
        @classmethod
        def reject_value(cls, value: int) -> int:
            raise ValueError(f"{value} is not accepted")

    @router.post("/api/v1/validator")
    def validator(_: ValidatorInput) -> None:
        return None

    app.include_router(router)
    app.router.routes.insert(0, app.router.routes.pop())
    client = TestClient(app, raise_server_exceptions=False)

    validation_response = client.get("/api/v1/typed?value=not-a-number")
    validator_response = client.post("/api/v1/validator", json={"value": 1})
    supplied_request_id = "11111111-1111-1111-1111-111111111111"
    unexpected_response = client.get(
        "/api/v1/unexpected", headers={"X-Request-ID": supplied_request_id}
    )

    assert validation_response.status_code == 422
    assert validation_response.json()["error"]["code"] == "validation_error"
    assert validator_response.status_code == 422
    assert validator_response.json()["error"]["code"] == "validation_error"
    assert unexpected_response.status_code == 500
    assert unexpected_response.json()["request_id"] == supplied_request_id
    assert unexpected_response.headers["X-Request-ID"] == supplied_request_id
    assert unexpected_response.json()["error"] == {
        "code": "internal_error",
        "message": "An unexpected error occurred.",
        "details": {},
    }


def test_only_operational_database_errors_map_to_database_unavailable() -> None:
    app = create_app()
    router = APIRouter()

    @router.get("/api/v1/operational-error")
    def operational_error() -> None:
        raise OperationalError("SELECT 1", {}, RuntimeError("connection failed"))

    @router.get("/api/v1/sql-error")
    def sql_error() -> None:
        raise SQLAlchemyError("invalid SQL")

    app.include_router(router)
    app.router.routes.insert(0, app.router.routes.pop())
    client = TestClient(app, raise_server_exceptions=False)

    operational_response = client.get("/api/v1/operational-error")
    sql_response = client.get("/api/v1/sql-error")

    assert operational_response.status_code == 503
    assert operational_response.json()["error"]["code"] == "database_unavailable"
    assert sql_response.status_code == 500
    assert sql_response.json()["error"]["code"] == "internal_error"


class FakeTransaction:
    def __init__(self, session: "FakeSession") -> None:
        self.session = session

    def __enter__(self) -> None:
        self.session.open = True

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> bool:
        self.session.open = False
        self.session.committed = exc_type is None
        self.session.rolled_back = exc_type is not None
        return False


class FakeSession:
    def __init__(self) -> None:
        self.open = False
        self.committed = False
        self.rolled_back = False

    def in_transaction(self) -> bool:
        return self.open

    def begin(self) -> FakeTransaction:
        return FakeTransaction(self)


def test_domain_transaction_scopes_distinct_correlation_ids_and_rolls_back() -> None:
    session = FakeSession()
    with domain_transaction(session):
        first = current_transaction_id()
        assert current_request_id()
    assert session.committed
    with domain_transaction(session):
        second = current_transaction_id()
    assert first != second
    with pytest.raises(ValueError), domain_transaction(session):
        raise ValueError("rollback")
    assert session.rolled_back
    with pytest.raises(RuntimeError, match="domain transaction"):
        current_transaction_id()
