"""Response envelope documented for OpenAPI and a future MCP client."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.auth import SessionAuth


class ApiErrorBody(BaseModel):
    """One failure. Read msg and change the request before calling the operation again."""

    model_config = ConfigDict(extra="forbid", title="ApiError")

    code: int = Field(
        description="HTTP status that also accompanies this error.",
        examples=[400],
    )
    msg: str = Field(
        description="Human-readable reason. This is the text an agent should surface or correct.",
        examples=["Task not found"],
    )


class ErrorResponse(BaseModel):
    """Failure envelope. success is false and data is null.

    Do not look for a top-level detail key.
    """

    model_config = ConfigDict(
        extra="forbid",
        title="ErrorResponse",
        json_schema_extra={
            "examples": [
                {
                    "session_auth": {},
                    "errors": [{"code": 404, "msg": "Task not found"}],
                    "success": False,
                    "data": None,
                }
            ]
        },
    )

    session_auth: SessionAuth = Field(
        default_factory=SessionAuth,
        description="The session_auth of the caller, or an empty object.",
    )
    errors: list[ApiErrorBody] = Field(
        description="At least one error. Use the first msg as the reason the call failed.",
    )
    success: bool = Field(description="Always false for this schema.", examples=[False])
    data: None = Field(default=None, description="Always null when success is false.")


def failure(status_code: int, message: str, session: dict[str, Any] | None = None) -> ErrorResponse:
    """Build an unsuccessful envelope. data is null."""
    return ErrorResponse(
        session_auth=SessionAuth.model_validate(session or {}),
        errors=[ApiErrorBody(code=status_code, msg=message)],
        success=False,
        data=None,
    )


def dump_envelope(model: BaseModel) -> dict[str, Any]:
    """Serialize an envelope with aliases. A null data key is kept on errors."""
    payload = model.model_dump(mode="json", by_alias=True, exclude_none=True)
    if "data" not in payload:
        payload["data"] = None
    if "session_auth" not in payload:
        payload["session_auth"] = {}
    return payload


_ERROR_TEXT = {
    400: "The request was rejected. Read errors[0].msg and correct the arguments before retrying.",
    401: "Missing or invalid bearer token. Send Authorization: Bearer <JWT> and do not retry unchanged.",
    404: "No record with this id is visible to the caller. Do not retry unchanged.",
    405: "This method is not served on the path. Do not retry unchanged.",
    409: "The state does not allow this change, or the file is already imported. Read errors[0].msg.",
    413: "The file is larger than the configured limit. Send a smaller file.",
    422: (
        "The body, form, or query failed validation. errors[0].msg names the field path "
        "and the reason. The body is this envelope, not a top-level detail array."
    ),
    502: "The model or the publisher failed. Read errors[0].msg. Safe to retry once when it is a timeout.",
    500: "Unexpected failure. The message is generic. Safe to retry once.",
}


def error_responses(*codes: int) -> dict[int | str, dict[str, Any]]:
    """OpenAPI responses for the shared error envelope."""
    documented: dict[int | str, dict[str, Any]] = {}
    for code in codes:
        documented[code] = {"model": ErrorResponse, "description": _ERROR_TEXT[code]}
    return documented
