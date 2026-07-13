from __future__ import annotations

from unittest import TestCase

from ai_studio.generation import ContentGenerationService, ScriptRequest
from ai_studio.providers.base import AIMessage, AIProvider, AIResponse


class SequencedProvider(AIProvider):
    name = "test"
    default_model = "test-model"

    def __init__(self):
        self.calls = []
        self.responses = [
            AIResponse("test", "test-model", "Hook. Useful detail. Follow for more."),
            AIResponse("test", "test-model", "Fast, warm delivery with a short hook pause."),
        ]

    def generate_text(
        self,
        messages: list[AIMessage],
        *,
        model=None,
        temperature=0.7,
        max_tokens=1200,
    ) -> AIResponse:
        self.calls.append(
            {
                "messages": messages,
                "model": model,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
        )
        return self.responses.pop(0)


class GenerationServiceTests(TestCase):
    def test_generates_script_and_voiceover_direction(self):
        provider = SequencedProvider()
        request = ScriptRequest(
            topic="Unexpected ocean discovery",
            keywords=("science", "ocean"),
            niche="education",
            target_duration_seconds=30,
        )

        package = ContentGenerationService(provider).generate_package(request)

        self.assertEqual(package.provider, "test")
        self.assertIn("Hook", package.script)
        self.assertIn("warm", package.voiceover_prompt)
        self.assertEqual(len(provider.calls), 2)
        first_prompt = provider.calls[0]["messages"][1].content
        self.assertIn("<trend_data>", first_prompt)
        self.assertIn("Unexpected ocean discovery", first_prompt)

    def test_rejects_invalid_short_duration(self):
        with self.assertRaisesRegex(ValueError, "between 15 and 180"):
            ScriptRequest(topic="topic", target_duration_seconds=5)

