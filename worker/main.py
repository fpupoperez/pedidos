"""Push consumer process. One replica holds one file at a time."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import asyncio
import signal

import nats

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.core.telemetry import configure_telemetry
from app.nats.stream import consumer_config, ensure_stream
from worker.consumer import handle_message


async def serve(stop: asyncio.Event | None = None) -> None:
    """Connect, ensure the stream and the queue consumer, and wait until stopped."""
    settings = get_settings()
    if not settings.nats_url:
        raise RuntimeError("NATS_URL is required when the worker starts.")
    client = await nats.connect(settings.nats_url, connect_timeout=2)
    try:
        js = client.jetstream()
        await ensure_stream(js, settings)
        await js.subscribe(
            settings.nats_subject,
            queue=settings.nats_worker,
            durable=settings.nats_worker,
            stream=settings.nats_stream,
            config=consumer_config(settings),
            cb=handle_message,
            manual_ack=True,
        )
        if stop is None:
            stop = asyncio.Event()
            loop = asyncio.get_running_loop()
            for sig in (signal.SIGINT, signal.SIGTERM):
                loop.add_signal_handler(sig, stop.set)
        await stop.wait()
    finally:
        await client.drain()


def main() -> None:
    """Configure logs and traces, then consume until the process is stopped."""
    settings = get_settings()
    configure_logging("orders-worker")
    configure_telemetry(settings, "orders-worker")
    asyncio.run(serve())


if __name__ == "__main__":
    main()
