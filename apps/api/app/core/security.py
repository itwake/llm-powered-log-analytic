from __future__ import annotations

import base64
import hashlib
import secrets
from datetime import UTC, datetime, timedelta

import bcrypt
from cryptography.fernet import Fernet


PASSWORD_HASH_SCHEME = "bcrypt_sha256$"
LEGACY_BCRYPT_PREFIXES = ("$2a$", "$2b$", "$2x$", "$2y$")


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


def encrypt_token(token: str, secret: str) -> bytes:
    return _fernet(secret).encrypt(token.encode())


def decrypt_token(encrypted: bytes, secret: str) -> str:
    return _fernet(secret).decrypt(encrypted).decode()


def token_hint(token: str) -> str:
    digest = hashlib.sha256(token.encode()).hexdigest()
    return digest[-8:]
