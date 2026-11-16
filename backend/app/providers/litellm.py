"""OpenAI-compatible chat completion. The key stays in the environment."""

from datetime import date

import httpx
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import get_settings
from app.core.errors import ApiError
from app.providers.base import SYSTEM_PROMPT
from app.sql.execute import execute_select


class LiteLLMProvider:
    """POST {LLM_API_BASE}/chat/completions and return the message content."""

    name = "litellm"

    def __init__(self, transport: httpx.BaseTransport | None = None) -> None:
        settings = get_settings()
        self.model = settings.llm_model
        self._base = settings.llm_api_base.rstrip("/")
        self._key = settings.llm_api_key
        self._timeout = settings.llm_timeout_seconds
        self._transport = transport

    def complete(self, question: str) -> tuple[str, int, int]:
        """Send the shared prompt. A transport error or a bad body is 502."""
        if not self._base or not self.model:
            raise ApiError(502, "The model response was not valid.")
        headers = {"Content-Type": "application/json"}
        if self._key:
            headers["Authorization"] = f"Bearer {self._key}"
        payload = {
            "model": self.model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT + _imported_date_note() + _stored_product_note()},
                {"role": "user", "content": question},
            ],
        }
        try:
            with httpx.Client(timeout=self._timeout, transport=self._transport) as client:
                response = client.post(f"{self._base}/chat/completions", json=payload, headers=headers)
                response.raise_for_status()
                body = response.json()
            text = body["choices"][0]["message"]["content"]
        except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as exc:
            raise ApiError(502, "The model response was not valid.") from exc
        if not isinstance(text, str):
            raise ApiError(502, "The model response was not valid.")
        usage = body.get("usage") if isinstance(body, dict) else None
        prompt_tokens = int(usage.get("prompt_tokens") or 0) if isinstance(usage, dict) else 0
        completion_tokens = int(usage.get("completion_tokens") or 0) if isinstance(usage, dict) else 0
        return text, prompt_tokens, completion_tokens


def _imported_date_note() -> str:
    """Name today, then the loaded dates. A missing table still reports today."""
    today = date.today()
    note = (
        f"\nToday is {today.isoformat()}. "
        f"'este año' means EXTRACT(YEAR FROM order_date) = {today.year}. "
        "Use that year even when every imported row is from another year."
    )
    try:
        _columns, rows = execute_select("SELECT MIN(order_date), MAX(order_date) FROM orders")
    except (ApiError, SQLAlchemyError, OSError):
        return note
    if not rows or rows[0][0] == "" or rows[0][1] == "":
        return note
    start, end = rows[0]
    return f"{note} Imported order_date values run from {start} through {end}."


def _stored_product_note() -> str:
    """List the product spellings loaded from the file. A missing table adds nothing."""
    try:
        _columns, rows = execute_select("SELECT DISTINCT product FROM orders")
    except (ApiError, SQLAlchemyError, OSError):
        return ""
    names = sorted(row[0] for row in rows if row[0])
    if not names:
        return ""
    return " Stored product names: " + ", ".join(names) + ". Translate the question's product into one of these names."
