from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from ai_studio.exceptions import ProviderResponseError

from .base import AIMessage, AIResponse, JSONHTTPProvider


class OpenAIProvider(JSONHTTPProvider):
    """OpenAI Chat Completions adapter.

    Chat Completions is used deliberately because it maps cleanly to the
    provider-neutral message contract and remains supported by GPT-5.6 Sol.
    """

    name = "OpenAI"
    endpoint = "https://api.openai.com/v1/chat/completions"
    default_model = "gpt-5.6-sol"

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
        }
        if temperature is not None:
            payload["temperature"] = temperature
        body, headers = self._post_json(
            payload,
            {
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
        )
        choices = body.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ProviderResponseError("OpenAI returned no completion choices.")
        choice = choices[0]
        if not isinstance(choice, dict) or not isinstance(choice.get("message"), dict):
            raise ProviderResponseError("OpenAI returned an invalid completion choice.")
        content = self._content_to_text(choice["message"].get("content"))
        usage = self._integer_usage(body.get("usage"))
        return AIResponse(
            provider="openai",
            model=str(body.get("model") or selected_model),
            content=content,
            finish_reason=self._optional_text(choice.get("finish_reason")),
            request_id=self._optional_text(headers.get("x-request-id") or body.get("id")),
            usage=usage,
        )

    @staticmethod
    def _content_to_text(content: Any) -> str:
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            parts = []
            for part in content:
                if isinstance(part, dict) and isinstance(part.get("text"), str):
                    parts.append(part["text"])
            return "\n".join(parts).strip()
        return ""

    @staticmethod
    def _integer_usage(value: Any) -> dict[str, int]:
        if not isinstance(value, dict):
            return {}
        return {
            str(key): item
            for key, item in value.items()
            if isinstance(item, int) and not isinstance(item, bool)
        }

    @staticmethod
    def _optional_text(value: Any) -> str | None:
        return str(value) if value is not None else None

