from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_first(*names: str) -> str | None:
    for name in names:
        value = os.getenv(name)
        if value and value.strip():
            return value.strip()
    return None


LLM_PROVIDERS = {"ai_platform", "none"}


@dataclass(frozen=True)
class Settings:
    env: str = os.getenv("LOGAN_ENV", "development")
    secret_key: str = os.getenv("LOGAN_SECRET_KEY", "change-me")
    database_path: str = os.getenv("LOGAN_DATABASE_PATH", ".logan/logan.db")
    local_object_store_dir: str = os.getenv(
        "LOGAN_LOCAL_OBJECT_STORE_DIR",
        str(Path.cwd() / ".logan" / "object-store"),
    )
    web_base_url: str | None = _env_first("LOGAN_WEB_BASE_URL")
    cors_allowed_origins: str = os.getenv(
        "LOGAN_CORS_ALLOWED_ORIGINS",
        "http://localhost:3000",
    )
    log_level: str = os.getenv("LOGAN_LOG_LEVEL", "INFO")
    sso_authorize_url: str = os.getenv("LOGAN_SSO_AUTHORIZE_URL", "")
    sso_token_url: str = os.getenv("LOGAN_SSO_TOKEN_URL", "")
    sso_client_id: str = os.getenv("LOGAN_SSO_CLIENT_ID", "")
    sso_authorize_scope: str = os.getenv("LOGAN_SSO_AUTHORIZE_SCOPE", "openid profile email")
    sso_token_scope: str = os.getenv("LOGAN_SSO_TOKEN_SCOPE", "openid profile email")
    sso_tls_verify: bool = _env_bool("LOGAN_SSO_TLS_VERIFY", True)
    sso_timeout_seconds: float = float(os.getenv("LOGAN_SSO_TIMEOUT_SECONDS", "15"))

    llm_provider: str = os.getenv("LOGAN_LLM_PROVIDER", "none")
    ai_platform_model: str = os.getenv("LOGAN_AI_PLATFORM_MODEL", "gpt-5.4")
    ai_platform_reasoning_effort: str = os.getenv(
        "LOGAN_AI_PLATFORM_REASONING_EFFORT",
        "high",
    )
    ai_platform_chat_host: str | None = _env_first("LOGAN_AI_PLATFORM_CHAT_HOST")
    ai_platform_chat_uri: str = os.getenv(
        "LOGAN_AI_PLATFORM_CHAT_URI",
        "/v1/api/v1/chat/completions",
    )
    ai_platform_ib2b_host: str | None = _env_first("LOGAN_AI_PLATFORM_IB2B_HOST")
    ai_platform_ib2b_uri: str = os.getenv(
        "LOGAN_AI_PLATFORM_IB2B_URI",
        "/dsp/rest-sts/DSP_iB2B/iB2B_tokenTranslator_v2?_action=translate",
    )
    ai_platform_username: str | None = _env_first("LOGAN_AI_PLATFORM_USERNAME")
    ai_platform_password: str | None = _env_first("LOGAN_AI_PLATFORM_PASSWORD")
    ai_platform_usercase: str | None = _env_first("LOGAN_AI_PLATFORM_USERCASE")
    ai_platform_token: str | None = _env_first("LOGAN_AI_PLATFORM_TOKEN")
    ai_platform_token_expires_at: str | None = _env_first(
        "LOGAN_AI_PLATFORM_TOKEN_EXPIRES_AT"
    )
    ai_platform_trust_token_header: str = os.getenv(
        "LOGAN_AI_PLATFORM_TRUST_TOKEN_HEADER",
        "X-XXXX-E2E-Trust-Token",
    )
    ai_platform_tracking_prefix: str = os.getenv(
        "LOGAN_AI_PLATFORM_TRACKING_PREFIX",
        "EFP",
    )
    ai_platform_max_completion_tokens: int = int(
        os.getenv("LOGAN_AI_PLATFORM_MAX_COMPLETION_TOKENS", "4096")
    )
    ai_platform_store_completions: bool = _env_bool(
        "LOGAN_AI_PLATFORM_STORE_COMPLETIONS",
        False,
    )
    ai_platform_token_ttl_seconds: int = int(
        os.getenv("LOGAN_AI_PLATFORM_TOKEN_TTL_SECONDS", "30")
    )
    ai_platform_timeout_seconds: float = float(
        os.getenv("LOGAN_AI_PLATFORM_TIMEOUT_SECONDS", "120")
    )
    ai_platform_ca_bundle: str | None = _env_first(
        "LOGAN_AI_PLATFORM_CA_BUNDLE",
        "SSL_CERT_FILE",
        "REQUESTS_CA_BUNDLE",
    )
    ai_platform_tls_verify: bool = _env_bool("LOGAN_AI_PLATFORM_TLS_VERIFY", True)
    ai_platform_proxy_url: str | None = _env_first("LOGAN_AI_PLATFORM_PROXY_URL")
    ai_platform_trust_env: bool = _env_bool("LOGAN_AI_PLATFORM_TRUST_ENV", True)

    @property
    def normalized_llm_provider(self) -> str:
        return self.llm_provider.strip().lower()

    @property
    def secure_cookies(self) -> bool:
        return self.env.strip().lower() == "production"

    def validate_for_runtime(self) -> None:
        errors: list[str] = []
        if self.normalized_llm_provider not in LLM_PROVIDERS:
            errors.append("LOGAN_LLM_PROVIDER must be ai_platform or none")
        if self.normalized_llm_provider == "ai_platform":
            if not (self.ai_platform_chat_host and self.ai_platform_chat_uri):
                errors.append("AI Platform chat host and URI are required")
            has_token = bool((self.ai_platform_token or "").strip())
            has_exchange_credentials = all(
                (
                    (self.ai_platform_ib2b_host or "").strip(),
                    (self.ai_platform_ib2b_uri or "").strip(),
                    (self.ai_platform_username or "").strip(),
                    (self.ai_platform_password or "").strip(),
                    (self.ai_platform_usercase or "").strip(),
                )
            )
            if not has_token and not has_exchange_credentials:
                errors.append(
                    "AI Platform requires a token or complete iB2B credentials"
                )
        if self.env.strip().lower() == "production":
            if len(self.secret_key.strip()) < 32 or self.secret_key == "change-me":
                errors.append("LOGAN_SECRET_KEY must contain at least 32 characters")
            if not (self.sso_authorize_url and self.sso_token_url and self.sso_client_id):
                errors.append("SSO URLs and client id are required")
            if not self.sso_tls_verify:
                errors.append("LOGAN_SSO_TLS_VERIFY must be true")
            if (
                self.normalized_llm_provider == "ai_platform"
                and not self.ai_platform_tls_verify
            ):
                errors.append("LOGAN_AI_PLATFORM_TLS_VERIFY must be true")
        if errors:
            raise ValueError("Invalid configuration: " + "; ".join(errors))

    def cors_origins(self) -> list[str]:
        return [
            origin.strip()
            for origin in self.cors_allowed_origins.split(",")
            if origin.strip()
        ]

    def public_web_base_url(self) -> str | None:
        if self.web_base_url:
            return self.web_base_url.rstrip("/")
        origins = self.cors_origins()
        return origins[0].rstrip("/") if origins else None

    def ai_platform_httpx_client_kwargs(self) -> dict[str, object]:
        kwargs: dict[str, object] = {
            "timeout": self.ai_platform_timeout_seconds,
            "verify": (
                self.ai_platform_ca_bundle
                if self.ai_platform_tls_verify and self.ai_platform_ca_bundle
                else self.ai_platform_tls_verify
            ),
            "trust_env": self.ai_platform_trust_env,
        }
        if self.ai_platform_proxy_url:
            kwargs["proxy"] = self.ai_platform_proxy_url
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
