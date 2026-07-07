from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_health() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["service"] == "sign_cloud_v1"
    assert data["vocab_size"] > 0


def test_root_health() -> None:
    response = client.get("/")

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["service"] == "sign_cloud_v1"

