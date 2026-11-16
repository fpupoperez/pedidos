"""Answer one question with a single read-only statement."""

from fastapi import APIRouter

from app.schemas.auth import SessionAuth
from app.schemas.envelope import error_responses
from app.schemas.questions import QuestionRequest, QuestionResponse
from app.services.questions import ask

router = APIRouter(prefix="/questions", tags=["Questions"])


@router.post(
    "",
    operation_id="ask_question",
    summary="Answer a question with one read-only SELECT",
    response_model=QuestionResponse,
    responses={
        200: {"model": QuestionResponse, "description": "The accepted SQL and its rows."},
        **error_responses(422, 500, 502),
    },
)
def ask_question(body: QuestionRequest) -> QuestionResponse:
    """Turn a question into one SELECT and run it as the read-only role.

    The statement may use only orders, sales_by_month_country, and top_customers.
    A rejected statement is 422 and the database is not contacted. A bad model payload is 502.
    Do not retry 422 until the question changes.
    """
    data = ask(body.question)
    return QuestionResponse(session_auth=SessionAuth(), errors=[], success=True, data=data)
