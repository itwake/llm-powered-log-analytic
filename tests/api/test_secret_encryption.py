from __future__ import annotations

import pytest

from app.services.secret_encryption import (
    ENCRYPTED_PREFIX,
    SecretCipher,
    SecretDecryptionError,
)


def test_secret_roundtrip_hides_plaintext() -> None:
    cipher = SecretCipher("logan-secret-key")
    encrypted = cipher.encrypt_json({"password": "hunter2", "token": "", "ignored": None})

    assert encrypted is not None
    assert encrypted.startswith(ENCRYPTED_PREFIX)
    assert "hunter2" not in encrypted
    assert cipher.decrypt_json(encrypted) == {"password": "hunter2"}


def test_empty_secrets_are_stored_as_null() -> None:
    cipher = SecretCipher("logan-secret-key")

    assert cipher.encrypt_json({}) is None
    assert cipher.encrypt_json({"token": ""}) is None
    assert cipher.decrypt_json(None) == {}


def test_decrypting_with_another_key_fails_clearly() -> None:
    encrypted = SecretCipher("first-key").encrypt_json({"token": "abc"})

    with pytest.raises(SecretDecryptionError, match="LOGAN_SECRET_KEY"):
        SecretCipher("second-key").decrypt_json(encrypted)
    with pytest.raises(SecretDecryptionError, match="unknown format"):
        SecretCipher("first-key").decrypt_json("plain-text")
