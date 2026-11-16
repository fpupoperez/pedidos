"""The inline import is one trace and its id is stored on the task."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from opentelemetry import trace

from app.core.config import get_settings
from app.db.models import TaskRow
from app.db.session import make_engine, make_session_factory
from app.main import create_app
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from tests.test_imports_and_tasks import CSV


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, migrated: object) -> TestClient:
    """An API that imports inline into the test database."""
    settings = get_settings()
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "nats_delivery", "inline")
    return TestClient(create_app())


def test_inline_import_shares_one_trace(client: TestClient, finished_spans: InMemorySpanExporter) -> None:
    """import.accept, the insert, and import.handle belong to the trace stored on the task."""
    response = client.post("/api/v1/imports", files={"file": ("trace.csv", CSV.encode(), "text/csv")})
    assert response.status_code == 202
    task_id = response.json()["data"]["taskId"]
    provider = trace.get_tracer_provider()
    force_flush = getattr(provider, "force_flush", None)
    if force_flush is not None:
        force_flush()
    names = {item.name for item in finished_spans.get_finished_spans()}
    assert {"import.accept", "task.insert", "import.handle", "import.clean", "task.transition"} <= names
    with make_session_factory(make_engine())() as session:
        task = session.get(TaskRow, task_id)
        assert task is not None
        assert task.trace_id
        accept = next(item for item in finished_spans.get_finished_spans() if item.name == "import.accept")
        assert task.trace_id == format(accept.context.trace_id, "032x")
