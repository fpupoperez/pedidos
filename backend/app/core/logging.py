"""JSON logs on stdout. Each line carries the current trace and task id."""

import json
import logging
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone

from opentelemetry import trace

task_id_var: ContextVar[str | None] = ContextVar("task_id", default=None)

_configured = False


class _JsonFormatter(logging.Formatter):
    """One JSON object per log record."""

    def __init__(self, service: str) -> None:
        super().__init__()
        self._service = service

    def format(self, record: logging.LogRecord) -> str:
        """Serialize the record. The traceback stays on the server and out of the HTTP body."""
        span_context = trace.get_current_span().get_span_context()
        trace_id = ""
        span_id = ""
        if span_context.trace_id:
            trace_id = format(span_context.trace_id, "032x")
            span_id = format(span_context.span_id, "016x")
        payload: dict[str, object] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "service": self._service,
            "trace_id": trace_id,
            "span_id": span_id,
            "task_id": task_id_var.get(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=True)


def configure_logging(service_name: str) -> None:
    """Attach the JSON formatter to the root logger once per process."""
    global _configured
    if _configured:
        return
    _configured = True
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_JsonFormatter(service_name))
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.INFO)


@contextmanager
def bind_task(task_id: str) -> Iterator[None]:
    """Set task_id for logs and spans inside a request or a worker delivery."""
    token = task_id_var.set(task_id)
    try:
        yield
    finally:
        task_id_var.reset(token)


def reset_logging() -> None:
    """Allow tests to configure logging again."""
    global _configured
    _configured = False
