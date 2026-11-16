"""Liveness route."""

from fastapi.testclient import TestClient

from app.main import create_app


def test_health_returns_the_envelope() -> None:
    """get_health reports ok and an empty session."""
    client = TestClient(create_app())
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["errors"] == []
    assert body["session_auth"] == {}
    assert body["data"] == {"status": "ok"}
