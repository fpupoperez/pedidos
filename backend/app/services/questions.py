"""Ask one question. The database is contacted only after the guard accepts the SQL."""

import json
import re
import time

from sqlglot import exp, parse_one
from sqlglot.errors import SqlglotError

from sqlalchemy.exc import SQLAlchemyError

from app.core.config import get_settings
from app.core.errors import ApiError
from app.core.telemetry import record_llm, record_question, span
from app.domain.countries import canonical_country
from app.domain.products import canonical_product, fold_product
from app.providers.base import ModelProvider
from app.providers.fake import FakeProvider
from app.providers.litellm import LiteLLMProvider
from app.schemas.questions import QuestionData
from app.sql.execute import execute_select
from app.sql.validator import GuardError, validate_sql

_HOW_MANY = re.compile(r"\bcu[aá]nt(?:as|os)\b", re.IGNORECASE)


def ask(question: str) -> QuestionData:
    """Call the provider, keep one checked statement, and execute it read-only."""
    started = time.perf_counter()
    success = False
    try:
        with span("question.ask"):
            data = _ask(question)
        success = True
        return data
    finally:
        record_question((time.perf_counter() - started) * 1000, success=success)


def _ask(question: str) -> QuestionData:
    """The steps under question.ask. A bad model payload never reaches the guard or the database."""
    settings = get_settings()
    provider = _provider()
    llm_started = time.perf_counter()
    with span("question.llm", provider=provider.name, model=provider.model):
        text, input_tokens, output_tokens = provider.complete(question)
    record_llm((time.perf_counter() - llm_started) * 1000, model=provider.model, input_tokens=input_tokens, output_tokens=output_tokens)
    sql = _count_when_asked(question, _translate_stored_names(_sql_from_model(text), _stored_products()))
    with span("question.guard") as current:
        try:
            checked, truncated = validate_sql(sql, row_limit=settings.question_row_limit)
        except GuardError as exc:
            current.set_attribute("accepted", False)
            current.set_attribute("rule", exc.rule)
            raise ApiError(422, f"Rejected by sql_guard: {exc.rule}") from exc
        current.set_attribute("accepted", True)
    with span("question.execute") as current:
        columns, rows = execute_select(checked)
        current.set_attribute("row_count", len(rows))
        current.set_attribute("truncated", truncated)
    return QuestionData(sql=checked, columns=columns, rows=rows, row_count=len(rows), truncated=truncated)


def _provider() -> ModelProvider:
    """fake in tests. litellm calls the configured OpenAI-compatible endpoint."""
    name = get_settings().llm_provider
    if name == "fake":
        return FakeProvider()
    if name == "litellm":
        return LiteLLMProvider()
    raise ApiError(502, "The model response was not valid.")


def _stored_products() -> dict[str, str]:
    """Map a folded product name to the spelling stored in orders. An empty table returns nothing."""
    try:
        _columns, rows = execute_select("SELECT DISTINCT product FROM orders")
    except (ApiError, SQLAlchemyError, OSError):
        return {}
    return {fold_product(row[0]): row[0] for row in rows if row[0]}


def _translate_stored_names(sql: str, products: dict[str, str]) -> str:
    """Use the Spanish country and product spellings when the model names them in another language."""
    try:
        statement = parse_one(sql, read="postgres")
    except SqlglotError:
        return sql
    if not isinstance(statement, exp.Select):
        return sql
    changed = False
    for node in list(statement.walk()):
        if isinstance(node, (exp.EQ, exp.NEQ)):
            changed = _translate_pair(node, products) or changed
        elif isinstance(node, exp.In):
            changed = _translate_in(node, products) or changed
    if not changed:
        return sql
    return statement.sql(dialect="postgres")


def _translate_pair(node: exp.EQ | exp.NEQ, products: dict[str, str]) -> bool:
    """Replace one string compared with country or product."""
    return _replace_literal(node, "this", "expression", products) or _replace_literal(node, "expression", "this", products)


def _replace_literal(node: exp.Expression, column_key: str, literal_key: str, products: dict[str, str]) -> bool:
    """When column_key is country or product, rewrite the string at literal_key."""
    column = _column_name(node.args.get(column_key))
    literal = _string_literal(node.args.get(literal_key))
    if column is None or literal is None:
        return False
    stored = _stored_value(column, literal.this, products)
    if stored is None or stored == literal.this:
        return False
    literal.set("this", stored)
    return True


def _translate_in(node: exp.In, products: dict[str, str]) -> bool:
    """Replace each string in country IN (...) or product IN (...)."""
    column = _column_name(node.this)
    if column not in {"country", "product"}:
        return False
    changed = False
    for item in node.expressions:
        literal = _string_literal(item)
        if literal is None:
            continue
        stored = _stored_value(column, literal.this, products)
        if stored is not None and stored != literal.this:
            literal.set("this", stored)
            changed = True
    return changed


def _stored_value(column: str, text: str, products: dict[str, str]) -> str | None:
    """The stored country or product spelling for one model word."""
    if column == "country":
        return canonical_country(text)
    if column == "product":
        return canonical_product(text, products)
    return None


def _column_name(node: object) -> str | None:
    """country or product, including LOWER(column)."""
    if isinstance(node, exp.Lower):
        node = node.this
    if isinstance(node, exp.Column):
        return node.name.lower()
    return None


def _string_literal(node: object) -> exp.Literal | None:
    """A string literal, including LOWER('text')."""
    if isinstance(node, exp.Lower):
        node = node.this
    if isinstance(node, exp.Literal) and node.is_string:
        return node
    return None


def _count_when_asked(question: str, sql: str) -> str:
    """How many sales is a row count. A sum of amount answers a different question."""
    if _HOW_MANY.search(question) is None:
        return sql
    try:
        statement = parse_one(sql, read="postgres")
    except SqlglotError:
        return sql
    if not isinstance(statement, exp.Select):
        return sql
    sums = [node for node in statement.find_all(exp.Sum) if _is_amount(node.this)]
    if not sums:
        return sql
    for node in sums:
        node.replace(exp.Count(this=exp.Star()))
    for alias in statement.find_all(exp.Alias):
        if alias.alias.lower() in {"total_amount", "total_sales"}:
            alias.set("alias", exp.to_identifier("sales"))
    return statement.sql(dialect="postgres")


def _is_amount(node: exp.Expression) -> bool:
    """True when the summed value is the amount column."""
    return isinstance(node, exp.Column) and node.name.lower() == "amount"


def _sql_from_model(text: str) -> str:
    """Require the object {"sql": "<SELECT>"}. Any other shape is rejected.

    A fenced block or a short preface is still read, then the object is checked.
    """
    payload = _json_object(text)
    if set(payload) != {"sql"}:
        raise ApiError(502, "The model response was not valid.")
    sql = payload.get("sql")
    if not isinstance(sql, str) or not sql.strip():
        raise ApiError(502, "The model response was not valid.")
    return sql


def _json_object(text: str) -> dict[str, object]:
    """Parse the model text as one JSON object. Fences and surrounding words are removed."""
    candidate = _without_fence(text.strip())
    payload = _loads_object(candidate)
    if payload is not None:
        return payload
    start = candidate.find("{")
    end = candidate.rfind("}")
    if start >= 0 and end > start:
        payload = _loads_object(candidate[start : end + 1])
        if payload is not None:
            return payload
    raise ApiError(502, "The model response was not valid.")


def _without_fence(text: str) -> str:
    """Drop one surrounding Markdown fence. The language tag on the first line is ignored."""
    if not text.startswith("```"):
        return text
    lines = text.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _loads_object(text: str) -> dict[str, object] | None:
    """Return a JSON object, or None when the text is not one."""
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None
    if isinstance(payload, dict):
        return payload
    return None
