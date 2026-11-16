"""Run one checked statement as the read-only role and roll it back."""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import get_settings
from app.core.errors import ApiError


def execute_select(sql: str) -> tuple[list[str], list[list[str]]]:
    """Open a read-only transaction, apply the statement timeout, and return string cells.

    The timeout value comes from settings. The model does not supply parameters.
    """
    settings = get_settings()
    timeout_ms = int(settings.question_timeout_ms)
    engine = create_engine(settings.database_read_url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                connection.exec_driver_sql("SET TRANSACTION READ ONLY")
                connection.exec_driver_sql(f"SET LOCAL statement_timeout = {timeout_ms}")
                result = connection.exec_driver_sql(sql)
                columns = list(result.keys())
                rows = [[_cell(value) for value in row] for row in result.fetchall()]
            except SQLAlchemyError as exc:
                transaction.rollback()
                raise ApiError(422, "The query could not be executed.") from exc
            transaction.rollback()
            return columns, rows
    finally:
        engine.dispose()


def _cell(value: object) -> str:
    """Render a driver value as a JSON string. Null is an empty string."""
    if value is None:
        return ""
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)
