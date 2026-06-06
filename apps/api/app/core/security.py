from __future__ import annotations

import base64
import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from cryptography.fernet import Fernet
from passlib.context import CryptContext


pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return pwd_context.verify(password, password_hash)


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
