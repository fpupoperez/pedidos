"""One JetStream publish is acknowledged by the worker callback.

The default suite skips this module. CI sets NATS_URL and runs `-m nats`.
"""

import asyncio
import os
from uuid import uuid4

import nats
import pytest
from nats.js.errors import NotFoundError

from app.core.config import get_settings
from app.nats.stream import ensure_stream, message_body, message_headers
from worker.consumer import handle_message
from worker.handler import HandleResult

pytestmark = pytest.mark.nats


def test_published_message_is_acked(monkeypatch: pytest.MonkeyPatch) -> None:
    """The callback receives the task id and acknowledges a successful handler result."""
    url = os.environ.get("NATS_URL", "")
    if not url:
        pytest.skip("NATS_URL is not set")
    settings = get_settings()
    monkeypatch.setattr(settings, "nats_url", url)
    monkeypatch.setattr(settings, "nats_stream", "ORDERS_TEST")
    monkeypatch.setattr(settings, "nats_subject", "orders.test.import")
    monkeypatch.setattr(settings, "nats_worker", "orders_import_worker_test")
    monkeypatch.setattr("worker.consumer.handle_import", lambda *args, **kwargs: HandleResult("ack"))
    task_id = uuid4()
    asyncio.run(_round_trip(task_id))


async def _round_trip(task_id: object) -> None:
    """Publish one message, let the callback ack it, and remove the test stream."""
    from uuid import UUID

    settings = get_settings()
    assert isinstance(task_id, UUID)
    seen: list[str] = []

    async def callback(msg: object) -> None:
        await handle_message(msg)  # type: ignore[arg-type]
        seen.append("acked")

    client = await nats.connect(settings.nats_url, connect_timeout=2)
    try:
        js = client.jetstream()
        await ensure_stream(js, settings)
        await js.subscribe(
            settings.nats_subject,
            queue=settings.nats_worker,
            durable=settings.nats_worker,
            stream=settings.nats_stream,
            cb=callback,
            manual_ack=True,
        )
        await js.publish(settings.nats_subject, message_body(task_id), headers=message_headers(task_id), timeout=2)
        for _ in range(30):
            if seen:
                break
            await asyncio.sleep(0.1)
        assert seen == ["acked"]
        try:
            await js.delete_stream(settings.nats_stream)
        except NotFoundError:
            pass
    finally:
        await client.close()
