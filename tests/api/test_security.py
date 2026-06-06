from __future__ import annotations

import bcrypt
import pytest

from app.core import security


def test_hash_password_uses_bcrypt_sha256_scheme() -> None:
    password_hash = security.hash_password("password123")

    assert password_hash.startswith(security.PASSWORD_HASH_SCHEME)
    assert "password123" not in password_hash
    assert security.verify_password("password123", password_hash) is True
    assert security.verify_password("wrong-password", password_hash) is False
    assert security.hash_password("password123") != password_hash


def test_hash_password_supports_passwords_longer_than_bcrypt_limit() -> None:
    password = "x" * 100
    password_hash = security.hash_password(password)

    assert security.verify_password(password, password_hash) is True
    assert security.verify_password(password + "x", password_hash) is False


def test_verify_password_returns_false_for_malformed_hashes() -> None:
    malformed_hashes = (
        "",
        "not-a-hash",
        "bcrypt_sha256$",
        "bcrypt_sha256$not-a-bcrypt-hash",
        "$2b$short",
    )

    for password_hash in malformed_hashes:
        assert security.verify_password("password123", password_hash) is False


def test_verify_password_returns_false_for_backend_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    password_hash = security.hash_password("password123")

    def raise_backend_error(_password: bytes, _stored_hash: bytes) -> bool:
        raise RuntimeError("bcrypt backend unavailable")

    monkeypatch.setattr(security.bcrypt, "checkpw", raise_backend_error)

    assert security.verify_password("password123", password_hash) is False


def test_verify_password_supports_legacy_raw_bcrypt_hashes() -> None:
    password_hash = bcrypt.hashpw(b"password123", bcrypt.gensalt()).decode("ascii")

    assert security.verify_password("password123", password_hash) is True
    assert security.verify_password("wrong-password", password_hash) is False
