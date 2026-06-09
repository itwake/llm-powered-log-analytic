from __future__ import annotations

import bcrypt
import pytest

from app.config import Settings
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


def test_credential_keyring_encrypts_with_key_id_and_decrypts_legacy_tokens() -> None:
    legacy = security.encrypt_token("legacy-token", "legacy-secret")
    app_settings = Settings(
        credential_encryption_key="current-secret",
        credential_encryption_key_id="v2",
        credential_encryption_keyring='{"legacy":"legacy-secret"}',
    )

    encrypted, key_id = security.encrypt_token_for_settings("current-token", app_settings)

    assert key_id == "v2"
    assert encrypted.startswith(security.ENCRYPTED_TOKEN_PREFIX)
    assert security.decrypt_token(encrypted, "current-secret") == "current-token"
    assert security.decrypt_token_for_settings(encrypted, app_settings) == "current-token"
    assert security.decrypt_token_for_settings(legacy, app_settings) == "legacy-token"


def test_production_settings_reject_default_runtime_secrets() -> None:
    app_settings = Settings(
        env="production",
        secret_key="change-me",
        credential_encryption_key="change-me-local-key",
    )

    with pytest.raises(ValueError, match="Invalid production configuration"):
        app_settings.validate_for_runtime()


def test_production_settings_accept_non_default_runtime_secrets() -> None:
    Settings(
        env="production",
        secret_key="s" * 32,
        credential_encryption_key="c" * 32,
    ).validate_for_runtime()


def test_copilot_httpx_verify_defaults_to_enabled_tls_verification() -> None:
    assert Settings(copilot_ca_bundle=None, copilot_tls_verify=True).copilot_httpx_verify() is True


def test_copilot_httpx_verify_uses_configured_ca_bundle() -> None:
    assert (
        Settings(copilot_ca_bundle="/etc/ssl/corp-root-ca.pem").copilot_httpx_verify()
        == "/etc/ssl/corp-root-ca.pem"
    )


def test_copilot_httpx_verify_can_be_disabled_outside_production() -> None:
    assert Settings(copilot_tls_verify=False).copilot_httpx_verify() is False


def test_copilot_httpx_client_kwargs_enable_env_proxy_by_default() -> None:
    kwargs = Settings().copilot_httpx_client_kwargs()

    assert kwargs["trust_env"] is True
    assert "proxy" not in kwargs


def test_copilot_httpx_client_kwargs_include_explicit_proxy() -> None:
    kwargs = Settings(
        copilot_proxy_url="http://proxy.example:8080",
        copilot_trust_env=False,
    ).copilot_httpx_client_kwargs()

    assert kwargs["proxy"] == "http://proxy.example:8080"
    assert kwargs["trust_env"] is False


def test_production_settings_reject_disabled_copilot_tls_verification() -> None:
    app_settings = Settings(
        env="production",
        secret_key="s" * 32,
        credential_encryption_key="c" * 32,
        copilot_tls_verify=False,
    )

    with pytest.raises(ValueError, match="LOGAN_COPILOT_TLS_VERIFY"):
        app_settings.validate_for_runtime()
