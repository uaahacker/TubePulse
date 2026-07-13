"""API-key repositories kept separate from concrete AI providers."""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from collections.abc import Iterable
from typing import Any

from .exceptions import CredentialAccessError, MissingAPIKeyError


class APIKeyRepository(ABC):
    """Retrieves a plaintext key at the last responsible moment."""

    @abstractmethod
    def get(self, user: Any, provider: str) -> str:
        """Return a non-empty key or raise :class:`MissingAPIKeyError`."""
        raise NotImplementedError


class DjangoAPIKeyRepository(APIKeyRepository):
    """Reads encrypted credentials from ``core.APIKeyStore``.

    The model owns encryption and must expose ``get_secret()``. No provider
    receives the model instance and plaintext keys are never cached here.
    """

    def __init__(self, model_label: str = "core.APIKeyStore") -> None:
        self.model_label = model_label

    def get(self, user: Any, provider: str) -> str:
        if user is None or not getattr(user, "is_authenticated", False):
            raise MissingAPIKeyError(provider)

        try:
            from django.apps import apps

            key_model = apps.get_model(self.model_label)
        except (LookupError, RuntimeError, ValueError) as exc:
            raise MissingAPIKeyError(provider) from exc

        record = (
            key_model.objects.filter(
                user=user, provider__iexact=provider.strip(), is_active=True
            )
            .order_by("-updated_at", "-pk")
            .first()
        )
        if record is None:
            raise MissingAPIKeyError(provider)

        get_secret = getattr(record, "get_secret", None)
        if not callable(get_secret):
            raise MissingAPIKeyError(provider)
        try:
            secret = get_secret()
        except Exception as exc:
            raise CredentialAccessError(
                f"The stored {provider} API key could not be decrypted. Save it again."
            ) from exc
        if not isinstance(secret, str) or not secret.strip():
            raise MissingAPIKeyError(provider)
        return secret.strip()


class EnvironmentAPIKeyRepository(APIKeyRepository):
    """Optional repository for server-level deployments and local development."""

    ENVIRONMENT_NAMES = {
        "openai": "OPENAI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "openrouter": "OPENROUTER_API_KEY",
        "pexels": "PEXELS_API_KEY",
    }

    def get(self, user: Any, provider: str) -> str:
        normalized = provider.strip().lower()
        variable = self.ENVIRONMENT_NAMES.get(
            normalized, f"{normalized.upper().replace('-', '_')}_API_KEY"
        )
        secret = os.environ.get(variable, "").strip()
        if not secret:
            raise MissingAPIKeyError(provider)
        return secret


class StaticAPIKeyRepository(APIKeyRepository):
    """Explicit key mapping useful for CLI jobs and dependency-injected tests."""

    def __init__(self, keys: dict[str, str]) -> None:
        self._keys = {name.lower(): value for name, value in keys.items()}

    def get(self, user: Any, provider: str) -> str:
        secret = self._keys.get(provider.strip().lower(), "").strip()
        if not secret:
            raise MissingAPIKeyError(provider)
        return secret


class ChainedAPIKeyRepository(APIKeyRepository):
    """Checks repositories in order without masking non-missing-key errors."""

    def __init__(self, repositories: Iterable[APIKeyRepository]) -> None:
        self.repositories = tuple(repositories)
        if not self.repositories:
            raise ValueError("At least one API-key repository is required.")

    def get(self, user: Any, provider: str) -> str:
        for repository in self.repositories:
            try:
                return repository.get(user, provider)
            except MissingAPIKeyError:
                continue
        raise MissingAPIKeyError(provider)
