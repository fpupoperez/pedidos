"""Create tasks, orders, rejections, and the two sales views."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "001_tasks_and_orders"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

def upgrade() -> None:
    """Create the import tables and the analytical views."""
    op.create_table(
        "tasks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("filename", sa.String(250), nullable=False),
        sa.Column("storage_path", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("summary", postgresql.JSONB(), nullable=False),
        sa.Column("failure_reason", sa.Text()),
        sa.Column("trace_id", sa.String(32)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_tasks_status", "tasks", ["status"])
    op.create_index("ix_tasks_content_hash", "tasks", ["content_hash"])
    op.create_index(
        "uq_tasks_active_hash",
        "tasks",
        ["content_hash"],
        unique=True,
        postgresql_where=sa.text("status IN ('pending', 'processing', 'completed')"),
    )
    op.create_table(
        "orders",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("order_date", sa.Date(), nullable=False),
        sa.Column("customer", sa.String(200), nullable=False),
        sa.Column("country", sa.String(80), nullable=False),
        sa.Column("product", sa.String(200), nullable=False),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("source_line", sa.Integer(), nullable=False),
    )
    op.create_index("ix_orders_task", "orders", ["task_id"])
    op.create_index("ix_orders_country_date", "orders", ["country", "order_date"])
    op.create_index("ix_orders_customer", "orders", ["customer"])
    op.create_table(
        "import_rejections",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_line", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(80), nullable=False),
        sa.Column("raw", sa.Text(), nullable=False),
    )
    op.create_index("ix_import_rejections_task", "import_rejections", ["task_id"])
    bind = op.get_bind()
    bind.exec_driver_sql(
        """
        CREATE VIEW sales_by_month_country AS
        SELECT
            date_trunc('month', order_date)::date AS sale_month,
            country,
            COUNT(*)::int AS order_count,
            SUM(amount) AS total_amount
        FROM orders
        GROUP BY 1, 2
        """
    )
    bind.exec_driver_sql(
        """
        CREATE VIEW top_customers AS
        SELECT customer, country, COUNT(*)::int AS order_count, SUM(amount) AS total_amount
        FROM orders
        GROUP BY customer, country
        ORDER BY total_amount DESC, customer
        LIMIT 10
        """
    )


def downgrade() -> None:
    """Drop the views and the import tables."""
    bind = op.get_bind()
    bind.exec_driver_sql("DROP VIEW IF EXISTS top_customers")
    bind.exec_driver_sql("DROP VIEW IF EXISTS sales_by_month_country")
    op.drop_table("import_rejections")
    op.drop_table("orders")
    op.drop_table("tasks")
