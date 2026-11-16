"""Decode one JetStream delivery and ack or nak from the handler result.

The handler does not sleep. JetStream applies the 2, 4, 8 second backoff after a nak.
"""

import asyncio
import json
import logging
from uuid import UUID

from nats.aio.msg import Msg
from opentelemetry.context import attach, detach
from opentelemetry.propagate import extract

from app.core.config import get_settings
from worker.handler import handle_import

logger = logging.getLogger(__name__)


async def handle_message(msg: Msg) -> None:
    """Call the import handler and acknowledge only when it says ack.

    num_delivered is the attempt count. A payload that is not a task id is acknowledged
    so JetStream does not redeliver it forever.
    """
    try:
        task_id = UUID(json.loads(msg.data.decode())["taskId"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        logger.warning("Dropping a delivery that has no task id.")
        await msg.ack()
        return
    settings = get_settings()
    token = attach(extract(_carrier(msg)))
    try:
        result = await asyncio.to_thread(
            handle_import,
            task_id,
            attempt=msg.metadata.num_delivered,
            max_deliver=settings.nats_max_deliver,
        )
    finally:
        detach(token)
    if result.action == "ack":
        await msg.ack()
        return
    await msg.nak()


def _carrier(msg: Msg) -> dict[str, str]:
    """Header values as strings so the W3C propagator can read traceparent."""
    raw = msg.headers or {}
    return {str(key): str(value) for key, value in raw.items()}
