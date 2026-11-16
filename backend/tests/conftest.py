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

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.engine import Engine  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.core.telemetry import configure_telemetry  # noqa: E402

_EXPORTER = InMemorySpanExporter()
configure_telemetry(get_settings(), "orders-api", span_exporter=_EXPORTER)


def span_exporter() -> InMemorySpanExporter:
    """The in-memory exporter installed before the app starts."""
    return _EXPORTER


@pytest.fixture
def finished_spans() -> InMemorySpanExporter:
    """The same exporter the test process configured. Clear it before each test."""
    _EXPORTER.clear()
    return _EXPORTER


@pytest.fixture
def migrated() -> Engine:
    """Upgrade the test database and remove import rows after the test.

    The database name must not be orders. That name is reserved for the Compose database.
    """
    url = get_settings().database_url
    if url.rsplit("/", 1)[-1] == "orders":
        raise RuntimeError("Refusing to run tests against the database named orders.")
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    command.upgrade(config, "head")
    engine = create_engine(url, pool_pre_ping=True)
    try:
        yield engine
    finally:
        with engine.begin() as connection:
            connection.execute(text("TRUNCATE import_rejections, orders, tasks CASCADE"))
        engine.dispose()
