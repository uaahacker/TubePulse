from __future__ import annotations

from unittest import TestCase

from ai_studio.credentials import StaticAPIKeyRepository
from ai_studio.exceptions import (
    MissingAPIKeyError,
    ProviderAuthenticationError,
    ProviderResponseError,
    UnsupportedProviderError,
)
from ai_studio.providers.anthropic import AnthropicProvider
from ai_studio.providers.base import AIMessage
from ai_studio.providers.factory import create_provider
from ai_studio.providers.openai import OpenAIProvider
from ai_studio.providers.openrouter import OpenRouterProvider


class FakeResponse:
    def __init__(self, payload, *, status=200, headers=None, text=""):
        self.payload = payload
        self.status_code = status
        self.headers = headers or {}
        self.text = text
        self.closed = False

    def json(self):
        return self.payload

    def close(self):
        self.closed = True


class FakeSession:
    def __init__(self, response):
        self.response = response
        self.calls = []
        self.closed = False

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response

    def close(self):
        self.closed = True


class ProviderTests(TestCase):
    def test_openai_maps_chat_completion(self):
        session = FakeSession(
            FakeResponse(
                {
                    "id": "chat-123",
                    "model": "gpt-5.6-sol",
                    "choices": [
                        {
                            "message": {"content": "A sharp opening hook."},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {"prompt_tokens": 12, "completion_tokens": 8},
                },
                headers={"x-request-id": "req-123"},
            )
        )
        provider = OpenAIProvider("secret", session=session)

        result = provider.generate_text([AIMessage("user", "Write a hook")])

        self.assertEqual(result.content, "A sharp opening hook.")
        self.assertEqual(result.request_id, "req-123")
        payload = session.calls[0][1]["json"]
        self.assertEqual(payload["max_completion_tokens"], 1200)
        self.assertNotIn("secret", repr(session.calls[0][1]["json"]))
        self.assertEqual(
            session.calls[0][1]["headers"]["Authorization"], "Bearer secret"
        )
        self.assertTrue(session.response.closed)
        provider.close()
        self.assertFalse(session.closed)

    def test_anthropic_separates_system_message(self):
        session = FakeSession(
            FakeResponse(
                {
                    "id": "msg-1",
                    "model": "claude-sonnet-4-6",
                    "content": [{"type": "text", "text": "Narration"}],
                    "stop_reason": "end_turn",
                    "usage": {"input_tokens": 10, "output_tokens": 3},
                }
            )
        )
        provider = AnthropicProvider("secret", session=session)

        result = provider.generate_text(
            [AIMessage("system", "Be concise"), AIMessage("user", "Write")]
        )

        payload = session.calls[0][1]["json"]
        self.assertEqual(payload["system"], "Be concise")
        self.assertEqual(payload["messages"], [{"role": "user", "content": "Write"}])
        self.assertEqual(result.content, "Narration")
        self.assertEqual(
            session.calls[0][1]["headers"]["anthropic-version"], "2023-06-01"
        )

    def test_openrouter_surfaces_upstream_error(self):
        session = FakeSession(
            FakeResponse(
                {
                    "choices": [
                        {
                            "finish_reason": "error",
                            "error": {"message": "provider unavailable"},
                        }
                    ]
                }
            )
        )
        provider = OpenRouterProvider("secret", session=session)

        with self.assertRaisesRegex(ProviderResponseError, "provider unavailable"):
            provider.generate_text([AIMessage("user", "Write")])

        self.assertEqual(
            session.calls[0][1]["json"]["max_completion_tokens"], 1200
        )
        self.assertNotIn("max_tokens", session.calls[0][1]["json"])

    def test_authentication_errors_are_safe(self):
        session = FakeSession(FakeResponse({"error": "bad key"}, status=401))
        provider = OpenAIProvider("do-not-leak", session=session)

        with self.assertRaises(ProviderAuthenticationError) as context:
            provider.generate_text([AIMessage("user", "Write")])
        self.assertNotIn("do-not-leak", str(context.exception))

    def test_factory_uses_injected_repository(self):
        provider = create_provider(
            "openai",
            key_repository=StaticAPIKeyRepository({"openai": "stored-key"}),
            session=FakeSession(FakeResponse({})),
        )
        self.assertIsInstance(provider, OpenAIProvider)

    def test_factory_rejects_missing_and_unknown_providers(self):
        with self.assertRaises(MissingAPIKeyError):
            create_provider("openai", key_repository=StaticAPIKeyRepository({}))
        with self.assertRaises(UnsupportedProviderError):
            create_provider("unknown", api_key="secret")
