from __future__ import annotations

from typing import Any

import requests

from ai_studio.credentials import APIKeyRepository, DjangoAPIKeyRepository
from ai_studio.exceptions import UnsupportedProviderError

from .anthropic import AnthropicProvider
from .base import AIProvider
from .openai import OpenAIProvider
from .openrouter import OpenRouterProvider

_PROVIDERS: dict[str, type[AIProvider]] = {
    "openai": OpenAIProvider,
    "anthropic": AnthropicProvider,
    "openrouter": OpenRouterProvider,
}


def supported_providers() -> tuple[str, ...]:
    return tuple(_PROVIDERS)


def create_provider(
    provider: str,
    *,
    user: Any = None,
    key_repository: APIKeyRepository | None = None,
    api_key: str | None = None,
    default_model: str | None = None,
    session: requests.Session | None = None,
    **options: Any,
) -> AIProvider:
    """Build a provider using an explicit key or the user's encrypted key store."""

    normalized = provider.strip().lower()
    provider_class = _PROVIDERS.get(normalized)
    if provider_class is None:
        raise UnsupportedProviderError(normalized, supported_providers())
    secret = api_key.strip() if isinstance(api_key, str) else ""
    if not secret:
        repository = key_repository or DjangoAPIKeyRepository()
        secret = repository.get(user, normalized)

    kwargs: dict[str, Any] = dict(options)
    if default_model:
        kwargs["default_model"] = default_model
    if session is not None:
        kwargs["session"] = session
    return provider_class(secret, **kwargs)

