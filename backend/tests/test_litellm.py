"""The litellm provider parses a chat completion and refuses a bad response."""

from datetime import date

import httpx
import pytest

from app.core.config import get_settings
from app.core.errors import ApiError
from app.providers.litellm import LiteLLMProvider


def _settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Point the provider at a base URL that the mock transport never dials."""
    settings = get_settings()
    monkeypatch.setattr(settings, "llm_api_base", "http://model.example/v1")
    monkeypatch.setattr(settings, "llm_api_key", "secret")
    monkeypatch.setattr(settings, "llm_model", "gpt-4o-mini")


def test_completion_returns_sql_and_token_counts(monkeypatch: pytest.MonkeyPatch) -> None:
    """A 200 body yields the message text and the usage counters."""
    _settings(monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer secret"
        body = request.read().decode()
        assert '"response_format":{"type":"json_object"}' in body.replace(" ", "")
        assert "Do not invent a year" in body
        assert "este año" in body
        assert str(date.today().year) in body
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"sql": "SELECT country FROM orders"}'}}],
                "usage": {"prompt_tokens": 11, "completion_tokens": 4},
            },
        )

    text, prompt_tokens, completion_tokens = LiteLLMProvider(transport=httpx.MockTransport(handler)).complete("total")
    assert "SELECT country FROM orders" in text
    assert prompt_tokens == 11
    assert completion_tokens == 4


def test_http_error_is_502(monkeypatch: pytest.MonkeyPatch) -> None:
    """A failed model call becomes 502 and does not return SQL."""
    _settings(monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "down"})

    with pytest.raises(ApiError) as caught:
        LiteLLMProvider(transport=httpx.MockTransport(handler)).complete("total")
    assert caught.value.status_code == 502
