"""Read committed orders. Questions use a separate read-only path."""

from datetime import date
from urllib.parse import urlencode

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.db.models import OrderRow
from app.schemas.orders import OrderData, OrderListQuery, OrderPage
from app.services.tasks import source_file


def list_orders(session: Session, query: OrderListQuery) -> OrderPage:
    """Return one page of orders. saleMonth limits the result to that calendar month."""
    statement: Select[tuple[OrderRow]] = select(OrderRow)
    count_statement = select(func.count()).select_from(OrderRow)
    statement, count_statement = _filters(statement, count_statement, query)
    count = int(session.scalar(count_statement) or 0)
    rows = session.scalars(statement.order_by(OrderRow.order_date, OrderRow.customer).limit(query.limit).offset(query.offset)).all()
    objects = [
        OrderData(
            order_id=row.id,
            task_id=row.task_id,
            source_file=source_file(row.task_id),
            source_line=row.source_line,
            order_date=row.order_date,
            customer=row.customer,
            country=row.country,
            product=row.product,
            amount=row.amount,
            status=row.status,
        )
        for row in rows
    ]
    return OrderPage(next=_next(query, count), count=count, objects=objects)


def _filters(statement: Select[tuple[OrderRow]], count_statement: Select[tuple[int]], query: OrderListQuery) -> tuple[Select[tuple[OrderRow]], Select[tuple[int]]]:
    """Apply the optional list filters to both the page query and the count."""
    if query.task_id is not None:
        statement = statement.where(OrderRow.task_id == query.task_id)
        count_statement = count_statement.where(OrderRow.task_id == query.task_id)
    if query.country:
        statement = statement.where(OrderRow.country == query.country)
        count_statement = count_statement.where(OrderRow.country == query.country)
    if query.customer:
        statement = statement.where(OrderRow.customer == query.customer)
        count_statement = count_statement.where(OrderRow.customer == query.customer)
    if query.status:
        statement = statement.where(OrderRow.status == query.status)
        count_statement = count_statement.where(OrderRow.status == query.status)
    if query.sale_month:
        start, end = _month_bounds(query.sale_month)
        statement = statement.where(OrderRow.order_date >= start, OrderRow.order_date < end)
        count_statement = count_statement.where(OrderRow.order_date >= start, OrderRow.order_date < end)
    return statement, count_statement


def _month_bounds(value: str) -> tuple[date, date]:
    """Turn YYYY-MM into a half-open date range."""
    parts = value.split("-")
    if len(parts) != 2:
        raise ApiError(422, "saleMonth must be YYYY-MM.")
    year, month = int(parts[0]), int(parts[1])
    if month < 1 or month > 12:
        raise ApiError(422, "saleMonth must be YYYY-MM.")
    start = date(year, month, 1)
    if month == 12:
        end = date(year + 1, 1, 1)
    else:
        end = date(year, month + 1, 1)
    return start, end


def _next(query: OrderListQuery, count: int) -> str | None:
    """The next page query string, or None when this page is the last."""
    following = query.offset + query.limit
    if following >= count:
        return None
    params: dict[str, str] = {"limit": str(query.limit), "offset": str(following)}
    if query.task_id is not None:
        params["taskId"] = str(query.task_id)
    if query.country:
        params["country"] = query.country
    if query.customer:
        params["customer"] = query.customer
    if query.status:
        params["status"] = query.status
    if query.sale_month:
        params["saleMonth"] = query.sale_month
    return "?" + urlencode(params)
