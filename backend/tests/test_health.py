from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from backend.app.db.session import get_db
from backend.app.main import create_app


class ReadySession:
    def execute(self, _statement: object) -> None:
        return None


def override_db() -> Iterator[ReadySession]:
    yield ReadySession()


def test_liveness_probe() -> None:
    client = TestClient(create_app())

    response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_probe() -> None:
    application = create_app()
    application.dependency_overrides[get_db] = override_db
    client = TestClient(application)

    response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


@pytest.mark.parametrize("method", ["get", "post", "put", "patch", "delete", "options"])
def test_unknown_api_route_never_falls_through_to_spa(method: str) -> None:
    client = TestClient(create_app())

    response = getattr(client, method)("/api/v1/does-not-exist")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["error"]["code"] == "not_found"
