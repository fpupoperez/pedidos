"""Accept a CSV import."""

from typing import Annotated

from fastapi import APIRouter, File, UploadFile

from app.core.errors import ApiError
from app.schemas.auth import SessionAuth
from app.schemas.envelope import error_responses
from app.schemas.tasks import TaskResponse
from app.services.imports import create_import
from app.services.tasks import task_data

router = APIRouter(prefix="/imports", tags=["Imports"])


@router.post(
    "",
    status_code=202,
    operation_id="create_import",
    summary="Accept a CSV and start an import task",
    response_model=TaskResponse,
    responses={
        202: {"model": TaskResponse, "description": "The task was stored. Poll get_task until it is terminal."},
        **error_responses(400, 409, 413, 422, 500, 502),
    },
)
async def create_import_route(
    file: Annotated[UploadFile | None, File(description="CSV file. The field name is file.")] = None,
) -> TaskResponse:
    """Store a CSV and import it.

    Inline delivery finishes before this response, and the task status is already terminal.
    The HTTP status stays 202. A repeated file hash returns 409 and names the existing task.
    Do not retry 400, 409, or 413 until the file changes.
    """
    if file is None:
        raise ApiError(400, "The file field is required.")
    raw = await file.read()
    task = create_import(file.filename, file.content_type, raw)
    return TaskResponse(session_auth=SessionAuth(), errors=[], success=True, data=task_data(task))
