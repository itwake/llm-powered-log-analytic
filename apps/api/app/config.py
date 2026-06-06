from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


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
    copilot_oauth_client_id: str = os.getenv(
        "LOGAN_COPILOT_OAUTH_CLIENT_ID", "Iv1.b507a08c87ecfe98"
    )
    github_copilot_token: str | None = os.getenv("LOGAN_GITHUB_COPILOT_TOKEN") or None
    github_source_token: str | None = os.getenv("LOGAN_GITHUB_SOURCE_TOKEN") or None
    copilot_timeout_seconds: float = float(os.getenv("LOGAN_COPILOT_TIMEOUT_SECONDS", "30"))
    database_url: str | None = os.getenv("LOGAN_DATABASE_URL") or None
    store_backend: str = os.getenv("LOGAN_STORE_BACKEND", "auto")
    object_store_backend: str = os.getenv("LOGAN_OBJECT_STORE_BACKEND", "local")
    local_object_store_dir: str = os.getenv(
        "LOGAN_LOCAL_OBJECT_STORE_DIR", str(Path.cwd() / ".logan" / "object-store")
    )
    secure_cookies: bool = os.getenv("LOGAN_ENV", "development") == "production"
    raw_log_retention_days: int = int(os.getenv("LOGAN_RAW_LOG_RETENTION_DAYS", "30"))
    report_retention_days: int = int(os.getenv("LOGAN_REPORT_RETENTION_DAYS", "365"))
    audit_retention_days: int = int(os.getenv("LOGAN_AUDIT_RETENTION_DAYS", "730"))
    analytics_sinks_enabled: bool = _env_bool("LOGAN_ANALYTICS_SINKS_ENABLED", False)
    clickhouse_url: str | None = os.getenv("LOGAN_CLICKHOUSE_URL") or None
    clickhouse_database: str = os.getenv("LOGAN_CLICKHOUSE_DATABASE", "logan")
    clickhouse_username: str | None = os.getenv("LOGAN_CLICKHOUSE_USERNAME") or None
    clickhouse_password: str | None = os.getenv("LOGAN_CLICKHOUSE_PASSWORD") or None
    opensearch_url: str | None = os.getenv("LOGAN_OPENSEARCH_URL") or None
    opensearch_username: str | None = os.getenv("LOGAN_OPENSEARCH_USERNAME") or None
    opensearch_password: str | None = os.getenv("LOGAN_OPENSEARCH_PASSWORD") or None
    analytics_sink_failure_mode: str = os.getenv(
        "LOGAN_ANALYTICS_SINK_FAILURE_MODE", "warn"
    ).lower()


settings = Settings()
