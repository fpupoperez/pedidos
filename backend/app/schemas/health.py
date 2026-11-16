"""Liveness response."""

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.auth import SessionAuth
from app.schemas.envelope import ApiErrorBody


class HealthData(BaseModel):
    """Process liveness. This does not check Postgres or NATS."""

    model_config = ConfigDict(extra="forbid", title="HealthData")

    status: str = Field(description="ok when the API process is serving requests.", examples=["ok"])


class HealthResponse(BaseModel):
    """Envelope around process liveness."""

    model_config = ConfigDict(
        extra="forbid",
        title="HealthResponse",
        json_schema_extra={
            "examples": [
                {"session_auth": {}, "errors": [], "success": True, "data": {"status": "ok"}}
            ]
        },
    )

    session_auth: SessionAuth = Field(description="Caller identity for this call. Empty when auth is off.")
    errors: list[ApiErrorBody] = Field(default_factory=list, description="Empty when success is true.")
    success: bool = Field(description="True when the process is running.", examples=[True])
    data: HealthData = Field(description="Liveness payload.")
