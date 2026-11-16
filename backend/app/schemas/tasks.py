"""Task request and response models."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.auth import SessionAuth
from app.schemas.envelope import ApiErrorBody

_TASK = "00000000-0000-0000-0000-0000000000aa"


class TaskSummary(BaseModel):
    """Counts for one file. phase is copied from the task status when the response is built."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True, title="TaskSummary")

    phase: str = Field(description="pending, importing, completed, failed, or cancelled.", examples=["completed"])
    total_rows: int = Field(alias="totalRows", description="Data rows in the file, header excluded.", examples=[4])
    processed_rows: int = Field(alias="processedRows", description="Rows cleaned. Stays at totalRows after cleaning.", examples=[4])
    staged_rows: int = Field(alias="stagedRows", description="Accepted rows visible only after the insert commits.", examples=[3])
    accepted_rows: int = Field(alias="acceptedRows", description="Rows that passed validation and were not duplicates.", examples=[3])
    imported_rows: int = Field(alias="importedRows", description="Rows committed in orders. Zero until the insert commits.", examples=[3])
    duplicate_rows: int = Field(alias="duplicateRows", description="Extra copies. The first copy stays accepted.", examples=[1])
    invalid_rows: int = Field(alias="invalidRows", description="Rows rejected for a broken value.", examples=[0])
    rejected_rows: int = Field(alias="rejectedRows", description="duplicateRows plus invalidRows.", examples=[1])
    by_reason: dict[str, int] = Field(alias="byReason", description="Rejection reason to count. Zero counts are omitted.", examples=[{"duplicate": 1}])
    cleaned: bool = Field(description="True after the rejection rows and these counts are committed.", examples=[True])


class TaskData(BaseModel):
    """One import task and its summary."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True, title="TaskData")

    task_id: UUID = Field(alias="taskId", description="Id returned by create_import.", examples=[_TASK])
    status: str = Field(description="pending, processing, completed, failed, or cancelled.", examples=["completed"])
    filename: str = Field(description="Original file name.", examples=["orders.csv"])
    source_file: str = Field(alias="sourceFile", description="Relative URL of the original CSV.", examples=[f"/api/v1/tasks/{_TASK}/file"])
    failure_reason: str | None = Field(alias="failureReason", description="Why the task failed. Null unless status is failed.", examples=[None])
    trace_id: str | None = Field(alias="traceId", description="Trace id of import.accept. Set once.", examples=["a" * 32])
    summary: TaskSummary = Field(description="File counts. phase follows status.")
    created_at: datetime = Field(alias="createdAt", description="When the task was created, UTC.")
    updated_at: datetime = Field(alias="updatedAt", description="When the task last changed, UTC.")


class TaskResponse(BaseModel):
    """Envelope around one task."""

    model_config = ConfigDict(extra="forbid", title="TaskResponse")

    session_auth: SessionAuth = Field(description="Caller identity for this call.")
    errors: list[ApiErrorBody] = Field(default_factory=list, description="Empty when success is true.")
    success: bool = Field(description="True when the task was read or changed.", examples=[True])
    data: TaskData = Field(description="The task.")


class TaskPage(BaseModel):
    """One page of tasks. count is the full match size."""

    model_config = ConfigDict(extra="forbid", title="TaskPage")

    next: str | None = Field(description="Query string of the next page, including the leading ?. Null on the last page.", examples=["?limit=50&offset=50"])
    count: int = Field(description="Number of tasks that match, including other pages.", examples=[1])
    objects: list[TaskData] = Field(description="Tasks on this page.")


class TaskPageResponse(BaseModel):
    """Envelope around a page of tasks."""

    model_config = ConfigDict(extra="forbid", title="TaskPageResponse")

    session_auth: SessionAuth = Field(description="Caller identity for this call.")
    errors: list[ApiErrorBody] = Field(default_factory=list, description="Empty when success is true.")
    success: bool = Field(description="True when the page was read.", examples=[True])
    data: TaskPage = Field(description="The page.")


class RejectionData(BaseModel):
    """One CSV line that was not imported."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True, title="RejectionData")

    source_line: int = Field(alias="sourceLine", description="1-based line number in the original file.", examples=[3])
    reason: str = Field(description="Why the line was rejected.", examples=["invalid_date"])
    raw: str = Field(description="The original CSV line.", examples=["32/13/2024,Ana,España,Teclado,10,pagado"])


class RejectionPage(BaseModel):
    """One page of rejection rows."""

    model_config = ConfigDict(extra="forbid", title="RejectionPage")

    next: str | None = Field(description="Query string of the next page. Null on the last page.", examples=[None])
    count: int = Field(description="Number of rejection rows for this task.", examples=[1])
    objects: list[RejectionData] = Field(description="Rejection rows on this page.")


class RejectionPageResponse(BaseModel):
    """Envelope around a page of rejection rows."""

    model_config = ConfigDict(extra="forbid", title="RejectionPageResponse")

    session_auth: SessionAuth = Field(description="Caller identity for this call.")
    errors: list[ApiErrorBody] = Field(default_factory=list, description="Empty when success is true.")
    success: bool = Field(description="True when the page was read.", examples=[True])
    data: RejectionPage = Field(description="The page.")


class TaskIdPath(BaseModel):
    """Task id taken from the path."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True, title="TaskIdPath")

    task_id: UUID = Field(alias="taskId", description="Id returned by create_import.", examples=[_TASK])


class TaskListQuery(BaseModel):
    """Filters for list_tasks. offset is the number of rows to skip."""

    model_config = ConfigDict(extra="forbid", title="TaskListQuery")

    limit: int = Field(default=50, ge=1, le=200, description="Page size. Maximum 200.", examples=[50])
    offset: int = Field(default=0, ge=0, description="Number of matching tasks to skip.", examples=[0])
    status: str | None = Field(default=None, description="When set, only tasks in this status are returned.", examples=["completed"])


class RejectionListQuery(BaseModel):
    """Page controls for list_task_rejections."""

    model_config = ConfigDict(extra="forbid", title="RejectionListQuery")

    limit: int = Field(default=50, ge=1, le=200, description="Page size. Maximum 200.", examples=[50])
    offset: int = Field(default=0, ge=0, description="Number of rejection rows to skip.", examples=[0])
