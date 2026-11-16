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
    _fold_product_case(statement)
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


def _fold_product_case(statement: exp.Select) -> None:
    """Compare product text without case. Stored names keep the letters from the file."""
    nodes = [node for node in statement.walk() if isinstance(node, (exp.EQ, exp.NEQ, exp.In, exp.Like))]
    for node in nodes:
        if isinstance(node, exp.In):
            _fold_product_in(node)
        elif isinstance(node, exp.Like):
            _fold_product_like(node)
        else:
            _fold_product_equality(node)


def _fold_product_equality(node: exp.EQ | exp.NEQ) -> None:
    """LOWER both sides of product = 'text' and product <> 'text'."""
    left = _product_text(node.this)
    right = _string_text(node.expression)
    if left is not None and right is not None:
        node.set("this", _lower(left))
        node.set("expression", _lower(right))
        return
    left = _string_text(node.this)
    right = _product_text(node.expression)
    if left is not None and right is not None:
        node.set("this", _lower(left))
        node.set("expression", _lower(right))


def _fold_product_in(node: exp.In) -> None:
    """LOWER product and each string in product IN (...)."""
    column = _product_text(node.this)
    values = [_string_text(item) for item in node.expressions]
    if column is None or not values or any(item is None for item in values):
        return
    node.set("this", _lower(column))
    node.set("expressions", [_lower(item) for item in values if item is not None])


def _fold_product_like(node: exp.Like) -> None:
    """Turn product LIKE 'pattern' into ILIKE. ILIKE is already case-insensitive."""
    if isinstance(node, exp.ILike):
        return
    column = node.this.this if isinstance(node.this, exp.Lower) else node.this
    if not isinstance(column, exp.Column) or column.name.lower() != "product":
        return
    if not isinstance(node.expression, exp.Literal) or not node.expression.is_string:
        return
    node.replace(exp.ILike(this=column.copy(), expression=node.expression.copy()))


def _product_text(node: exp.Expression) -> exp.Expression | None:
    """The product column, or LOWER(product)."""
    if isinstance(node, exp.Column) and node.name.lower() == "product":
        return node
    if isinstance(node, exp.Lower) and isinstance(node.this, exp.Column) and node.this.name.lower() == "product":
        return node
    return None


def _string_text(node: exp.Expression) -> exp.Expression | None:
    """A string literal, or LOWER of a string literal."""
    if isinstance(node, exp.Literal) and node.is_string:
        return node
    if isinstance(node, exp.Lower) and isinstance(node.this, exp.Literal) and node.this.is_string:
        return node
    return None


def _lower(node: exp.Expression) -> exp.Expression:
    """Wrap a value in LOWER unless it is already wrapped."""
    if isinstance(node, exp.Lower):
        return node
    return exp.Lower(this=node.copy())


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
