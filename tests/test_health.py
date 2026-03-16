from fastapi.testclient import TestClient

from idea_check_backend.main import app


def test_healthcheck_returns_ok() -> None:
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "environment": "local"}
