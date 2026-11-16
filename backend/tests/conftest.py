"""Pytest setup. Refuses the Compose database named orders."""

import os

from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+psycopg://orders:orders@localhost:5432/orders_test",
)
os.environ.setdefault(
    "DATABASE_READ_URL",
    "postgresql+psycopg://orders_reader:orders_reader@localhost:5432/orders_test",
)
os.environ.setdefault("NATS_DELIVERY", "inline")
os.environ.setdefault("LLM_PROVIDER", "fake")
os.environ.setdefault("OTEL_EXPORTER_OTLP_ENDPOINT", "")
os.environ.setdefault("LANGFUSE_PUBLIC_KEY", "")
os.environ.setdefault("LANGFUSE_SECRET_KEY", "")

_database = os.environ["DATABASE_URL"].rsplit("/", 1)[-1]
if _database == "orders":
    raise RuntimeError("Refusing to run tests against the database named orders.")

from app.core.config import get_settings  # noqa: E402
from app.core.telemetry import configure_telemetry  # noqa: E402

_EXPORTER = InMemorySpanExporter()
configure_telemetry(get_settings(), "orders-api", span_exporter=_EXPORTER)


def span_exporter() -> InMemorySpanExporter:
    """The in-memory exporter installed before the app starts."""
    return _EXPORTER
