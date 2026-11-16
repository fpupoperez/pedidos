"""Question request and response models."""

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.auth import SessionAuth
from app.schemas.envelope import ApiErrorBody


class QuestionRequest(BaseModel):
    """One natural-language question. The server writes the SQL."""

    model_config = ConfigDict(extra="forbid", title="QuestionRequest")

    question: str = Field(
        min_length=1,
        max_length=500,
        description="Question about imported orders, from 1 to 500 characters.",
        examples=["¿cuánto vendimos en España en marzo?"],
    )


class QuestionData(BaseModel):
    """The accepted SQL and its rows. Every cell is a string."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True, title="QuestionData")

    sql: str = Field(description="The single SELECT that was executed.", examples=["SELECT total_amount FROM sales_by_month_country LIMIT 200"])
    columns: list[str] = Field(description="Column names in the result.", examples=[["total_amount"]])
    rows: list[list[str]] = Field(description="Result cells as strings. An empty string is a database null.", examples=[[["10.50"]]])
    row_count: int = Field(alias="rowCount", description="Number of rows in this response.", examples=[1])
    truncated: bool = Field(description="True when the server added or shortened LIMIT.", examples=[False])


class QuestionResponse(BaseModel):
    """Envelope around one question result."""

    model_config = ConfigDict(extra="forbid", title="QuestionResponse")

    session_auth: SessionAuth = Field(description="Caller identity for this call.")
    errors: list[ApiErrorBody] = Field(default_factory=list, description="Empty when success is true.")
    success: bool = Field(description="True when the statement ran.", examples=[True])
    data: QuestionData = Field(description="The accepted SQL and its rows.")
