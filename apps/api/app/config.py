from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from logan_analysis.activities.ingestion import DEFAULT_MAX_INPUT_BYTES


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


LOCAL_WEB_ORIGINS = (
    "http://localhost:3000",
    "http://127.0.0.1:3000",
)
AI_PLATFORM_DEFAULT_TRUST_TOKEN_HEADER = "X-XXXX-E2E-Trust-Token"
AI_PLATFORM_DEFAULT_TRACKING_PREFIX = "EFP"
# The deployment settings an AI Platform provider needs, as (environment variable, attribute).
AI_PLATFORM_ENDPOINT_SETTINGS = (
    ("LOGAN_AI_PLATFORM_CHAT_HOST", "ai_platform_chat_host"),
    ("LOGAN_AI_PLATFORM_CHAT_URI", "ai_platform_chat_uri"),
    ("LOGAN_AI_PLATFORM_IB2B_HOST", "ai_platform_ib2b_host"),
    ("LOGAN_AI_PLATFORM_IB2B_URI", "ai_platform_ib2b_uri"),
)


@dataclass(frozen=True)
class Settings:
    env: str = os.getenv("LOGAN_ENV", "development")
    secret_key: str = os.getenv("LOGAN_SECRET_KEY", "change-me")
    database_path: str = os.getenv("LOGAN_DATABASE_PATH", ".logan/logan.db")
    local_object_store_dir: str = os.getenv(
        "LOGAN_LOCAL_OBJECT_STORE_DIR",
        str(Path.cwd() / ".logan" / "object-store"),
    )
    max_upload_bytes: int = int(
        os.getenv("LOGAN_MAX_UPLOAD_BYTES", str(DEFAULT_MAX_INPUT_BYTES))
    )
    web_base_url: str | None = _env_first("LOGAN_WEB_BASE_URL")
    cors_allowed_origins: str = os.getenv(
        "LOGAN_CORS_ALLOWED_ORIGINS",
        ",".join(LOCAL_WEB_ORIGINS),
    )
    log_level: str = os.getenv("LOGAN_LOG_LEVEL", "INFO")
    sso_authorize_url: str = os.getenv("LOGAN_SSO_AUTHORIZE_URL", "")
    sso_token_url: str = os.getenv("LOGAN_SSO_TOKEN_URL", "")
    sso_client_id: str = os.getenv("LOGAN_SSO_CLIENT_ID", "")
    sso_authorize_scope: str = os.getenv("LOGAN_SSO_AUTHORIZE_SCOPE", "openid profile email")
    sso_token_scope: str = os.getenv("LOGAN_SSO_TOKEN_SCOPE", "openid profile email")
    sso_tls_verify: bool = _env_bool("LOGAN_SSO_TLS_VERIFY", True)
    sso_timeout_seconds: float = float(os.getenv("LOGAN_SSO_TIMEOUT_SECONDS", "15"))

    # AI providers are configured per user in the web application, but the AI Platform
    # endpoints and transport belong to the deployment: a user supplies only credentials.
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
    # A blank value falls back to the default: these become HTTP header names and values.
    ai_platform_trust_token_header: str = (
        _env_first("LOGAN_AI_PLATFORM_TRUST_TOKEN_HEADER") or AI_PLATFORM_DEFAULT_TRUST_TOKEN_HEADER
    )
    ai_platform_tracking_prefix: str = (
        _env_first("LOGAN_AI_PLATFORM_TRACKING_PREFIX") or AI_PLATFORM_DEFAULT_TRACKING_PREFIX
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

    # GitHub Copilot transport: device-flow sign-in on github.com and completions on the
    # Copilot API. An empty proxy honours the process HTTP(S)_PROXY variables.
    github_copilot_timeout_seconds: float = float(
        os.getenv("LOGAN_GITHUB_COPILOT_TIMEOUT_SECONDS", "120")
    )
    github_copilot_ca_bundle: str | None = _env_first(
        "LOGAN_GITHUB_COPILOT_CA_BUNDLE",
        "SSL_CERT_FILE",
        "REQUESTS_CA_BUNDLE",
    )
    github_copilot_tls_verify: bool = _env_bool("LOGAN_GITHUB_COPILOT_TLS_VERIFY", True)
    github_copilot_proxy_url: str | None = _env_first("LOGAN_GITHUB_COPILOT_PROXY_URL")
    github_copilot_trust_env: bool = _env_bool("LOGAN_GITHUB_COPILOT_TRUST_ENV", True)

    @property
    def sso_enabled(self) -> bool:
        return bool(self.sso_authorize_url.strip())

    @property
    def sso_configured(self) -> bool:
        return all(
            value.strip()
            for value in (
                self.sso_authorize_url,
                self.sso_token_url,
                self.sso_client_id,
            )
        )

    @property
    def default_user_enabled(self) -> bool:
        return self.env.strip().lower() == "development" and not self.sso_enabled

    @property
    def secure_cookies(self) -> bool:
        return self.env.strip().lower() == "production"

    def validate_for_runtime(self) -> None:
        errors: list[str] = []
        if self.max_upload_bytes <= 0:
            errors.append("LOGAN_MAX_UPLOAD_BYTES must be greater than zero")
        if self.sso_enabled and not self.sso_configured:
            errors.append(
                "LOGAN_SSO_TOKEN_URL and LOGAN_SSO_CLIENT_ID are required "
                "when LOGAN_SSO_AUTHORIZE_URL is configured"
            )
        elif self.env.strip().lower() != "development" and not self.sso_configured:
            errors.append("SSO URLs and client id are required")
        if self.env.strip().lower() == "production":
            if len(self.secret_key.strip()) < 32 or self.secret_key == "change-me":
                errors.append("LOGAN_SECRET_KEY must contain at least 32 characters")
            if not self.sso_tls_verify:
                errors.append("LOGAN_SSO_TLS_VERIFY must be true")
            if not self.ai_platform_tls_verify:
                errors.append("LOGAN_AI_PLATFORM_TLS_VERIFY must be true")
            if not self.github_copilot_tls_verify:
                errors.append("LOGAN_GITHUB_COPILOT_TLS_VERIFY must be true")
        # httpx loads a CA bundle when the client is built, which now happens on the first
        # provider request; checking here keeps a bad path a startup error with a clear name.
        for name, ca_bundle, tls_verify in (
            ("LOGAN_AI_PLATFORM_CA_BUNDLE", self.ai_platform_ca_bundle, self.ai_platform_tls_verify),
            (
                "LOGAN_GITHUB_COPILOT_CA_BUNDLE",
                self.github_copilot_ca_bundle,
                self.github_copilot_tls_verify,
            ),
        ):
            if tls_verify and ca_bundle and not Path(ca_bundle).is_file():
                errors.append(
                    f"{name} (or SSL_CERT_FILE / REQUESTS_CA_BUNDLE) must point to a CA bundle file"
                )
        if errors:
            raise ValueError("Invalid configuration: " + "; ".join(errors))

    def cors_origins(self) -> list[str]:
        origins = [
            origin.strip()
            for origin in self.cors_allowed_origins.split(",")
            if origin.strip()
        ]
        if self.env.strip().lower() == "development":
            origins.extend(origin for origin in LOCAL_WEB_ORIGINS if origin not in origins)
        return origins

    def public_web_base_url(self) -> str | None:
        if self.web_base_url:
            return self.web_base_url.rstrip("/")
        origins = self.cors_origins()
        return origins[0].rstrip("/") if origins else None

    def missing_ai_platform_settings(self) -> list[str]:
        """Environment variables an AI Platform provider needs that this deployment lacks.

        Users supply only their own credentials, so without these endpoints an AI Platform
        provider cannot be created. The catalog and the provider validation both report
        this list so they can never disagree.
        """
        return [
            name
            for name, attribute in AI_PLATFORM_ENDPOINT_SETTINGS
            if not (getattr(self, attribute) or "").strip()
        ]

    @property
    def ai_platform_configured(self) -> bool:
        """Whether this deployment can reach AI Platform at all."""
        return not self.missing_ai_platform_settings()

    def ai_platform_httpx_client_kwargs(self) -> dict[str, object]:
        return _httpx_client_kwargs(
            timeout=self.ai_platform_timeout_seconds,
            tls_verify=self.ai_platform_tls_verify,
            ca_bundle=self.ai_platform_ca_bundle,
            trust_env=self.ai_platform_trust_env,
            proxy_url=self.ai_platform_proxy_url,
        )

    def github_copilot_httpx_client_kwargs(self) -> dict[str, object]:
        return _httpx_client_kwargs(
            timeout=self.github_copilot_timeout_seconds,
            tls_verify=self.github_copilot_tls_verify,
            ca_bundle=self.github_copilot_ca_bundle,
            trust_env=self.github_copilot_trust_env,
            proxy_url=self.github_copilot_proxy_url,
        )

    def sso_httpx_client_kwargs(self) -> dict[str, object]:
        return {
            "timeout": self.sso_timeout_seconds,
            "verify": self.sso_tls_verify,
            "trust_env": True,
        }


def _httpx_client_kwargs(
    *,
    timeout: float,
    tls_verify: bool,
    ca_bundle: str | None,
    trust_env: bool,
    proxy_url: str | None,
) -> dict[str, object]:
    kwargs: dict[str, object] = {
        "timeout": timeout,
        "verify": ca_bundle if tls_verify and ca_bundle else tls_verify,
        "trust_env": trust_env,
    }
    if proxy_url:
        kwargs["proxy"] = proxy_url
    return kwargs


def validate_runtime_settings(app_settings: Settings) -> None:
    app_settings.validate_for_runtime()


settings = Settings()
