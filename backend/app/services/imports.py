"""Accept a CSV, store it, and hand the task to inline delivery."""

import hashlib
from uuid import uuid4

from sqlalchemy.exc import IntegrityError

from app.core.config import get_settings
from app.core.errors import ApiError
from app.core.telemetry import span
from app.db.models import EMPTY_SUMMARY, TaskRow
from app.db.session import make_engine, make_session_factory
from app.services.storage import uploads_root
from app.services.tasks import current_trace_id, find_active_hash, get_task


def create_import(filename: str | None, content_type: str | None, raw: bytes) -> TaskRow:
    """Store one CSV and run the import when delivery is inline.

    The HTTP status stays 202. Inline delivery finishes before this returns,
    so the task status in the response is already terminal.
    """
    _validate_upload(filename, content_type, raw)
    name = filename or "orders.csv"
    settings = get_settings()
    digest = hashlib.sha256(raw).hexdigest()
    factory = make_session_factory(make_engine())
    with span("import.accept"):
        with factory() as session:
            existing = find_active_hash(session, digest)
            if existing is not None:
                raise ApiError(409, f"This file is already imported as task {existing.id}.")
            task_id = uuid4()
            relative = f"uploads/{task_id}.csv"
            destination = uploads_root(settings) / f"{task_id}.csv"
            destination.write_bytes(raw)
            task = TaskRow(
                id=task_id,
                status="pending",
                filename=name,
                storage_path=relative,
                content_hash=digest,
                summary=dict(EMPTY_SUMMARY),
                trace_id=current_trace_id(),
            )
            with span("task.insert", task_id=str(task_id)):
                session.add(task)
                try:
                    session.commit()
                except IntegrityError:
                    session.rollback()
                    winner = find_active_hash(session, digest)
                    if winner is None:
                        raise
                    raise ApiError(409, f"This file is already imported as task {winner.id}.") from None
        from app.nats.publisher import deliver

        with span("nats.publish", task_id=str(task_id)):
            deliver(task_id)
        with factory() as session:
            return get_task(session, task_id)


def _validate_upload(filename: str | None, content_type: str | None, raw: bytes) -> None:
    """Reject a missing, empty, oversized, or non-CSV upload before a task exists."""
    if not filename and not content_type:
        raise ApiError(400, "The file field is required.")
    settings = get_settings()
    if len(raw) > settings.max_upload_bytes:
        raise ApiError(413, "The file is larger than the configured limit.")
    if not raw:
        raise ApiError(400, "The file is empty.")
    suffix_ok = bool(filename and filename.lower().endswith(".csv"))
    type_ok = content_type in {"text/csv", "application/csv"}
    if not suffix_ok and not type_ok:
        raise ApiError(400, "The file must be a CSV.")
    try:
        raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ApiError(400, "The file must be UTF-8.") from exc
