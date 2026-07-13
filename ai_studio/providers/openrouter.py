from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from ai_studio.exceptions import ProviderResponseError

from .base import AIMessage, AIResponse, JSONHTTPProvider
from .openai import OpenAIProvider


class OpenRouterProvider(JSONHTTPProvider):
    """OpenRouter adapter for its normalized non-streaming Chat API."""

    name = "OpenRouter"
    endpoint = "https://openrouter.ai/api/v1/chat/completions"
    default_model = "openai/gpt-5.6-sol"

    def __init__(
        self,
        api_key: str,
        *,
        site_url: str = "http://localhost:8000",
        app_title: str = "TubePulse CRM",
        **kwargs: Any,
    ) -> None:
        super().__init__(api_key, **kwargs)
        self.site_url = site_url
        self.app_title = app_title

    def generate_text(
        self,
        messages: Sequence[AIMessage],
        *,
        model: str | None = None,
        temperature: float | None = 0.7,
        max_tokens: int = 1_200,
    ) -> AIResponse:
        self._validate_request(messages, max_tokens, temperature)
        selected_model = model or self.default_model
        payload: dict[str, Any] = {
            "model": selected_model,
            "messages": [
                {"role": message.role, "content": message.content}
                for message in messages
            ],
            "max_completion_tokens": max_tokens,
            "stream": False,
        }
        if temperature is not None:
            payload["temperature"] = temperature
        body, headers = self._post_json(
            payload,
            {
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": self.site_url,
                "X-OpenRouter-Title": self.app_title,
            },
        )
        choices = body.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ProviderResponseError("OpenRouter returned no completion choices.")
        choice = choices[0]
        if not isinstance(choice, dict):
            raise ProviderResponseError("OpenRouter returned an invalid completion choice.")
        if choice.get("error") or choice.get("finish_reason") == "error":
            detail = choice.get("error")
            if isinstance(detail, dict):
                detail = detail.get("message") or "upstream provider failed"
            raise ProviderResponseError(
                f"OpenRouter upstream generation failed: {str(detail)[:300]}"
            )
        message = choice.get("message")
        if not isinstance(message, dict):
            raise ProviderResponseError("OpenRouter returned invalid message content.")
        content = OpenAIProvider._content_to_text(message.get("content"))
        return AIResponse(
            provider="openrouter",
            model=str(body.get("model") or selected_model),
            content=content,
            finish_reason=self._optional_text(choice.get("finish_reason")),
            request_id=self._optional_text(headers.get("x-request-id") or body.get("id")),
            usage=OpenAIProvider._integer_usage(body.get("usage")),
        )

    @staticmethod
    def _optional_text(value: Any) -> str | None:
        return str(value) if value is not None else None
