"""Error bodies use the shared envelope."""

from fastapi.testclient import TestClient

from app.main import create_app


def test_unknown_path_is_the_error_envelope() -> None:
    """A missing route is ErrorResponse, not a top-level detail string."""
    client = TestClient(create_app())
    response = client.get("/api/v1/missing")
    assert response.status_code == 404
    body = response.json()
    assert body["success"] is False
    assert body["data"] is None
    assert body["errors"][0]["code"] == 404
    assert "detail" not in body
