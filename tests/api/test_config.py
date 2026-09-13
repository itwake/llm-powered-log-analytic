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


def test_production_requires_provider_tls_verification() -> None:
    base = dict(
        env="production",
        secret_key="s" * 40,
        sso_authorize_url="https://sso.example.test/authorize",
        sso_token_url="https://sso.example.test/token",
        sso_client_id="logan",
    )
    Settings(**base).validate_for_runtime()
    with pytest.raises(ValueError, match="LOGAN_AI_PLATFORM_TLS_VERIFY"):
        Settings(**base, ai_platform_tls_verify=False).validate_for_runtime()
    with pytest.raises(ValueError, match="LOGAN_GITHUB_COPILOT_TLS_VERIFY"):
        Settings(**base, github_copilot_tls_verify=False).validate_for_runtime()


def test_ai_platform_form_defaults_come_from_deployment_settings() -> None:
    defaults = Settings(
        ai_platform_chat_host="https://ai.example.test/",
        ai_platform_ib2b_host="https://identity.example.test",
    ).ai_platform_form_defaults()

    assert defaults["chat_host"] == "https://ai.example.test"
    assert defaults["chat_uri"] == "/v1/api/v1/chat/completions"
    assert defaults["ib2b_host"] == "https://identity.example.test"
    assert defaults["trust_token_header"] == "X-XXXX-E2E-Trust-Token"


def test_github_copilot_client_kwargs_honour_proxy_and_ca_bundle() -> None:
    kwargs = Settings(
        github_copilot_proxy_url="http://proxy.example.test:3128",
        github_copilot_ca_bundle="/etc/ssl/corp.pem",
        github_copilot_timeout_seconds=42,
    ).github_copilot_httpx_client_kwargs()

    assert kwargs == {
        "timeout": 42.0,
        "verify": "/etc/ssl/corp.pem",
        "trust_env": True,
        "proxy": "http://proxy.example.test:3128",
    }
