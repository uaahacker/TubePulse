from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from ai_studio.exceptions import ProviderResponseError

from .base import AIMessage, AIResponse, JSONHTTPProvider


class AnthropicProvider(JSONHTTPProvider):
    """Claude Messages API adapter using Anthropic's versioned HTTP contract."""

    name = "Anthropic"
    endpoint = "https://api.anthropic.com/v1/messages"
    default_model = "claude-sonnet-4-6"

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
        system_parts = [message.content for message in messages if message.role == "system"]
        conversation = [
            {"role": message.role, "content": message.content}
            for message in messages
            if message.role != "system"
        ]
        if not conversation:
            raise ValueError("Anthropic requests require at least one user message.")

        payload: dict[str, Any] = {
            "model": selected_model,
            "messages": conversation,
            "max_tokens": max_tokens,
        }
        if system_parts:
            payload["system"] = "\n\n".join(system_parts)
        if temperature is not None:
            payload["temperature"] = temperature

        body, headers = self._post_json(
            payload,
            {
                "x-api-key": self._api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
        )
        blocks = body.get("content")
        if not isinstance(blocks, list):
            raise ProviderResponseError("Anthropic returned invalid message content.")
        content = "\n".join(
            block["text"]
            for block in blocks
            if isinstance(block, dict)
            and block.get("type") == "text"
            and isinstance(block.get("text"), str)
        ).strip()
        if not content:
            raise ProviderResponseError("Anthropic returned no text content.")
        usage = self._integer_usage(body.get("usage"))
        return AIResponse(
            provider="anthropic",
            model=str(body.get("model") or selected_model),
            content=content,
            finish_reason=self._optional_text(body.get("stop_reason")),
            request_id=self._optional_text(
                headers.get("request-id") or headers.get("x-request-id") or body.get("id")
            ),
            usage=usage,
        )

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

