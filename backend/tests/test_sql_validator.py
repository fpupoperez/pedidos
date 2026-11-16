"""The SQL guard rejects anything that is not one read-only select."""

import pytest

from app.sql.validator import GuardError, validate_sql


def test_select_is_capped_and_a_small_limit_is_kept() -> None:
    """A missing LIMIT is added. A limit under the cap stays and is not marked truncated."""
    sql, truncated = validate_sql("SELECT country FROM orders", row_limit=200)
    assert truncated is True
    assert "LIMIT 200" in sql
    kept, truncated = validate_sql("SELECT country FROM orders LIMIT 10", row_limit=200)
    assert truncated is False
    assert "LIMIT 10" in kept


def test_public_prefix_and_cte_are_allowed() -> None:
    """public.orders is the same relation. A CTE name is not a foreign table."""
    sql, _truncated = validate_sql("SELECT country FROM public.orders", row_limit=200)
    assert "orders" in sql
    wrapped, _truncated = validate_sql(
        "WITH recent AS (SELECT country FROM orders) SELECT country FROM recent",
        row_limit=200,
    )
    assert "recent" in wrapped


def test_writes_and_hidden_statements_are_rejected() -> None:
    """Writes, a second statement, pg_ functions, and SELECT INTO do not reach the database."""
    cases = {
        "DROP TABLE orders": "not_select",
        "INSERT INTO orders (country) VALUES ('España')": "not_select",
        "SELECT pg_read_file('/etc/passwd')": "function_not_allowed",
        "SELECT country FROM orders; SELECT country FROM orders": "multiple_statements",
        "SELECT country FROM orders; -- hidden\nDROP TABLE orders": "multiple_statements",
        "SELECT pg_sleep(1)": "function_not_allowed",
        "SELECT country INTO saved FROM orders": "select_into",
        "SELECT country FROM orders FOR UPDATE": "locking",
        "SELECT country FROM customers": "relation_not_allowed",
        "SELECT country FROM secret.orders": "relation_not_allowed",
    }
    for sql, rule in cases.items():
        with pytest.raises(GuardError) as caught:
            validate_sql(sql, row_limit=200)
        assert caught.value.rule == rule
