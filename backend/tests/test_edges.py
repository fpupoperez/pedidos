"""Branches the main suite does not pass through: filters, publish failure, and setup helpers."""

import asyncio
import logging
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from opentelemetry.sdk.trace.export import SpanExportResult

from app.core.config import Settings, get_settings
from app.core.errors import ApiError
from app.core.logging import _JsonFormatter, bind_task, configure_logging, reset_logging
from app.core.telemetry import _DropSqlAlchemyExporter, _otlp_target
from app.db.models import TaskRow
from app.db.session import make_engine, make_session_factory
from app.main import create_app
from app.nats.publisher import deliver
from app.services.questions import ask
from app.sql.execute import execute_select
from app.sql.validator import GuardError, validate_sql

CSV = (
    "fecha,cliente,pais,producto,importe,estado\n"
    "2024-03-13,Ana Ruiz,España,Teclado,10.50,pagado\n"
    "2024-12-02,Luis Ortega,Francia,Monitor,3.00,enviado\n"
)


@pytest.fixture
def client(tmp_path, monkeypatch: pytest.MonkeyPatch, migrated: object) -> TestClient:
    """Inline imports into the test database."""
    settings = get_settings()
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "nats_delivery", "inline")
    return TestClient(create_app())


def test_order_filters_and_bad_month(client: TestClient) -> None:
    """Each list filter narrows the page, and a bad month is 422."""
    uploaded = client.post("/api/v1/imports", files={"file": ("orders.csv", CSV.encode(), "text/csv")})
    task_id = uploaded.json()["data"]["taskId"]
    listed = client.get("/api/v1/tasks", params={"status": "completed", "limit": 1})
    assert listed.status_code == 200
    page = client.get(
        "/api/v1/orders",
        params={"taskId": task_id, "country": "España", "customer": "Ana Ruiz", "status": "pagado", "saleMonth": "2024-03", "limit": 1},
    )
    assert page.status_code == 200
    assert page.json()["data"]["count"] == 1
    december = client.get("/api/v1/orders", params={"saleMonth": "2024-12"})
    assert december.status_code == 200
    assert december.json()["data"]["count"] == 1
    assert client.get("/api/v1/orders", params={"saleMonth": "2024-13"}).status_code == 422
    assert client.get("/api/v1/orders", params={"saleMonth": "march"}).status_code == 422


def test_upload_rejections(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """An empty, huge, or non-CSV upload never becomes a task."""
    assert client.post("/api/v1/imports", files={"file": ("orders.csv", b"", "text/csv")}).status_code == 400
    assert client.post("/api/v1/imports", files={"file": ("notes.txt", b"hola", "text/plain")}).status_code == 400
    assert client.post("/api/v1/imports", files={"file": ("orders.csv", b"\xff", "text/csv")}).status_code == 400
    monkeypatch.setattr(get_settings(), "max_upload_bytes", 4)
    assert client.post("/api/v1/imports", files={"file": ("orders.csv", b"fecha", "text/csv")}).status_code == 413


def test_failed_publish_marks_the_task(monkeypatch: pytest.MonkeyPatch, migrated: object) -> None:
    """JetStream without a URL stores publish_failed. An unknown id still returns 502."""
    settings = get_settings()
    monkeypatch.setattr(settings, "nats_delivery", "jetstream")
    monkeypatch.setattr(settings, "nats_url", "")
    task_id = uuid4()
    factory = make_session_factory(make_engine())
    with factory() as session:
        session.add(
            TaskRow(
                id=task_id,
                status="pending",
                filename="orders.csv",
                storage_path=f"uploads/{task_id}.csv",
                content_hash="b" * 64,
                summary={"cleaned": False},
            )
        )
        session.commit()
    with pytest.raises(ApiError) as caught:
        deliver(task_id)
    assert caught.value.status_code == 502
    with factory() as session:
        task = session.get(TaskRow, task_id)
        assert task is not None
        assert task.failure_reason == "publish_failed"
    with pytest.raises(ApiError):
        deliver(uuid4())


def test_model_payload_and_reader_errors(monkeypatch: pytest.MonkeyPatch, migrated: object) -> None:
    """A bad model payload is 502. The reader rejects a forbidden table and returns string cells."""
    monkeypatch.setattr(get_settings(), "llm_provider", "other")
    with pytest.raises(ApiError) as caught:
        ask("hola")
    assert caught.value.status_code == 502
    monkeypatch.setattr(get_settings(), "llm_provider", "fake")

    def bad(self: object, question: str) -> tuple[str, int, int]:
        return "[]", 0, 0

    monkeypatch.setattr("app.providers.fake.FakeProvider.complete", bad)
    with pytest.raises(ApiError) as caught:
        ask("hola")
    assert caught.value.status_code == 502
    with pytest.raises(GuardError):
        validate_sql("", row_limit=200)
    with pytest.raises(GuardError):
        validate_sql("SELECT country FROM orders LIMIT (SELECT 1)", row_limit=200)
    columns, rows = execute_select("SELECT NULL::text AS empty_value, CURRENT_DATE AS today")
    assert columns == ["empty_value", "today"]
    assert rows[0][0] == ""
    with pytest.raises(ApiError):
        execute_select("SELECT id FROM tasks")


def test_log_formatter_and_otlp_target() -> None:
    """JSON logs include the task id, and the OTLP target follows the settings."""
    reset_logging()
    configure_logging("orders-api")
    record = logging.LogRecord("orders", logging.INFO, __file__, 1, "hello", (), (ValueError, ValueError("x"), None))
    with bind_task("task-1"):
        line = _JsonFormatter("orders-api").format(record)
    assert "task-1" in line
    assert "hello" in line
    assert _otlp_target(Settings(otel_exporter_otlp_endpoint="http://otel/"))[0] == "http://otel"
    host, headers = _otlp_target(Settings(langfuse_public_key="pub", langfuse_secret_key="sec", langfuse_host="http://lf"))
    assert host.endswith("/api/public/otel")
    assert headers["Authorization"].startswith("Basic ")


def test_stdout_exporter_drops_sqlalchemy_spans() -> None:
    """A SQLAlchemy span is not forwarded. Any other span is."""
    forwarded: list[object] = []

    class Inner:
        def export(self, spans: object) -> SpanExportResult:
            forwarded.append(spans)
            return SpanExportResult.SUCCESS

        def shutdown(self) -> None:
            return None

        def force_flush(self, timeout_millis: int = 30000) -> bool:
            return True

    exporter = _DropSqlAlchemyExporter(Inner())  # type: ignore[arg-type]
    sql_span = SimpleNamespace(instrumentation_scope=SimpleNamespace(name="opentelemetry.instrumentation.sqlalchemy"))
    other = SimpleNamespace(instrumentation_scope=SimpleNamespace(name="orders"))
    assert exporter.export([sql_span]) == SpanExportResult.SUCCESS  # type: ignore[list-item]
    assert forwarded == []
    assert exporter.export([other]) == SpanExportResult.SUCCESS  # type: ignore[list-item]
    assert forwarded
    exporter.shutdown()
    assert exporter.force_flush() is True


def test_worker_serve_stops_when_asked(monkeypatch: pytest.MonkeyPatch) -> None:
    """The consumer connects, subscribes, and drains when the stop event is set."""
    from worker import main as worker_main

    monkeypatch.setattr(get_settings(), "nats_url", "nats://localhost:4222")

    class Client:
        def jetstream(self) -> "Client":
            return self

        async def subscribe(self, *args: object, **kwargs: object) -> None:
            return None

        async def drain(self) -> None:
            return None

    async def connect(url: str, connect_timeout: int = 2) -> Client:
        return Client()

    async def ensure(js: object, settings: object) -> None:
        return None

    monkeypatch.setattr(worker_main.nats, "connect", connect)
    monkeypatch.setattr(worker_main, "ensure_stream", ensure)
    stop = asyncio.Event()
    stop.set()
    asyncio.run(worker_main.serve(stop))
    monkeypatch.setattr(get_settings(), "nats_url", "")
    with pytest.raises(RuntimeError):
        asyncio.run(worker_main.serve(stop))

    async def idle(stop: asyncio.Event | None = None) -> None:
        return None

    monkeypatch.setattr(worker_main, "serve", idle)
    worker_main.main()
