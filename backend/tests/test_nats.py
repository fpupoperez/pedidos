"""JetStream message shape, and ack or nak from the handler result."""

import asyncio
from types import SimpleNamespace
from uuid import uuid4

import pytest
from opentelemetry import trace

from app.core.telemetry import span
from app.nats.stream import message_body, message_headers
from worker.consumer import handle_message
from worker.handler import HandleResult


class _Message:
    """The fields the callback reads. ack and nak record what the worker decided."""

    def __init__(self, data: bytes, headers: dict[str, str] | None = None, delivered: int = 1) -> None:
        self.data = data
        self.headers = headers
        self.action = ""
        self._delivered = delivered

    @property
    def metadata(self) -> SimpleNamespace:
        """JetStream delivery count."""
        return SimpleNamespace(num_delivered=self._delivered)

    async def ack(self) -> None:
        """Record an acknowledgement."""
        self.action = "ack"

    async def nak(self) -> None:
        """Record a negative acknowledgement."""
        self.action = "nak"


def test_message_carries_the_task_and_the_trace() -> None:
    """The body is the task id and the headers continue the current span."""
    task_id = uuid4()
    with span("nats.publish", task_id=str(task_id)):
        headers = message_headers(task_id)
        current = trace.get_current_span().get_span_context()
    assert message_body(task_id) == f'{{"taskId": "{task_id}"}}'.encode()
    assert headers["Nats-Msg-Id"] == str(task_id)
    assert format(current.trace_id, "032x") in headers["traceparent"]


def test_handler_ack_and_nak_are_forwarded(monkeypatch: pytest.MonkeyPatch) -> None:
    """ack follows a finished import. nak follows a transient failure. A bad body is acked."""
    task_id = uuid4()

    def finish(*args: object, **kwargs: object) -> HandleResult:
        return HandleResult("ack")

    monkeypatch.setattr("worker.consumer.handle_import", finish)
    ok = _Message(message_body(task_id))
    asyncio.run(handle_message(ok))  # type: ignore[arg-type]
    assert ok.action == "ack"

    def fail(*args: object, **kwargs: object) -> HandleResult:
        return HandleResult("nak")

    monkeypatch.setattr("worker.consumer.handle_import", fail)
    again = _Message(message_body(task_id), delivered=2)
    asyncio.run(handle_message(again))  # type: ignore[arg-type]
    assert again.action == "nak"

    bad = _Message(b"not-json")
    asyncio.run(handle_message(bad))  # type: ignore[arg-type]
    assert bad.action == "ack"
