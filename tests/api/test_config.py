from __future__ import annotations

import pytest

from app.config import Settings


def test_default_upload_limit_is_300_mib() -> None:
    assert Settings().max_upload_bytes == 300 * 1024 * 1024


def test_upload_limit_must_be_positive() -> None:
    with pytest.raises(ValueError, match="LOGAN_MAX_UPLOAD_BYTES"):
        Settings(max_upload_bytes=0).validate_for_runtime()


def test_development_cors_supports_both_loopback_hostnames() -> None:
    settings = Settings(
        env="development",
        cors_allowed_origins="http://localhost:3000",
    )

    assert settings.cors_origins() == [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]


def test_production_cors_uses_only_configured_origins() -> None:
    settings = Settings(
        env="production",
        cors_allowed_origins="https://logan.example.com",
    )

    assert settings.cors_origins() == ["https://logan.example.com"]


def test_development_uses_default_user_when_sso_authorize_url_is_empty() -> None:
    settings = Settings(env="development", sso_authorize_url="")

    assert settings.default_user_enabled
    assert not settings.sso_enabled


def test_non_development_requires_sso() -> None:
    with pytest.raises(ValueError, match="SSO URLs and client id"):
        Settings(env="staging").validate_for_runtime()


def test_sso_authorize_url_requires_token_url_and_client_id() -> None:
    with pytest.raises(ValueError, match="LOGAN_SSO_TOKEN_URL"):
        Settings(
            env="development",
            sso_authorize_url="https://sso.example.test/authorize",
        ).validate_for_runtime()


def test_ai_platform_requires_usable_credentials() -> None:
    with pytest.raises(ValueError, match="token or complete iB2B credentials"):
        Settings(
            llm_provider="ai_platform",
            ai_platform_chat_host="https://ai.example.test",
        ).validate_for_runtime()


def test_ai_platform_accepts_a_configured_token() -> None:
    Settings(
        llm_provider="ai_platform",
        ai_platform_chat_host="https://ai.example.test",
        ai_platform_token="trust-token",
    ).validate_for_runtime()
