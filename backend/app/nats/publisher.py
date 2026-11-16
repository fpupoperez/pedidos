"""Hand a committed task to the worker.

inline runs the handler in this process. jetstream publishes orders.import.
A publish failure is stored on the task so the caller can retry it.
"""

import asyncio
import logging
from collections.abc import Coroutine
from concurrent.futures import ThreadPoolExecutor
from uuid import UUID

import nats
from nats.js.client import JetStreamContext

from app.core.config import get_settings
from app.core.errors import ApiError
from app.core.telemetry import record_publish
from app.db.session import make_engine, make_session_factory
from app.nats.stream import ensure_stream, message_body, message_headers
from app.services.tasks import transition_status
from worker.handler import handle_import

logger = logging.getLogger(__name__)


def deliver(task_id: UUID) -> None:
    """Run the import now, or publish it. A failed publish leaves the task failed."""
    settings = get_settings()
    if settings.nats_delivery == "inline":
        handle_import(task_id)
        record_publish("ok")
        return
    headers = message_headers(task_id)
    try:
        _run(publish_task(task_id, headers))
    except Exception as exc:
        try:
            _mark_unpublished(task_id)
        except Exception:
            logger.exception("Could not store publish_failed for %s", task_id)
        record_publish("error")
        raise ApiError(502, "The import could not be published.") from exc
    record_publish("ok")


async def publish_task(task_id: UUID, headers: dict[str, str]) -> None:
    """Ensure the stream and wait for the JetStream acknowledgement.

    Nats-Msg-Id is the task id, so a retry inside the duplicate window is one message.
    """
    settings = get_settings()
    if not settings.nats_url:
        raise ApiError(502, "The import could not be published.")
    client = await nats.connect(settings.nats_url, connect_timeout=2)
    try:
        js: JetStreamContext = client.jetstream()
        await ensure_stream(js, settings)
        await js.publish(
            settings.nats_subject,
            message_body(task_id),
            headers=headers,
            timeout=2,
            stream=settings.nats_stream,
        )
    finally:
        await client.close()


def _run(coro: Coroutine[object, object, None]) -> None:
    """Run a coroutine from a sync route. A thread avoids nesting event loops."""
    with ThreadPoolExecutor(max_workers=1) as pool:
        pool.submit(asyncio.run, coro).result()


def _mark_unpublished(task_id: UUID) -> None:
    """Leave the bytes on disk and the task failed so retry can publish again."""
    factory = make_session_factory(make_engine())
    with factory() as session:
        try:
            transition_status(session, task_id, ("pending",), "failed", failure_reason="publish_failed")
            session.commit()
        except ApiError:
            session.rollback()
