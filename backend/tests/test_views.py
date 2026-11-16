"""Sales views and the active-hash rule, loaded without the CSV cleaner."""

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError, ProgrammingError

from app.db.models import OrderRow, TaskRow
from app.db.session import make_session_factory


def _task(status: str, content_hash: str) -> TaskRow:
    """Build a task row that satisfies the non-null columns."""
    return TaskRow(
        id=uuid4(),
        status=status,
        filename="orders.csv",
        storage_path="uploads/orders.csv",
        content_hash=content_hash,
        summary={"cleaned": False, "totalRows": 0},
    )


def test_views_rank_sales_and_stop_at_ten_customers(migrated: Engine) -> None:
    """Monthly totals match the inserted rows, and top_customers returns at most 10."""
    factory = make_session_factory(migrated)
    with factory() as session:
        task = _task("completed", "a" * 64)
        session.add(task)
        session.flush()
        rows = [
            ("Ana", "Espana", date(2024, 3, 10), Decimal("100.00")),
            ("Ana", "Espana", date(2024, 3, 20), Decimal("40.00")),
            ("Ana", "Francia", date(2024, 3, 5), Decimal("10.00")),
            ("Luis", "Espana", date(2024, 4, 2), Decimal("25.00")),
        ]
        for index in range(11):
            rows.append((f"Cliente {index}", "Portugal", date(2024, 1, 1), Decimal(index + 1)))
        for index, (customer, country, order_date, amount) in enumerate(rows, start=2):
            session.add(
                OrderRow(
                    id=uuid4(),
                    task_id=task.id,
                    order_date=order_date,
                    customer=customer,
                    country=country,
                    product="Teclado",
                    amount=amount,
                    status="pagado",
                    source_line=index,
                )
            )
        session.commit()
        monthly = session.execute(
            text(
                "SELECT sale_month, country, order_count, total_amount "
                "FROM sales_by_month_country ORDER BY sale_month, country"
            )
        ).all()
        top = session.execute(text("SELECT customer, country, total_amount FROM top_customers")).all()
    months = {(row.sale_month, row.country): (row.order_count, row.total_amount) for row in monthly}
    assert months[(date(2024, 3, 1), "Espana")] == (2, Decimal("140.00"))
    assert months[(date(2024, 3, 1), "Francia")] == (1, Decimal("10.00"))
    assert months[(date(2024, 4, 1), "Espana")] == (1, Decimal("25.00"))
    assert len(top) == 10
    assert top[0].customer == "Ana"
    assert top[0].country == "Espana"
    assert top[0].total_amount == Decimal("140.00")


def test_one_active_task_per_hash(migrated: Engine) -> None:
    """A completed hash blocks a second active task. A failed task does not."""
    factory = make_session_factory(migrated)
    digest = "b" * 64
    with factory() as session:
        session.add(_task("completed", digest))
        session.commit()
        session.add(_task("pending", digest))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()
        session.add(_task("failed", digest))
        session.commit()


def test_reader_can_select_views_and_not_tasks(migrated: Engine) -> None:
    """orders_reader sees the views and is refused the tasks table."""
    url = migrated.url.render_as_string(hide_password=False)
    reader_url = url.replace("orders:orders@", "orders_reader:orders_reader@")
    from sqlalchemy import create_engine

    reader = create_engine(reader_url, pool_pre_ping=True)
    try:
        with reader.connect() as connection:
            connection.execute(text("SELECT country FROM sales_by_month_country"))
            with pytest.raises(ProgrammingError):
                connection.execute(text("SELECT id FROM tasks"))
    finally:
        reader.dispose()
