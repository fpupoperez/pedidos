"""Read and control import tasks."""

from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path as PathParam, Query
from fastapi.responses import FileResponse

from app.core.config import get_settings
from app.db.session import make_engine, make_session_factory
from app.schemas.auth import SessionAuth
from app.schemas.envelope import error_responses
from app.schemas.tasks import RejectionListQuery, RejectionPageResponse, TaskListQuery, TaskPageResponse, TaskResponse
from app.services.storage import stored_file
from app.services.tasks import cancel_task, get_task, list_rejections, list_tasks, retry_task, task_data
from app.nats.publisher import deliver

router = APIRouter(prefix="/tasks", tags=["Tasks"])


def _session():
    """One session for a single request."""
    factory = make_session_factory(make_engine())
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def task_list_query(
    limit: Annotated[int, Query(ge=1, le=200, description="Page size. Maximum 200.")] = 50,
    offset: Annotated[int, Query(ge=0, description="Number of matching tasks to skip.")] = 0,
    status: Annotated[str | None, Query(description="When set, only tasks in this status are returned.")] = None,
) -> TaskListQuery:
    """Build the documented list query."""
    return TaskListQuery(limit=limit, offset=offset, status=status)


def rejection_list_query(
    limit: Annotated[int, Query(ge=1, le=200, description="Page size. Maximum 200.")] = 50,
    offset: Annotated[int, Query(ge=0, description="Number of rejection rows to skip.")] = 0,
) -> RejectionListQuery:
    """Build the documented rejection query."""
    return RejectionListQuery(limit=limit, offset=offset)


@router.get(
    "",
    operation_id="list_tasks",
    summary="List import tasks",
    response_model=TaskPageResponse,
    responses={200: {"model": TaskPageResponse, "description": "One page of tasks."}, **error_responses(422, 500)},
)
def list_tasks_route(query: Annotated[TaskListQuery, Depends(task_list_query)], session=Depends(_session)) -> TaskPageResponse:
    """List tasks, newest first.

    This operation has no JSON body. offset skips that many matching rows.
    """
    page = list_tasks(session, limit=query.limit, offset=query.offset, status=query.status)
    return TaskPageResponse(session_auth=SessionAuth(), errors=[], success=True, data=page)


@router.get(
    "/{taskId}",
    operation_id="get_task",
    summary="Read one import task",
    response_model=TaskResponse,
    responses={200: {"model": TaskResponse, "description": "The task and its summary."}, **error_responses(404, 422, 500)},
)
def get_task_route(
    taskId: Annotated[UUID, PathParam(description="Id returned by create_import.", examples=["00000000-0000-0000-0000-0000000000aa"])],
    session=Depends(_session),
) -> TaskResponse:
    """Return one task, including the summary and the link to the original file.

    This operation has no JSON body. An unknown id is 404. Do not retry it unchanged.
    """
    return TaskResponse(session_auth=SessionAuth(), errors=[], success=True, data=task_data(get_task(session, taskId)))


@router.get(
    "/{taskId}/rejections",
    operation_id="list_task_rejections",
    summary="List CSV lines that were not imported",
    response_model=RejectionPageResponse,
    responses={200: {"model": RejectionPageResponse, "description": "One page of rejected lines."}, **error_responses(404, 422, 500)},
)
def list_rejections_route(
    taskId: Annotated[UUID, PathParam(description="Id returned by create_import.")],
    query: Annotated[RejectionListQuery, Depends(rejection_list_query)],
    session=Depends(_session),
) -> RejectionPageResponse:
    """Return the rejected lines for one task.

    The rows stay after cancel and after completion. This operation has no JSON body.
    """
    page = list_rejections(session, taskId, limit=query.limit, offset=query.offset)
    return RejectionPageResponse(session_auth=SessionAuth(), errors=[], success=True, data=page)


@router.post(
    "/{taskId}/cancel",
    operation_id="cancel_task",
    summary="Cancel a task that has not finished",
    response_model=TaskResponse,
    responses={200: {"model": TaskResponse, "description": "The task is cancelled."}, **error_responses(404, 409, 422, 500)},
)
def cancel_task_route(
    taskId: Annotated[UUID, PathParam(description="Id returned by create_import.")],
    session=Depends(_session),
) -> TaskResponse:
    """Cancel a pending or processing task.

    This operation has no JSON body. A completed, failed, or cancelled task is 409.
    Do not retry 409 unchanged.
    """
    task = cancel_task(session, taskId)
    return TaskResponse(session_auth=SessionAuth(), errors=[], success=True, data=task_data(task))


@router.post(
    "/{taskId}/retry",
    status_code=202,
    operation_id="retry_task",
    summary="Publish a failed or stale task again",
    response_model=TaskResponse,
    responses={202: {"model": TaskResponse, "description": "The task is pending again."}, **error_responses(404, 409, 422, 500, 502)},
)
def retry_task_route(
    taskId: Annotated[UUID, PathParam(description="Id returned by create_import.")],
    session=Depends(_session),
) -> TaskResponse:
    """Retry a publish failure, an exhausted delivery, or a processing task older than the ack wait.

    This operation has no JSON body. A permanent file failure is 409. Do not retry that unchanged.
    """
    settings = get_settings()
    task = retry_task(session, taskId, ack_wait_seconds=settings.ack_wait_seconds)
    session.commit()
    deliver(task.id)
    session.expire_all()
    task = get_task(session, task.id)
    return TaskResponse(session_auth=SessionAuth(), errors=[], success=True, data=task_data(task))


@router.get(
    "/{taskId}/file",
    operation_id="download_task_file",
    summary="Download the original CSV",
    response_class=FileResponse,
    responses={
        200: {"content": {"text/csv": {}}, "description": "The original file bytes, not the JSON envelope."},
        **error_responses(404, 500),
    },
)
def download_task_file(
    taskId: Annotated[UUID, PathParam(description="Id returned by create_import.")],
    session=Depends(_session),
) -> FileResponse:
    """Return the original CSV.

    The body is the file. A path outside the uploads directory is 404, the same as a missing task.
    Do not retry 404 unchanged.
    """
    task = get_task(session, taskId)
    path: Path = stored_file(get_settings(), task.storage_path)
    filename = task.filename.replace('"', "").replace("\n", "").replace("\r", "")
    return FileResponse(path, media_type="text/csv", filename=filename)
