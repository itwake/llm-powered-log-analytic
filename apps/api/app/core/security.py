from __future__ import annotations

import base64
import hashlib
import json
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
from cryptography.fernet import Fernet


PASSWORD_HASH_SCHEME = "bcrypt_sha256$"
LEGACY_BCRYPT_PREFIXES = ("$2a$", "$2b$", "$2x$", "$2y$")
ENCRYPTED_TOKEN_PREFIX = b"logan:v1:"


def _bcrypt_password_material(password: str) -> bytes:
    digest = hashlib.sha256(password.encode("utf-8")).digest()
    return base64.b64encode(digest)


def hash_password(password: str) -> str:
    hashed = bcrypt.hashpw(_bcrypt_password_material(password), bcrypt.gensalt())
    return f"{PASSWORD_HASH_SCHEME}{hashed.decode('ascii')}"


def verify_password(password: str, password_hash: str) -> bool:
    try:
        if password_hash.startswith(PASSWORD_HASH_SCHEME):
            stored_hash = password_hash.removeprefix(PASSWORD_HASH_SCHEME).encode("ascii")
            return bcrypt.checkpw(_bcrypt_password_material(password), stored_hash)
        if password_hash.startswith(LEGACY_BCRYPT_PREFIXES):
            return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("ascii"))
    except Exception:
        return False
    return False


def issue_session_token() -> str:
    return secrets.token_urlsafe(48)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def default_session_expiry() -> datetime:
    return datetime.now(UTC) + timedelta(days=365)


def _fernet(secret: str) -> Fernet:
    key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest())
    return Fernet(key)


def _encode_key_id(key_id: str) -> bytes:
    return base64.urlsafe_b64encode(key_id.encode("utf-8")).rstrip(b"=")


def _decode_key_id(encoded: bytes) -> str:
    padding = b"=" * (-len(encoded) % 4)
    return base64.urlsafe_b64decode(encoded + padding).decode("utf-8")


def parse_credential_keyring(raw_keyring: str | None) -> dict[str, str]:
    if not raw_keyring:
        return {}
    raw_keyring = raw_keyring.strip()
    if not raw_keyring:
        return {}
    try:
        parsed = json.loads(raw_keyring)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, dict):
        return {
            str(key): str(value)
            for key, value in parsed.items()
            if str(key) and str(value)
        }
    keyring: dict[str, str] = {}
    for item in raw_keyring.split(","):
        key_id, separator, secret = item.partition("=")
        if separator and key_id.strip() and secret.strip():
            keyring[key_id.strip()] = secret.strip()
    return keyring


def credential_key_id_from_settings(app_settings: Any) -> str:
    return str(getattr(app_settings, "credential_encryption_key_id", "default") or "default")


def credential_keyring_from_settings(app_settings: Any) -> dict[str, str]:
    key_id = credential_key_id_from_settings(app_settings)
    keyring = parse_credential_keyring(
        getattr(app_settings, "credential_encryption_keyring", "{}")
    )
    keyring[key_id] = str(getattr(app_settings, "credential_encryption_key"))
    return keyring


def encrypt_token(token: str, secret: str, *, key_id: str | None = None) -> bytes:
    encrypted = _fernet(secret).encrypt(token.encode())
    if not key_id:
        return encrypted
    return ENCRYPTED_TOKEN_PREFIX + _encode_key_id(key_id) + b":" + encrypted


def encrypt_token_for_settings(token: str, app_settings: Any) -> tuple[bytes, str]:
    key_id = credential_key_id_from_settings(app_settings)
    return (
        encrypt_token(
            token,
            str(getattr(app_settings, "credential_encryption_key")),
            key_id=key_id,
        ),
        key_id,
    )


def _split_encrypted_token(encrypted: bytes) -> tuple[str | None, bytes]:
    if not encrypted.startswith(ENCRYPTED_TOKEN_PREFIX):
        return None, encrypted
    remainder = encrypted.removeprefix(ENCRYPTED_TOKEN_PREFIX)
    encoded_key_id, separator, ciphertext = remainder.partition(b":")
    if not separator or not encoded_key_id or not ciphertext:
        raise ValueError("encrypted token key id header is malformed")
    return _decode_key_id(encoded_key_id), ciphertext


def decrypt_token(
    encrypted: bytes,
    secret: str,
    *,
    key_id: str | None = None,
    keyring: dict[str, str] | None = None,
) -> str:
    token_key_id, ciphertext = _split_encrypted_token(encrypted)
    candidates: list[str] = []
    if token_key_id is not None:
        if keyring and token_key_id in keyring:
            candidates.append(keyring[token_key_id])
        if token_key_id == key_id or not candidates:
            candidates.append(secret)
    else:
        candidates.append(secret)
        if keyring:
            candidates.extend(value for value in keyring.values() if value not in candidates)
    last_error: Exception | None = None
    for candidate in candidates:
        try:
            return _fernet(candidate).decrypt(ciphertext).decode()
        except Exception as exc:
            last_error = exc
    if last_error is not None:
        raise last_error
    raise ValueError("no credential decryption key is configured")


def decrypt_token_for_settings(
    encrypted: bytes,
    app_settings: Any,
    *,
    key_id: str | None = None,
) -> str:
    return decrypt_token(
        encrypted,
        str(getattr(app_settings, "credential_encryption_key")),
        key_id=key_id or credential_key_id_from_settings(app_settings),
        keyring=credential_keyring_from_settings(app_settings),
    )


def token_hint(token: str) -> str:
    digest = hashlib.sha256(token.encode()).hexdigest()
    return digest[-8:]
