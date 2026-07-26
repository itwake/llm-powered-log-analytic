from __future__ import annotations

import pytest

from app.config import Settings


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
