"""Authenticated encryption helpers for user-supplied provider secrets."""
from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


class SecretDecryptionError(ValueError):
    """Raised when encrypted data cannot be decrypted with the configured key."""


def _fernet() -> Fernet:
    configured = settings.TUBEPULSE_ENCRYPTION_KEY.strip()
    if configured:
        try:
            raw_key = configured.encode("ascii")
            Fernet(raw_key)
            return Fernet(raw_key)
        except (ValueError, UnicodeEncodeError) as exc:
            raise ImproperlyConfigured(
                "TUBEPULSE_ENCRYPTION_KEY must be a valid Fernet key"
            ) from exc

    # This stable derivation keeps local setup simple. Production should use a
    # dedicated Fernet key so secrets survive a Django SECRET_KEY rotation.
    digest = hashlib.sha256(settings.SECRET_KEY.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("Secret cannot be empty")
    return _fernet().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_secret(token: str) -> str:
    if not token:
        raise SecretDecryptionError("No encrypted secret is stored")
    try:
        return _fernet().decrypt(token.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError, UnicodeEncodeError) as exc:
        raise SecretDecryptionError(
            "Stored secret could not be decrypted; verify TUBEPULSE_ENCRYPTION_KEY"
        ) from exc
