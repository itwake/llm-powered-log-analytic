from __future__ import annotations

import pytest

from app.config import Settings


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
