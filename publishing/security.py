import base64
import hashlib
import json
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured, ValidationError


@lru_cache(maxsize=4)
def _cipher(configured_key, secret_key):
    if configured_key:
        try:
            return Fernet(configured_key.encode("ascii"))
        except (TypeError, ValueError) as exc:
            raise ImproperlyConfigured(
                "PUBLISHING_CREDENTIAL_KEY must be a valid Fernet key."
            ) from exc
    digest = hashlib.sha256(f"tubepulse-oauth:{secret_key}".encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def get_cipher():
    return _cipher(
        getattr(settings, "PUBLISHING_CREDENTIAL_KEY", "")
        or getattr(settings, "TUBEPULSE_ENCRYPTION_KEY", ""),
        settings.SECRET_KEY,
    )


def encrypt_json(payload):
    encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return get_cipher().encrypt(encoded).decode("ascii")


def decrypt_json(value):
    try:
        decoded = get_cipher().decrypt(value.encode("ascii"))
        payload = json.loads(decoded.decode("utf-8"))
    except (InvalidToken, UnicodeError, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise ValidationError(
            "Stored channel credentials cannot be decrypted. Reconnect the channel."
        ) from exc
    if not isinstance(payload, dict):
        raise ValidationError("Stored channel credentials have an invalid format.")
    return payload
