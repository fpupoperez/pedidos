"""Import a CSV inline and control the task."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import TaskRow
from app.db.session import make_session_factory
from app.main import create_app
from worker.handler import handle_import

CSV = "\n".join(
    [
        "fecha,cliente,pais,producto,importe,estado",
        "2024-03-13,Ana Ruiz,España,Teclado,10.50,pagado",
        "32/13/2024,Ana Ruiz,España,Teclado,1.00,pagado",
        '2024-03-13,Ana Ruiz,Spain,Teclado,"10,50",pagado',
    ]
) + "\n"


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, migrated: object) -> TestClient:
    """An API whose files land in a temporary directory and whose database is orders_test."""
    settings = get_settings()
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "nats_delivery", "inline")
    return TestClient(create_app())


def _session() -> Session:
    """A short-lived session on the test database."""
    return make_session_factory(make_session_engine())()


def make_session_engine():
    """The engine pointed at the test database."""
    from app.db.session import make_engine

    return make_engine()


def test_upload_completes_and_keeps_the_file(client: TestClient, migrated: object) -> None:
    """A CSV is imported, summarized, and downloadable. The same bytes are refused."""
    response = client.post("/api/v1/imports", files={"file": ("orders.csv", CSV.encode(), "text/csv")})
    assert response.status_code == 202
    body = response.json()
    data = body["data"]
    assert data["status"] == "completed"
    assert data["summary"]["phase"] == "completed"
    assert data["summary"]["totalRows"] == 3
    assert data["summary"]["acceptedRows"] == 1
    assert data["summary"]["importedRows"] == 1
    assert data["summary"]["duplicateRows"] == 1
    assert data["summary"]["invalidRows"] == 1
    task_id = data["taskId"]
    with _session() as session:
        stored = session.get(TaskRow, task_id)
        assert stored is not None
        assert "phase" not in stored.summary
    rejected = client.get(f"/api/v1/tasks/{task_id}/rejections")
    assert rejected.status_code == 200
    assert rejected.json()["data"]["count"] == 2
    downloaded = client.get(data["sourceFile"])
    assert downloaded.status_code == 200
    assert downloaded.content == CSV.encode()
    orders = client.get("/api/v1/orders", params={"taskId": task_id})
    assert orders.status_code == 200
    assert orders.json()["data"]["objects"][0]["sourceFile"] == data["sourceFile"]
    again = client.post("/api/v1/imports", files={"file": ("orders.csv", CSV.encode(), "text/csv")})
    assert again.status_code == 409
    assert task_id in again.json()["errors"][0]["msg"]
    missing = client.get("/api/v1/tasks/00000000-0000-0000-0000-000000000099")
    assert missing.status_code == 404
    finished = client.post(f"/api/v1/tasks/{task_id}/cancel")
    assert finished.status_code == 409
    with _session() as session:
        row = session.get(TaskRow, task_id)
        assert row is not None
        row.storage_path = "/etc/passwd"
        session.commit()
    hidden = client.get(data["sourceFile"])
    assert hidden.status_code == 404


def test_cancel_pending_before_the_handler(client: TestClient, tmp_path: Path) -> None:
    """A cancel that wins before the handler writes no orders."""
    settings = get_settings()
    uploads = settings.data_dir / "uploads"
    uploads.mkdir(parents=True, exist_ok=True)
    from uuid import uuid4

    task_id = uuid4()
    relative = f"uploads/{task_id}.csv"
    (settings.data_dir / relative).write_text(CSV, encoding="utf-8")
    with _session() as session:
        session.add(
            TaskRow(
                id=task_id,
                status="pending",
                filename="orders.csv",
                storage_path=relative,
                content_hash="c" * 64,
                summary={"cleaned": False},
            )
        )
        session.commit()
    cancelled = client.post(f"/api/v1/tasks/{task_id}/cancel")
    assert cancelled.status_code == 200
    handle_import(task_id)
    orders = client.get("/api/v1/orders", params={"taskId": str(task_id)})
    assert orders.json()["data"]["count"] == 0
    assert client.get(f"/api/v1/tasks/{task_id}").json()["data"]["summary"]["importedRows"] == 0


def test_retry_rules(client: TestClient) -> None:
    """retries_exhausted can run again. invalid_header cannot."""
    first = client.post("/api/v1/imports", files={"file": ("orders.csv", CSV.encode(), "text/csv")})
    task_id = first.json()["data"]["taskId"]
    with _session() as session:
        row = session.get(TaskRow, task_id)
        assert row is not None
        row.status = "failed"
        row.failure_reason = "invalid_header"
        session.commit()
    refused = client.post(f"/api/v1/tasks/{task_id}/retry")
    assert refused.status_code == 409
    with _session() as session:
        row = session.get(TaskRow, task_id)
        assert row is not None
        row.status = "failed"
        row.failure_reason = "retries_exhausted"
        session.commit()
    retried = client.post(f"/api/v1/tasks/{task_id}/retry")
    assert retried.status_code == 202
    assert retried.json()["data"]["status"] == "completed"
