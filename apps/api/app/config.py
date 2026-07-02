from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _origin_list(value: str | None) -> list[str]:
    if value is None:
        return []
    return [origin.strip() for origin in value.split(",") if origin.strip()]


def _env_first(*names: str) -> str | None:
    for name in names:
        value = os.getenv(name)
        if value and value.strip():
            return value.strip()
    env_by_lower = {key.lower(): value for key, value in os.environ.items()}
    for name in names:
        value = env_by_lower.get(name.lower())
        if value and value.strip():
            return value.strip()
    return None


PRODUCTION_ENV_NAMES = {"prod", "production"}
DEFAULT_SECRET_KEYS = {"", "change-me", "logan-local-dev-secret"}
DEFAULT_CREDENTIAL_ENCRYPTION_KEYS = {
    "",
    "change-me-local-key",
    "logan-local-dev-credential-key",
}
STANDARD_PROXY_ENV_NAMES = (
    "HTTPS_PROXY",
    "https_proxy",
    "HTTP_PROXY",
    "http_proxy",
    "ALL_PROXY",
    "all_proxy",
)
DEFAULT_SQLITE_DATABASE_URL = "sqlite:///.logan/logan.db"


def _is_unsafe_production_secret(value: str, unsafe_values: Iterable[str]) -> bool:
    return value.strip() in unsafe_values or len(value.strip()) < 32


@dataclass(frozen=True)
class Settings:
    env: str = os.getenv("LOGAN_ENV", "development")
    secret_key: str = os.getenv("LOGAN_SECRET_KEY", "change-me")
    credential_encryption_key: str = os.getenv(
        "LOGAN_CREDENTIAL_ENCRYPTION_KEY", "change-me-local-key"
    )
    credential_encryption_key_id: str = os.getenv(
        "LOGAN_CREDENTIAL_ENCRYPTION_KEY_ID", "default"
    )
    credential_encryption_keyring: str = os.getenv(
        "LOGAN_CREDENTIAL_ENCRYPTION_KEYRING", "{}"
    )
    llm_provider: str = os.getenv("LOGAN_LLM_PROVIDER", "ai_platform")
    ai_platform_model: str = os.getenv("LOGAN_AI_PLATFORM_MODEL", "gpt-5.4")
    ai_platform_reasoning_effort: str = os.getenv("LOGAN_AI_PLATFORM_REASONING_EFFORT", "high")
    github_source_token: str | None = os.getenv("LOGAN_GITHUB_SOURCE_TOKEN") or None
    ai_platform_chat_host: str | None = os.getenv("LOGAN_AI_PLATFORM_CHAT_HOST") or None
    ai_platform_chat_uri: str = os.getenv(
        "LOGAN_AI_PLATFORM_CHAT_URI", "/v1/api/v1/chat/completions"
    )
    ai_platform_ib2b_host: str | None = os.getenv("LOGAN_AI_PLATFORM_IB2B_HOST") or None
    ai_platform_ib2b_uri: str = os.getenv(
        "LOGAN_AI_PLATFORM_IB2B_URI",
        "/dsp/rest-sts/DSP_iB2B/iB2B_tokenTranslator_v2?_action=translate",
    )
    ai_platform_username: str | None = os.getenv("LOGAN_AI_PLATFORM_USERNAME") or None
    ai_platform_password: str | None = os.getenv("LOGAN_AI_PLATFORM_PASSWORD") or None
    ai_platform_usercase: str | None = os.getenv("LOGAN_AI_PLATFORM_USERCASE") or None
    ai_platform_token: str | None = os.getenv("LOGAN_AI_PLATFORM_TOKEN") or None
    ai_platform_token_expires_at: str | None = (
        os.getenv("LOGAN_AI_PLATFORM_TOKEN_EXPIRES_AT") or None
    )
    ai_platform_trust_token_header: str = os.getenv(
        "LOGAN_AI_PLATFORM_TRUST_TOKEN_HEADER", "X-XXXX-E2E-Trust-Token"
    )
    ai_platform_tracking_prefix: str = os.getenv("LOGAN_AI_PLATFORM_TRACKING_PREFIX", "EFP")
    ai_platform_max_completion_tokens: int = int(
        os.getenv("LOGAN_AI_PLATFORM_MAX_COMPLETION_TOKENS", "4096")
    )
    ai_platform_store_completions: bool = _env_bool("LOGAN_AI_PLATFORM_STORE_COMPLETIONS", False)
    ai_platform_token_ttl_seconds: int = int(os.getenv("LOGAN_AI_PLATFORM_TOKEN_TTL_SECONDS", "30"))
    ai_platform_timeout_seconds: float = float(os.getenv("LOGAN_AI_PLATFORM_TIMEOUT_SECONDS", "30"))
    ai_platform_ca_bundle: str | None = _env_first(
        "LOGAN_AI_PLATFORM_CA_BUNDLE", "SSL_CERT_FILE", "REQUESTS_CA_BUNDLE"
    )
    ai_platform_tls_verify: bool = _env_bool("LOGAN_AI_PLATFORM_TLS_VERIFY", True)
    ai_platform_proxy_url: str | None = _env_first("LOGAN_AI_PLATFORM_PROXY_URL")
    ai_platform_trust_env: bool = _env_bool("LOGAN_AI_PLATFORM_TRUST_ENV", True)
    database_url: str | None = _env_first("LOGAN_DATABASE_URL") or DEFAULT_SQLITE_DATABASE_URL
    store_backend: str = os.getenv("LOGAN_STORE_BACKEND", "auto")
    analysis_orchestrator: str = os.getenv("LOGAN_ANALYSIS_ORCHESTRATOR", "local")
    temporal_address: str = os.getenv("LOGAN_TEMPORAL_ADDRESS", "temporal:7233")
    temporal_namespace: str = os.getenv("LOGAN_TEMPORAL_NAMESPACE", "default")
    temporal_task_queue: str = os.getenv("LOGAN_TEMPORAL_TASK_QUEUE", "logan-analysis")
    temporal_activity_start_to_close_seconds: int = int(
        os.getenv("LOGAN_TEMPORAL_ACTIVITY_START_TO_CLOSE_SECONDS", "3600")
    )
    temporal_activity_max_attempts: int = int(
        os.getenv("LOGAN_TEMPORAL_ACTIVITY_MAX_ATTEMPTS", "3")
    )
    object_store_backend: str = os.getenv("LOGAN_OBJECT_STORE_BACKEND", "local")
    local_object_store_dir: str = os.getenv(
        "LOGAN_LOCAL_OBJECT_STORE_DIR", str(Path.cwd() / ".logan" / "object-store")
    )
    analysis_input_tmp_dir: str = os.getenv(
        "LOGAN_ANALYSIS_INPUT_TMP_DIR", str(Path.cwd() / ".logan" / "analysis-inputs")
    )
    s3_endpoint: str | None = os.getenv("LOGAN_S3_ENDPOINT") or None
    s3_bucket: str | None = os.getenv("LOGAN_S3_BUCKET") or None
    s3_access_key: str | None = os.getenv("LOGAN_S3_ACCESS_KEY") or None
    s3_secret_key: str | None = os.getenv("LOGAN_S3_SECRET_KEY") or None
    s3_region: str = os.getenv("LOGAN_S3_REGION", "us-east-1")
    s3_presign_expires_seconds: int = int(os.getenv("LOGAN_S3_PRESIGN_EXPIRES_SECONDS", "900"))
    s3_force_path_style: bool = _env_bool("LOGAN_S3_FORCE_PATH_STYLE", True)
    s3_multipart_threshold_bytes: int = int(
        os.getenv("LOGAN_S3_MULTIPART_THRESHOLD_BYTES", "104857600")
    )
    s3_multipart_part_size_bytes: int = int(
        os.getenv("LOGAN_S3_MULTIPART_PART_SIZE_BYTES", "67108864")
    )
    s3_multipart_max_parts: int = int(os.getenv("LOGAN_S3_MULTIPART_MAX_PARTS", "10000"))
    step_artifacts_enabled: bool = _env_bool("LOGAN_STEP_ARTIFACTS_ENABLED", True)
    step_artifact_failure_mode: str = os.getenv(
        "LOGAN_STEP_ARTIFACT_FAILURE_MODE", "warn"
    ).lower()
    secure_cookies: bool = os.getenv("LOGAN_ENV", "development") == "production"
    web_base_url: str | None = os.getenv("LOGAN_WEB_BASE_URL") or None
    sso_enabled: bool = _env_bool("LOGAN_SSO_ENABLED", False)
    sso_authorize_url: str = os.getenv(
        "LOGAN_SSO_AUTHORIZE_URL",
        "https://example.sso.com/realms/persons/protocol/openid-connect/auth",
    )
    sso_token_url: str = os.getenv(
        "LOGAN_SSO_TOKEN_URL",
        "https://example.sso.com/realms/persons/protocol/openid-connect/token",
    )
    sso_client_id: str = os.getenv("LOGAN_SSO_CLIENT_ID", "webapp")
    sso_authorize_scope: str = os.getenv("LOGAN_SSO_AUTHORIZE_SCOPE", "read write")
    sso_token_scope: str = os.getenv("LOGAN_SSO_TOKEN_SCOPE", "offline_access")
    sso_tls_verify: bool = _env_bool("LOGAN_SSO_TLS_VERIFY", True)
    sso_timeout_seconds: float = float(os.getenv("LOGAN_SSO_TIMEOUT_SECONDS", "15"))
    sso_mock_enabled: bool = _env_bool("LOGAN_SSO_MOCK_ENABLED", False)
    sso_mock_username: str = (os.getenv("LOGAN_SSO_MOCK_USERNAME") or "logan.mock").strip() or "logan.mock"
    sso_mock_email: str = (
        os.getenv("LOGAN_SSO_MOCK_EMAIL") or "logan.mock@example.com"
    ).strip() or "logan.mock@example.com"
    sso_mock_full_name: str = (
        os.getenv("LOGAN_SSO_MOCK_FULL_NAME") or "Logan Mock User"
    ).strip() or "Logan Mock User"
    raw_log_retention_days: int = int(os.getenv("LOGAN_RAW_LOG_RETENTION_DAYS", "30"))
    report_retention_days: int = int(os.getenv("LOGAN_REPORT_RETENTION_DAYS", "365"))
    audit_retention_days: int = int(os.getenv("LOGAN_AUDIT_RETENTION_DAYS", "730"))
    rate_limit_enabled: bool = _env_bool("LOGAN_RATE_LIMIT_ENABLED", False)
    rate_limit_requests_per_minute: int = int(
        os.getenv("LOGAN_RATE_LIMIT_REQUESTS_PER_MINUTE", "120")
    )
    log_level: str = os.getenv("LOGAN_LOG_LEVEL", "INFO")
    metrics_enabled: bool = _env_bool("LOGAN_METRICS_ENABLED", True)
    metrics_path: str = os.getenv("LOGAN_METRICS_PATH", "/metrics")
    cors_allowed_origins: str = os.getenv(
        "LOGAN_CORS_ALLOWED_ORIGINS", "http://localhost:3000"
    )
    otel_enabled: bool = _env_bool("LOGAN_OTEL_ENABLED", False)
    otel_service_name: str = os.getenv("LOGAN_OTEL_SERVICE_NAME", "logan-api")
    otel_exporter_otlp_endpoint: str | None = (
        os.getenv("LOGAN_OTEL_EXPORTER_OTLP_ENDPOINT") or None
    )
    analytics_sinks_enabled: bool = _env_bool("LOGAN_ANALYTICS_SINKS_ENABLED", False)
    clickhouse_url: str | None = os.getenv("LOGAN_CLICKHOUSE_URL") or None
    clickhouse_database: str = os.getenv("LOGAN_CLICKHOUSE_DATABASE", "logan")
    clickhouse_username: str | None = os.getenv("LOGAN_CLICKHOUSE_USERNAME") or None
    clickhouse_password: str | None = os.getenv("LOGAN_CLICKHOUSE_PASSWORD") or None
    opensearch_url: str | None = os.getenv("LOGAN_OPENSEARCH_URL") or None
    opensearch_username: str | None = os.getenv("LOGAN_OPENSEARCH_USERNAME") or None
    opensearch_password: str | None = os.getenv("LOGAN_OPENSEARCH_PASSWORD") or None
    external_analytics_queries_enabled: bool = _env_bool(
        "LOGAN_EXTERNAL_ANALYTICS_QUERIES_ENABLED", False
    )
    external_analytics_query_timeout_seconds: float = float(
        os.getenv("LOGAN_EXTERNAL_ANALYTICS_QUERY_TIMEOUT_SECONDS", "10")
    )
    analytics_sink_failure_mode: str = os.getenv(
        "LOGAN_ANALYTICS_SINK_FAILURE_MODE", "warn"
    ).lower()
    scim_bearer_token: str | None = os.getenv("LOGAN_SCIM_BEARER_TOKEN") or None
    scim_organization_id: str = (
        os.getenv("LOGAN_SCIM_ORGANIZATION_ID", "default").strip() or "default"
    )

    def validate_for_runtime(self) -> None:
        if self.env.strip().lower() not in PRODUCTION_ENV_NAMES:
            return
        errors: list[str] = []
        if _is_unsafe_production_secret(self.secret_key, DEFAULT_SECRET_KEYS):
            errors.append(
                "LOGAN_SECRET_KEY must be set to a non-default value with at least 32 characters"
            )
        if _is_unsafe_production_secret(
            self.credential_encryption_key, DEFAULT_CREDENTIAL_ENCRYPTION_KEYS
        ):
            errors.append(
                "LOGAN_CREDENTIAL_ENCRYPTION_KEY must be set to a non-default value "
                "with at least 32 characters"
            )
        if not self.ai_platform_tls_verify:
            errors.append("LOGAN_AI_PLATFORM_TLS_VERIFY must not be false in production")
        if self.sso_enabled and not self.sso_tls_verify:
            errors.append("LOGAN_SSO_TLS_VERIFY must not be false in production when SSO is enabled")
        if self.sso_mock_enabled:
            errors.append("LOGAN_SSO_MOCK_ENABLED must be false in production")
        if errors:
            raise ValueError("Invalid production configuration: " + "; ".join(errors))

    def cors_origins(self) -> list[str]:
        return _origin_list(self.cors_allowed_origins) or ["http://localhost:3000"]

    def public_web_base_url(self) -> str | None:
        if self.web_base_url and self.web_base_url.strip():
            return self.web_base_url.strip().rstrip("/")
        origins = self.cors_origins()
        if origins:
            return origins[0].rstrip("/")
        return None


    def ai_platform_httpx_verify(self) -> bool | str:
        if not self.ai_platform_tls_verify:
            return False
        return self.ai_platform_ca_bundle or True

    def ai_platform_effective_proxy_url(self) -> str | None:
        if self.ai_platform_proxy_url:
            return self.ai_platform_proxy_url
        if not self.ai_platform_trust_env:
            return None
        return _env_first(*STANDARD_PROXY_ENV_NAMES)

    def ai_platform_httpx_client_kwargs(self) -> dict[str, object]:
        kwargs: dict[str, object] = {
            "timeout": self.ai_platform_timeout_seconds,
            "verify": self.ai_platform_httpx_verify(),
            "trust_env": self.ai_platform_trust_env,
        }
        proxy_url = self.ai_platform_effective_proxy_url()
        if proxy_url:
            kwargs["proxy"] = proxy_url
        return kwargs

    def sso_httpx_client_kwargs(self) -> dict[str, object]:
        return {
            "timeout": self.sso_timeout_seconds,
            "verify": self.sso_tls_verify,
            "trust_env": True,
        }


def validate_runtime_settings(app_settings: Settings) -> None:
    app_settings.validate_for_runtime()


settings = Settings()
