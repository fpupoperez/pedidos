"""Task status changes. Every write locks the row with SELECT FOR UPDATE."""

from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
from uuid import UUID

from opentelemetry import trace
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.core.telemetry import record_task, span
from app.db.models import EMPTY_SUMMARY, ImportRejectionRow, TaskRow
from app.schemas.tasks import RejectionData, RejectionPage, TaskData, TaskPage, TaskSummary

ACTIVE_STATUSES = ("pending", "processing", "completed")
RETRYABLE = ("publish_failed", "retries_exhausted")
PERMANENT = ("invalid_header", "file_missing", "file_unreadable", "summary_mismatch")


class Transition:
    """The locked task and whether this call changed it."""

    def __init__(self, task: TaskRow, changed: bool) -> None:
        self.task = task
        self.changed = changed


def transition_status(
    session: Session,
    task_id: UUID,
    allowed_from: tuple[str, ...],
    new_status: str,
    **fields: object,
) -> Transition:
    """Lock the task and apply one status change.

    A caller that loses the race gets the row back unchanged and changed=False.
    The caller maps that to 409. The worker acknowledges and does no further write.
    """
    task = session.execute(select(TaskRow).where(TaskRow.id == task_id).with_for_update()).scalar_one_or_none()
    if task is None:
        raise ApiError(404, "Task not found")
    previous = task.status
    allowed = previous in allowed_from
    with span("task.transition", task_id=str(task_id)) as current:
        current.set_attribute("from", previous)
        current.set_attribute("to", new_status if allowed else previous)
        current.set_attribute("unchanged", not allowed)
        current.add_event(
            "task.status",
            {"from": previous, "to": new_status if allowed else previous, "task_id": str(task_id), "unchanged": not allowed},
        )
        if not allowed:
            return Transition(task, False)
        task.status = new_status
        task.updated_at = datetime.now(timezone.utc)
        for name, value in fields.items():
            setattr(task, name, value)
        session.flush()
    record_task(new_status)
    return Transition(task, True)


def source_file(task_id: UUID) -> str:
    """Relative URL of the original CSV for this task."""
    return f"/api/v1/tasks/{task_id}/file"


def phase_for(status: str) -> str:
    """The summary phase. processing is shown as importing."""
    if status == "processing":
        return "importing"
    return status


def task_data(task: TaskRow) -> TaskData:
    """Build the response model. phase comes from status, not from the stored JSON."""
    stored = dict(EMPTY_SUMMARY)
    stored.update(task.summary or {})
    stored.pop("phase", None)
    stored["phase"] = phase_for(task.status)
    summary = TaskSummary.model_validate(stored)
    return TaskData(
        task_id=task.id,
        status=task.status,
        filename=task.filename,
        source_file=source_file(task.id),
        failure_reason=task.failure_reason,
        trace_id=task.trace_id,
        summary=summary,
        created_at=task.created_at,
        updated_at=task.updated_at,
    )


def get_task(session: Session, task_id: UUID) -> TaskRow:
    """Return one task or raise 404."""
    task = session.get(TaskRow, task_id)
    if task is None:
        raise ApiError(404, "Task not found")
    return task


def list_tasks(session: Session, *, limit: int, offset: int, status: str | None) -> TaskPage:
    """Return one page of tasks, newest first."""
    query: Select[tuple[TaskRow]] = select(TaskRow)
    count_query = select(func.count()).select_from(TaskRow)
    if status:
        query = query.where(TaskRow.status == status)
        count_query = count_query.where(TaskRow.status == status)
    count = int(session.scalar(count_query) or 0)
    rows = session.scalars(query.order_by(TaskRow.created_at.desc()).limit(limit).offset(offset)).all()
    extra = {"status": status} if status else {}
    return TaskPage(next=_next(limit, offset, count, extra), count=count, objects=[task_data(row) for row in rows])


def list_rejections(session: Session, task_id: UUID, *, limit: int, offset: int) -> RejectionPage:
    """Return one page of rejection rows. A missing task is 404."""
    get_task(session, task_id)
    count = int(
        session.scalar(select(func.count()).select_from(ImportRejectionRow).where(ImportRejectionRow.task_id == task_id))
        or 0
    )
    rows = session.scalars(
        select(ImportRejectionRow)
        .where(ImportRejectionRow.task_id == task_id)
        .order_by(ImportRejectionRow.source_line)
        .limit(limit)
        .offset(offset)
    ).all()
    objects = [RejectionData(source_line=row.source_line, reason=row.reason, raw=row.raw) for row in rows]
    return RejectionPage(next=_next(limit, offset, count, {}), count=count, objects=objects)


def cancel_task(session: Session, task_id: UUID) -> TaskRow:
    """Cancel a task that has not finished. A finished task returns 409."""
    result = transition_status(session, task_id, ("pending", "processing"), "cancelled", failure_reason=None)
    if not result.changed:
        raise ApiError(409, f"Task {task_id} cannot be cancelled from status {result.task.status}.")
    return result.task


def retry_task(session: Session, task_id: UUID, *, ack_wait_seconds: int) -> TaskRow:
    """Move a failed publish, an exhausted delivery, or a stale processing task back to pending.

    A processing task newer than ack_wait stays put because a handler may still hold it.
    Permanent file failures stay failed.
    """
    task = session.execute(select(TaskRow).where(TaskRow.id == task_id).with_for_update()).scalar_one_or_none()
    if task is None:
        raise ApiError(404, "Task not found")
    stale = _is_stale(task, ack_wait_seconds)
    retryable = task.status == "failed" and task.failure_reason in RETRYABLE
    if not retryable and not (task.status == "processing" and stale):
        raise ApiError(409, f"Task {task_id} cannot be retried from status {task.status}.")
    task.status = "pending"
    task.failure_reason = None
    task.updated_at = datetime.now(timezone.utc)
    session.flush()
    record_task("pending")
    return task


def find_active_hash(session: Session, content_hash: str) -> TaskRow | None:
    """The pending, processing, or completed task that already owns this file hash."""
    return session.scalar(
        select(TaskRow).where(TaskRow.content_hash == content_hash, TaskRow.status.in_(ACTIVE_STATUSES)).limit(1)
    )


def current_trace_id() -> str | None:
    """Hex trace id of the current span, or None when there is no recording span."""
    context = trace.get_current_span().get_span_context()
    if not context.trace_id:
        return None
    return format(context.trace_id, "032x")


def _is_stale(task: TaskRow, ack_wait_seconds: int) -> bool:
    """True when the row has not been touched within the JetStream ack wait."""
    updated = task.updated_at
    if updated.tzinfo is None:
        updated = updated.replace(tzinfo=timezone.utc)
    return updated <= datetime.now(timezone.utc) - timedelta(seconds=ack_wait_seconds)


def _next(limit: int, offset: int, count: int, extra: dict[str, str]) -> str | None:
    """The next page query string, or None when this page is the last."""
    following = offset + limit
    if following >= count:
        return None
    query = {"limit": str(limit), "offset": str(following)}
    query.update({key: value for key, value in extra.items() if value})
    return "?" + urlencode(query)
