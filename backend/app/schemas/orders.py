"""Order list models."""

from datetime import date
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.auth import SessionAuth
from app.schemas.envelope import ApiErrorBody

_TASK = "00000000-0000-0000-0000-0000000000aa"
_ORDER = "00000000-0000-0000-0000-0000000000bb"


class OrderData(BaseModel):
    """One committed order and the link back to the CSV that produced it."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True, title="OrderData")

    order_id: UUID = Field(alias="orderId", description="Stable id of this order row.", examples=[_ORDER])
    task_id: UUID = Field(alias="taskId", description="Import that committed this row.", examples=[_TASK])
    source_file: str = Field(alias="sourceFile", description="Relative URL of the original CSV.", examples=[f"/api/v1/tasks/{_TASK}/file"])
    source_line: int = Field(alias="sourceLine", description="1-based line in the original file.", examples=[2])
    order_date: date = Field(alias="orderDate", description="Cleaned order date.", examples=["2024-03-13"])
    customer: str = Field(description="Customer name.", examples=["Ana Ruiz"])
    country: str = Field(description="Canonical country name.", examples=["España"])
    product: str = Field(description="Product name.", examples=["Teclado"])
    amount: Decimal = Field(description="Amount in the stored currency unit.", examples=["10.50"])
    status: str = Field(description="Business status from the file.", examples=["pagado"])


class OrderPage(BaseModel):
    """One page of orders."""

    model_config = ConfigDict(extra="forbid", title="OrderPage")

    next: str | None = Field(description="Query string of the next page. Null on the last page.", examples=[None])
    count: int = Field(description="Number of orders that match, including other pages.", examples=[1])
    objects: list[OrderData] = Field(description="Orders on this page.")


class OrderPageResponse(BaseModel):
    """Envelope around a page of orders."""

    model_config = ConfigDict(extra="forbid", title="OrderPageResponse")

    session_auth: SessionAuth = Field(description="Caller identity for this call.")
    errors: list[ApiErrorBody] = Field(default_factory=list, description="Empty when success is true.")
    success: bool = Field(description="True when the page was read.", examples=[True])
    data: OrderPage = Field(description="The page.")


class OrderListQuery(BaseModel):
    """Filters for list_orders. offset is the number of rows to skip."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True, title="OrderListQuery")

    task_id: UUID | None = Field(default=None, alias="taskId", description="When set, only orders from this import.", examples=[_TASK])
    country: str | None = Field(default=None, description="Canonical country name.", examples=["España"])
    customer: str | None = Field(default=None, description="Exact customer name.", examples=["Ana Ruiz"])
    status: str | None = Field(default=None, description="Business status from the file.", examples=["pagado"])
    sale_month: str | None = Field(default=None, alias="saleMonth", description="Month as YYYY-MM.", examples=["2024-03"])
    limit: int = Field(default=50, ge=1, le=200, description="Page size. Maximum 200.", examples=[50])
    offset: int = Field(default=0, ge=0, description="Number of matching orders to skip.", examples=[0])
