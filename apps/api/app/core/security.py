from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta


def issue_session_token() -> str:
    return secrets.token_urlsafe(48)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def default_session_expiry() -> datetime:
    return datetime.now(UTC) + timedelta(days=7)
