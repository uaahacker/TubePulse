"""Small domain services shared by decoupled apps."""
from __future__ import annotations

from core.models import APIKeyStore, User


class MissingAPIKeyError(LookupError):
    """Raised when a provider key has not been configured for a user."""


def get_api_key(user: User, provider: str) -> str:
    try:
        record = APIKeyStore.objects.get(user=user, provider=provider, is_active=True)
    except APIKeyStore.DoesNotExist as exc:
        raise MissingAPIKeyError(
            f"Configure an active {provider.title()} API key in Settings before continuing."
        ) from exc
    try:
        return record.get_secret()
    except ValueError as exc:
        raise MissingAPIKeyError(str(exc)) from exc
