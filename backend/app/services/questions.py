"""Ask one question. The database is contacted only after the guard accepts the SQL."""

import json
import time

from app.core.config import get_settings
from app.core.errors import ApiError
from app.core.telemetry import record_llm, record_question, span
from app.providers.base import ModelProvider
from app.providers.fake import FakeProvider
from app.providers.litellm import LiteLLMProvider
from app.schemas.questions import QuestionData
from app.sql.execute import execute_select
from app.sql.validator import GuardError, validate_sql


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
    sql = _sql_from_model(text)
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


def _sql_from_model(text: str) -> str:
    """Require one JSON object with a non-empty sql string. Extra keys are ignored."""
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ApiError(502, "The model response was not valid.") from exc
    if not isinstance(payload, dict):
        raise ApiError(502, "The model response was not valid.")
    sql = payload.get("sql")
    if not isinstance(sql, str) or not sql.strip():
        raise ApiError(502, "The model response was not valid.")
    return sql
