"""The one JetStream stream shared by the API and the worker."""

import json
from uuid import UUID

from nats.js import api
from nats.js.client import JetStreamContext
from nats.js.errors import NotFoundError
from opentelemetry.propagate import inject

from app.core.config import Settings

DELIVER_SUBJECT = "deliver_orders_import"
BACKOFF_SECONDS = [2.0, 4.0, 8.0]
DUPLICATE_WINDOW_SECONDS = 120.0
MAX_AGE_SECONDS = 7 * 24 * 3600


def stream_config(settings: Settings) -> api.StreamConfig:
    """Limits retention, file storage, a 7 day age, and a 2 minute duplicate window."""
    return api.StreamConfig(
        name=settings.nats_stream,
        subjects=["orders.>"],
        retention=api.RetentionPolicy.LIMITS,
        storage=api.StorageType.FILE,
        max_age=MAX_AGE_SECONDS,
        duplicate_window=DUPLICATE_WINDOW_SECONDS,
    )


def consumer_config(settings: Settings) -> api.ConsumerConfig:
    """Push consumer. The queue name, durable name, and deliver group are the same."""
    return api.ConsumerConfig(
        durable_name=settings.nats_worker,
        deliver_subject=DELIVER_SUBJECT,
        deliver_group=settings.nats_worker,
        deliver_policy=api.DeliverPolicy.ALL,
        ack_policy=api.AckPolicy.EXPLICIT,
        ack_wait=float(settings.ack_wait_seconds),
        max_ack_pending=1,
        max_deliver=settings.nats_max_deliver,
        backoff=list(BACKOFF_SECONDS),
        filter_subject=settings.nats_subject,
    )


async def ensure_stream(js: JetStreamContext, settings: Settings) -> None:
    """Create the stream when it is missing. An existing stream is left as the server has it."""
    try:
        await js.stream_info(settings.nats_stream)
    except NotFoundError:
        await js.add_stream(config=stream_config(settings))


def message_body(task_id: UUID) -> bytes:
    """The only field a delivery carries is the task id."""
    return json.dumps({"taskId": str(task_id)}).encode()


def message_headers(task_id: UUID) -> dict[str, str]:
    """W3C trace headers from the current span, plus the task id as the JetStream dedupe key."""
    headers: dict[str, str] = {}
    inject(headers)
    headers["Nats-Msg-Id"] = str(task_id)
    return headers
