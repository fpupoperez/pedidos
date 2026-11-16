"""Read committed orders."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.db.session import make_engine, make_session_factory
from app.schemas.auth import SessionAuth
from app.schemas.envelope import error_responses
from app.schemas.orders import OrderListQuery, OrderPageResponse
from app.services.orders_query import list_orders

router = APIRouter(prefix="/orders", tags=["Orders"])


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


def order_list_query(
    taskId: Annotated[UUID | None, Query(alias="taskId", description="When set, only orders from this import.")] = None,
    country: Annotated[str | None, Query(description="Canonical country name.")] = None,
    customer: Annotated[str | None, Query(description="Exact customer name.")] = None,
    status: Annotated[str | None, Query(description="Business status from the file.")] = None,
    saleMonth: Annotated[str | None, Query(alias="saleMonth", description="Month as YYYY-MM.")] = None,
    limit: Annotated[int, Query(ge=1, le=200, description="Page size. Maximum 200.")] = 50,
    offset: Annotated[int, Query(ge=0, description="Number of matching orders to skip.")] = 0,
) -> OrderListQuery:
    """Build the documented order query."""
    return OrderListQuery(
        task_id=taskId,
        country=country,
        customer=customer,
        status=status,
        sale_month=saleMonth,
        limit=limit,
        offset=offset,
    )


@router.get(
    "",
    operation_id="list_orders",
    summary="List committed orders",
    response_model=OrderPageResponse,
    responses={200: {"model": OrderPageResponse, "description": "One page of orders."}, **error_responses(422, 500)},
)
def list_orders_route(query: Annotated[OrderListQuery, Depends(order_list_query)], session=Depends(_session)) -> OrderPageResponse:
    """List orders that an import committed.

    This operation has no JSON body. taskId limits the page to one file.
    Analytical questions go through ask_question.
    """
    page = list_orders(session, query)
    return OrderPageResponse(session_auth=SessionAuth(), errors=[], success=True, data=page)
