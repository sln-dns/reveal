from fastapi.testclient import TestClient

from idea_check_backend.main import create_app


def test_web_client_index_is_served() -> None:
    client = TestClient(create_app())

    response = client.get("/client/")

    assert response.status_code == 200
    assert "Pair flow MVP client" in response.text
    assert "Manual test mode for both players on one page" in response.text
