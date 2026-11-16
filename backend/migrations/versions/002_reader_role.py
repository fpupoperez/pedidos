"""Create the read-only role used by natural-language questions."""

from collections.abc import Sequence

from alembic import op

revision: str = "002_reader_role"
down_revision: str | None = "001_tasks_and_orders"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Grant the reader SELECT on orders and the two views, and nothing else."""
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'orders_reader') THEN
                CREATE ROLE orders_reader LOGIN PASSWORD 'orders_reader';
            END IF;
        END
        $$
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            EXECUTE format('GRANT CONNECT ON DATABASE %I TO orders_reader', current_database());
        END
        $$
        """
    )
    op.execute("GRANT USAGE ON SCHEMA public TO orders_reader")
    op.execute("GRANT SELECT ON orders, sales_by_month_country, top_customers TO orders_reader")
    op.execute("REVOKE ALL ON tasks, import_rejections FROM orders_reader")


def downgrade() -> None:
    """Remove the reader grants. The role stays if another database still uses it."""
    op.execute("REVOKE ALL ON tasks, import_rejections FROM orders_reader")
    op.execute("REVOKE SELECT ON orders, sales_by_month_country, top_customers FROM orders_reader")
