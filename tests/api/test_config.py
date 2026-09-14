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


def test_ai_platform_needs_deployment_endpoints_to_be_offered() -> None:
    assert not Settings().ai_platform_configured
    assert not Settings(ai_platform_chat_host="https://ai.example.test").ai_platform_configured
    assert Settings(
        ai_platform_chat_host="https://ai.example.test",
        ai_platform_ib2b_host="https://identity.example.test",
        ai_platform_ib2b_uri="/token",
    ).ai_platform_configured


def test_ai_platform_missing_settings_name_every_required_endpoint() -> None:
    """The catalog notice and the save-time error are built from this one list."""
    blank_chat_uri = Settings(
        ai_platform_chat_host="https://ai.example.test",
        ai_platform_chat_uri=" ",
        ai_platform_ib2b_host="https://identity.example.test",
        ai_platform_ib2b_uri="/token",
    )

    assert blank_chat_uri.missing_ai_platform_settings() == ["LOGAN_AI_PLATFORM_CHAT_URI"]
    assert not blank_chat_uri.ai_platform_configured
    assert Settings().missing_ai_platform_settings() == [
        "LOGAN_AI_PLATFORM_CHAT_HOST",
        "LOGAN_AI_PLATFORM_IB2B_HOST",
    ]


def test_runtime_validation_rejects_a_missing_ca_bundle(tmp_path) -> None:
    """httpx loads the bundle when a provider client is first built, so a bad path must be a
    startup error with the setting's name rather than a 500 on the first request."""
    bundle = tmp_path / "corp.pem"
    bundle.write_text("-----BEGIN CERTIFICATE-----\n")
    missing = str(tmp_path / "missing.pem")

    Settings(ai_platform_ca_bundle=str(bundle)).validate_for_runtime()
    with pytest.raises(ValueError, match="LOGAN_AI_PLATFORM_CA_BUNDLE"):
        Settings(ai_platform_ca_bundle=missing).validate_for_runtime()
    with pytest.raises(ValueError, match="LOGAN_GITHUB_COPILOT_CA_BUNDLE"):
        Settings(github_copilot_ca_bundle=missing).validate_for_runtime()
    # The bundle is only loaded while verification is on.
    Settings(
        github_copilot_ca_bundle=missing,
        github_copilot_tls_verify=False,
    ).validate_for_runtime()


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


def test_every_catalog_model_id_is_usable() -> None:
    """A typo in the catalog would make provider creation fail for everyone."""
    from app.llm_catalog import (
        PROVIDER_DEFAULT_MODEL,
        PROVIDER_MODELS,
        is_valid_model_id,
        normalize_model_list,
    )

    for provider_type, models in PROVIDER_MODELS.items():
        assert models, provider_type
        assert all(is_valid_model_id(model) for model in models), provider_type
        assert normalize_model_list(list(models)) == list(models), provider_type
        assert PROVIDER_DEFAULT_MODEL[provider_type] in models
