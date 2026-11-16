"""SQLAlchemy models for tasks, orders, and rejected CSV rows."""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import Date, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Shared SQLAlchemy base. Alembic imports this so the metadata is complete."""


EMPTY_SUMMARY: dict[str, object] = {
    "totalRows": 0,
    "processedRows": 0,
    "stagedRows": 0,
    "acceptedRows": 0,
    "importedRows": 0,
    "duplicateRows": 0,
    "invalidRows": 0,
    "rejectedRows": 0,
    "byReason": {},
    "cleaned": False,
}


class TaskRow(Base):
    """One CSV import. summary stores counts only. phase is derived from status later."""

    __tablename__ = "tasks"
    __table_args__ = (
        Index("ix_tasks_status", "status"),
        Index("ix_tasks_content_hash", "content_hash"),
        Index(
            "uq_tasks_active_hash",
            "content_hash",
            unique=True,
            postgresql_where=text("status IN ('pending', 'processing', 'completed')"),
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    filename: Mapped[str] = mapped_column(String(250), nullable=False)
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    summary: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=lambda: dict(EMPTY_SUMMARY))
    failure_reason: Mapped[str | None] = mapped_column(Text)
    trace_id: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class OrderRow(Base):
    """One accepted order row. task_id is the link back to the original CSV."""

    __tablename__ = "orders"
    __table_args__ = (
        Index("ix_orders_task", "task_id"),
        Index("ix_orders_country_date", "country", "order_date"),
        Index("ix_orders_customer", "customer"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    task_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False
    )
    order_date: Mapped[date] = mapped_column(Date, nullable=False)
    customer: Mapped[str] = mapped_column(String(200), nullable=False)
    country: Mapped[str] = mapped_column(String(80), nullable=False)
    product: Mapped[str] = mapped_column(String(200), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    source_line: Mapped[int] = mapped_column(Integer, nullable=False)


class ImportRejectionRow(Base):
    """One CSV line that was not imported, kept so the caller can inspect it."""

    __tablename__ = "import_rejections"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    task_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_line: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(String(80), nullable=False)
    raw: Mapped[str] = mapped_column(Text, nullable=False)
