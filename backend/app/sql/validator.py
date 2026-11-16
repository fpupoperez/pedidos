"""Accept one read-only statement against the three published relations.

sqlglot parses the text. The database sees only the SQL this module returns.
"""

from sqlglot import exp, parse
from sqlglot.errors import SqlglotError

ALLOWED_RELATIONS = frozenset({"orders", "sales_by_month_country", "top_customers"})
_WRITE = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Merge,
    exp.Drop,
    exp.Alter,
    exp.Create,
    exp.Command,
    exp.Grant,
    exp.TruncateTable,
    exp.Copy,
)
_CONTROL = (exp.Transaction, exp.Commit, exp.Rollback, exp.Set)


class GuardError(Exception):
    """The statement failed one rule. rule is the public name, not the SQL text."""

    def __init__(self, rule: str) -> None:
        self.rule = rule
        super().__init__(rule)


def validate_sql(sql: str, *, row_limit: int) -> tuple[str, bool]:
    """Return the checked SQL and whether the row cap was added or shortened.

    A rejection raises GuardError. The caller turns that into 422 and does not keep the text.
    """
    try:
        statements = [item for item in parse(sql, read="postgres") if item is not None]
    except SqlglotError as exc:
        raise GuardError("not_select") from exc
    if not statements:
        raise GuardError("empty")
    if len(statements) != 1:
        raise GuardError("multiple_statements")
    statement = statements[0]
    if not isinstance(statement, exp.Select):
        raise GuardError("not_select")
    if statement.args.get("into"):
        raise GuardError("select_into")
    if statement.args.get("locks"):
        raise GuardError("locking")
    for node in statement.walk():
        if isinstance(node, _WRITE) or isinstance(node, _CONTROL):
            raise GuardError("write_statement")
        if isinstance(node, exp.Func):
            called = (node.name or node.sql_name()).lower()
            if called.startswith("pg_"):
                raise GuardError("function_not_allowed")
    _check_relations(statement)
    truncated = _cap_limit(statement, row_limit)
    return statement.sql(dialect="postgres"), truncated


def _check_relations(statement: exp.Select) -> None:
    """Every real table is one of the three views or orders. A CTE name is local."""
    cte_names = {cte.alias_or_name.lower() for cte in statement.find_all(exp.CTE)}
    for table in statement.find_all(exp.Table):
        name = table.name.lower()
        if name in cte_names:
            continue
        schema = (table.db or "").lower()
        if table.catalog or schema not in {"", "public"} or name not in ALLOWED_RELATIONS:
            raise GuardError("relation_not_allowed")


def _cap_limit(statement: exp.Select, row_limit: int) -> bool:
    """Append or shorten LIMIT. A non-numeric limit is rejected."""
    limit = statement.args.get("limit")
    if limit is None:
        statement.set("limit", exp.Limit(expression=exp.Literal.number(row_limit)))
        return True
    value = limit.expression
    if not isinstance(value, exp.Literal) or not value.is_int:
        raise GuardError("limit_not_constant")
    if int(value.this) > row_limit:
        value.set("this", str(row_limit))
        return True
    return False
