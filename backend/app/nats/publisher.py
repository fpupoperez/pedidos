"""Hand a committed task to the worker.

inline runs the handler in this process. jetstream is connected in a later step.
A publish failure is stored on the task so the caller can retry it.
"""

from uuid import UUID

from app.core.config import get_settings
from app.core.errors import ApiError
from app.core.telemetry import record_publish
from app.db.session import make_engine, make_session_factory
from app.services.tasks import transition_status
from worker.handler import handle_import


def deliver(task_id: UUID) -> None:
    """Run the import now, or record publish_failed when JetStream is selected and not connected."""
    settings = get_settings()
    if settings.nats_delivery == "inline":
        handle_import(task_id)
        record_publish("ok")
        return
    _mark_unpublished(task_id)
    record_publish("error")
    raise ApiError(502, "The import could not be published.")


def _mark_unpublished(task_id: UUID) -> None:
    """Leave the bytes on disk and the task failed so retry can publish again."""
    factory = make_session_factory(make_engine())
    with factory() as session:
        try:
            transition_status(session, task_id, ("pending",), "failed", failure_reason="publish_failed")
            session.commit()
        except ApiError:
            session.rollback()
