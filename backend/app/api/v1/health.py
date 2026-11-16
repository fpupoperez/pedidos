"""Process liveness."""

from fastapi import APIRouter

from app.schemas.auth import SessionAuth
from app.schemas.envelope import error_responses
from app.schemas.health import HealthData, HealthResponse

router = APIRouter(tags=["Status"])


@router.get(
    "/health",
    operation_id="get_health",
    summary="Report that the API process is running",
    response_model=HealthResponse,
    responses={
        200: {"model": HealthResponse, "description": "The process is running."},
        **error_responses(500),
    },
)
def get_health() -> HealthResponse:
    """Report process liveness.

    This operation has no JSON body. It does not check Postgres or NATS.
    Do not retry a 500 unchanged more than once.
    """
    return HealthResponse(session_auth=SessionAuth(), errors=[], success=True, data=HealthData(status="ok"))
