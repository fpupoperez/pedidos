"""Import one task. The API calls this inline. The NATS callback will call it too.

A database outage returns nak and leaves the status unchanged so JetStream can redeliver.
A bad file is stored as failed and acknowledged, so it is not retried.
"""

import time
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.core.errors import ApiError
from app.core.logging import bind_task
from app.core.telemetry import record_import_duration, record_import_rows, span
from app.db.models import EMPTY_SUMMARY, ImportRejectionRow, OrderRow, TaskRow
from app.db.session import make_engine, make_session_factory
from app.services.cleaning import CleanError, CleanResult, clean_orders
from app.services.storage import stored_file
from app.services.tasks import transition_status

TERMINAL = ("completed", "cancelled", "failed")


@dataclass
class HandleResult:
    """What the caller tells JetStream. inline delivery ignores nak."""

    action: str


def before_batch(task_id: UUID) -> None:
    """Tests replace this to cancel between batches. The default does nothing."""
    return None


def handle_import(task_id: UUID, *, attempt: int = 1, max_deliver: int = 4) -> HandleResult:
    """Clean a stored CSV and commit its orders, or acknowledge a task that is already finished."""
    started = time.perf_counter()
    with bind_task(str(task_id)), span("import.handle", task_id=str(task_id)):
        try:
            return _run(task_id, attempt=attempt, max_deliver=max_deliver, started=started)
        except OperationalError:
            if attempt >= max_deliver and _fail_quietly(task_id, "retries_exhausted"):
                return HandleResult("ack")
            return HandleResult("nak")


def _run(task_id: UUID, *, attempt: int, max_deliver: int, started: float) -> HandleResult:
    """Claim the task, clean when needed, and insert accepted rows."""
    settings = get_settings()
    factory = make_session_factory(make_engine())
    with factory() as session:
        try:
            claimed = transition_status(session, task_id, ("pending", "processing"), "processing")
        except ApiError:
            return HandleResult("ack")
        if not claimed.changed and claimed.task.status in TERMINAL:
            session.rollback()
            return HandleResult("ack")
        session.commit()
        task = claimed.task
    path = _read_path(task)
    if isinstance(path, HandleResult):
        return path
    if not bool(task.summary.get("cleaned")):
        cleaned = _clean_and_store(factory, task_id, path)
        if isinstance(cleaned, HandleResult):
            return cleaned
        result = cleaned
    else:
        result = clean_orders(path.read_text(encoding="utf-8"))
    outcome = _insert(factory, task_id, result, settings.import_batch_size)
    if outcome.action == "ack":
        record_import_duration((time.perf_counter() - started) * 1000)
    return outcome


def _read_path(task: TaskRow) -> Path | HandleResult:
    """Open the stored file. A missing or escaped path is a permanent failure."""
    settings = get_settings()
    try:
        return stored_file(settings, task.storage_path)
    except ApiError:
        _fail(task.id, "file_missing")
        return HandleResult("ack")


def _clean_and_store(factory: sessionmaker[Session], task_id: UUID, path: Path) -> CleanResult | HandleResult:
    """Parse the file once and commit the counts and the rejection rows."""
    try:
        text_value = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        _fail(task_id, "file_unreadable")
        return HandleResult("ack")
    try:
        with span("import.clean", task_id=str(task_id)):
            result = clean_orders(text_value)
    except CleanError:
        _fail(task_id, "invalid_header")
        return HandleResult("ack")
    if result.total_rows != result.accepted_rows + result.rejected_rows:
        _fail(task_id, "summary_mismatch")
        return HandleResult("ack")
    summary = _summary(result, imported=0, staged=0, cleaned=True)
    with factory() as session:
        task = session.get(TaskRow, task_id)
        if task is None or task.status == "cancelled":
            return HandleResult("ack")
        task.summary = summary
        session.add_all(
            [
                ImportRejectionRow(id=uuid4(), task_id=task_id, source_line=row.source_line, reason=row.reason, raw=row.raw)
                for row in result.rejections
            ]
        )
        session.commit()
    record_import_rows("accepted", result.accepted_rows)
    record_import_rows("rejected", result.invalid_rows)
    record_import_rows("duplicate", result.duplicate_rows)
    return result


def _insert(factory: sessionmaker[Session], task_id: UUID, result: CleanResult, batch_size: int) -> HandleResult:
    """Insert accepted rows under an advisory lock. Cancel between batches rolls the insert back."""
    with factory() as session:
        keys = _advisory_keys(task_id)
        session.execute(text("SELECT pg_advisory_xact_lock(:hi, :lo)"), {"hi": keys[0], "lo": keys[1]})
        session.execute(text("DELETE FROM orders WHERE task_id = :task_id"), {"task_id": task_id})
        accepted = result.accepted
        for start in range(0, len(accepted), batch_size):
            with span("import.batch", task_id=str(task_id)):
                before_batch(task_id)
                if _is_cancelled(task_id):
                    session.rollback()
                    _clear_imported(task_id)
                    return HandleResult("ack")
                for row in accepted[start : start + batch_size]:
                    session.add(
                        OrderRow(
                            id=uuid4(),
                            task_id=task_id,
                            order_date=row.order_date.date(),
                            customer=row.customer,
                            country=row.country,
                            product=row.product,
                            amount=row.amount,
                            status=row.status,
                            source_line=row.source_line,
                        )
                    )
        finished = transition_status(
            session,
            task_id,
            ("processing",),
            "completed",
            summary=_summary(result, imported=result.accepted_rows, staged=result.accepted_rows, cleaned=True),
            failure_reason=None,
        )
        if not finished.changed:
            session.rollback()
            _clear_imported(task_id)
            return HandleResult("ack")
        session.commit()
    return HandleResult("ack")


def _is_cancelled(task_id: UUID) -> bool:
    """Lock the task on a short connection so a cancel can commit while the insert stays open."""
    factory = make_session_factory(make_engine())
    with factory() as session:
        task = session.execute(select(TaskRow).where(TaskRow.id == task_id).with_for_update()).scalar_one_or_none()
        cancelled = task is not None and task.status == "cancelled"
        session.commit()
    return cancelled


def _clear_imported(task_id: UUID) -> None:
    """A rolled-back insert leaves importedRows at zero. The file counts stay."""
    factory = make_session_factory(make_engine())
    with factory() as session:
        task = session.get(TaskRow, task_id)
        if task is None:
            return
        summary = dict(task.summary)
        summary["importedRows"] = 0
        summary["stagedRows"] = 0
        task.summary = summary
        session.commit()


def _fail(task_id: UUID, reason: str) -> None:
    """Store a permanent failure and leave the message to be acknowledged."""
    factory = make_session_factory(make_engine())
    with factory() as session:
        try:
            transition_status(session, task_id, ("pending", "processing"), "failed", failure_reason=reason)
            session.commit()
        except ApiError:
            session.rollback()


def _fail_quietly(task_id: UUID, reason: str) -> bool:
    """The last transient attempt. False means the database is still down and the caller naks."""
    try:
        _fail(task_id, reason)
    except OperationalError:
        return False
    return True


def _summary(result: CleanResult, *, imported: int, staged: int, cleaned: bool) -> dict[str, object]:
    """The stored summary. phase is not included."""
    summary = dict(EMPTY_SUMMARY)
    summary.update(
        {
            "totalRows": result.total_rows,
            "processedRows": result.total_rows,
            "stagedRows": staged,
            "acceptedRows": result.accepted_rows,
            "importedRows": imported,
            "duplicateRows": result.duplicate_rows,
            "invalidRows": result.invalid_rows,
            "rejectedRows": result.rejected_rows,
            "byReason": result.by_reason(),
            "cleaned": cleaned,
        }
    )
    return summary


def _advisory_keys(task_id: UUID) -> tuple[int, int]:
    """Two positive int4 keys for pg_advisory_xact_lock. The lock dies with the transaction."""
    raw = task_id.int
    return (raw >> 96) & 0x7FFFFFFF, raw & 0x7FFFFFFF
