from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    env: str = os.getenv("LOGAN_ENV", "development")
    secret_key: str = os.getenv("LOGAN_SECRET_KEY", "change-me")
    credential_encryption_key: str = os.getenv(
        "LOGAN_CREDENTIAL_ENCRYPTION_KEY", "change-me-local-key"
    )
    llm_provider: str = os.getenv("LOGAN_LLM_PROVIDER", "github_copilot")
    copilot_model: str = os.getenv("LOGAN_COPILOT_MODEL", "gpt-5.4")
    copilot_reasoning_effort: str = os.getenv("LOGAN_COPILOT_REASONING_EFFORT", "high")
    copilot_base_url: str | None = os.getenv("LOGAN_COPILOT_BASE_URL") or None
    database_url: str | None = os.getenv("LOGAN_DATABASE_URL") or None
    store_backend: str = os.getenv("LOGAN_STORE_BACKEND", "auto")
    secure_cookies: bool = os.getenv("LOGAN_ENV", "development") == "production"
    raw_log_retention_days: int = int(os.getenv("LOGAN_RAW_LOG_RETENTION_DAYS", "30"))
    report_retention_days: int = int(os.getenv("LOGAN_REPORT_RETENTION_DAYS", "365"))
    audit_retention_days: int = int(os.getenv("LOGAN_AUDIT_RETENTION_DAYS", "730"))


settings = Settings()
