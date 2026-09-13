"""Encryption at rest for provider credentials stored in the database.

Values are encrypted with Fernet using a key derived from ``LOGAN_SECRET_KEY`` (SHA-256, base64).
Rotating the secret key therefore invalidates stored provider credentials; users must re-enter
them. Encrypted values carry a version prefix so the format can evolve.
"""

from __future__ import annotations

import base64
import hashlib
import json
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

ENCRYPTED_PREFIX = "enc:v1:"


class SecretDecryptionError(RuntimeError):
    """Raised when a stored secret cannot be decrypted with the configured key."""


def fernet_for_secret_key(secret_key: str) -> Fernet:
    digest = hashlib.sha256(secret_key.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


class SecretCipher:
    def __init__(self, secret_key: str) -> None:
        self._fernet = fernet_for_secret_key(secret_key)

    def encrypt_text(self, value: str) -> str:
        token = self._fernet.encrypt(value.encode("utf-8")).decode("ascii")
        return f"{ENCRYPTED_PREFIX}{token}"

    def decrypt_text(self, value: str) -> str:
        if not value.startswith(ENCRYPTED_PREFIX):
            raise SecretDecryptionError("stored secret has an unknown format")
        try:
            return self._fernet.decrypt(value[len(ENCRYPTED_PREFIX):].encode("ascii")).decode(
                "utf-8"
            )
        except (InvalidToken, ValueError, UnicodeDecodeError) as exc:
            raise SecretDecryptionError(
                "stored secret cannot be decrypted; LOGAN_SECRET_KEY may have changed"
            ) from exc

    def encrypt_json(self, values: dict[str, Any]) -> str | None:
        cleaned = {
            str(key): str(value)
            for key, value in values.items()
            if isinstance(value, str) and value
        }
        if not cleaned:
            return None
        return self.encrypt_text(json.dumps(cleaned, separators=(",", ":"), sort_keys=True))

    def decrypt_json(self, value: str | None) -> dict[str, str]:
        if not value:
            return {}
        try:
            payload = json.loads(self.decrypt_text(value))
        except json.JSONDecodeError as exc:
            raise SecretDecryptionError("stored secret payload is not valid JSON") from exc
        if not isinstance(payload, dict):
            raise SecretDecryptionError("stored secret payload is not an object")
        return {str(key): str(item) for key, item in payload.items() if isinstance(item, str)}


__all__ = ["ENCRYPTED_PREFIX", "SecretCipher", "SecretDecryptionError", "fernet_for_secret_key"]
