"""OpenAI-compatible chat completion. The key stays in the environment."""

import httpx

from app.core.config import get_settings
from app.core.errors import ApiError
from app.providers.base import SYSTEM_PROMPT


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
                {"role": "system", "content": SYSTEM_PROMPT},
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
