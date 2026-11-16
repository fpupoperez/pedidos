"""The inline import is one trace and its id is stored on the task."""

import asyncio
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from opentelemetry import trace
from opentelemetry.propagate import inject

from app.core.config import get_settings
from app.db.models import TaskRow
from app.db.session import make_engine, make_session_factory
from app.core.telemetry import span
from app.main import create_app
from worker.consumer import handle_message
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


def test_question_spans_are_one_tree(client: TestClient, finished_spans: InMemorySpanExporter) -> None:
    """question.llm, question.guard, and question.execute sit under question.ask."""
    response = client.post("/api/v1/questions", json={"question": "¿cuánto hay?"})
    assert response.status_code == 200
    names = {item.name for item in finished_spans.get_finished_spans()}
    assert {"question.ask", "question.llm", "question.guard", "question.execute"} <= names


def test_delivery_continues_the_parent_trace(client: TestClient, finished_spans: InMemorySpanExporter) -> None:
    """import.handle is a child of the span that injected traceparent."""
    headers: dict[str, str] = {}
    with span("upstream"):
        inject(headers)
        parent = trace.get_current_span().get_span_context().span_id
    message = _Delivery(f'{{"taskId": "{uuid4()}"}}'.encode(), headers)
    asyncio.run(handle_message(message))  # type: ignore[arg-type]
    assert message.action == "ack"
    child = next(item for item in finished_spans.get_finished_spans() if item.name == "import.handle")
    assert child.parent is not None
    assert child.parent.span_id == parent


class _Delivery:
    """A JetStream message with the headers the callback extracts."""

    def __init__(self, data: bytes, headers: dict[str, str]) -> None:
        self.data = data
        self.headers = headers
        self.action = ""

    @property
    def metadata(self) -> SimpleNamespace:
        """First delivery."""
        return SimpleNamespace(num_delivered=1)

    async def ack(self) -> None:
        """Record the acknowledgement."""
        self.action = "ack"

    async def nak(self) -> None:
        """Record a negative acknowledgement."""
        self.action = "nak"
