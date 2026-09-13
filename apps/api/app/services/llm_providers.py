"""Validation, masking, and selection logic for user-managed AI providers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from app.config import Settings
from app.llm_catalog import (
    AI_PLATFORM_PROVIDER,
    DEFAULT_REASONING_EFFORT,
    GITHUB_COPILOT_PROVIDER,
    MAX_PROVIDER_NAME_LENGTH,
    REASONING_EFFORTS,
    default_model_for_provider,
    models_for_provider,
    normalize_model_list,
    normalize_provider_type,
    normalize_reasoning_effort,
    provider_label,
)
from app.records import LlmProviderRecord
from app.services.aiplatform_model_gateway import AIPlatformProviderConfig
from app.services.github_copilot_model_gateway import GitHubCopilotProviderConfig
from app.services.model_gateway import ModelGatewayError
from app.records import sanitize_error_message


class LlmProviderError(ValueError):
    status_code = 400


class LlmProviderNotFound(LlmProviderError):
    status_code = 404


class LlmProviderNotReady(LlmProviderError):
    status_code = 409


AI_PLATFORM_CONFIG_FIELDS: tuple[str, ...] = (
    "chat_host",
    "chat_uri",
    "ib2b_host",
    "ib2b_uri",
    "usercase",
    "trust_token_header",
    "tracking_prefix",
    "username",
    "token_expires_at",
)
AI_PLATFORM_SECRET_FIELDS: tuple[str, ...] = ("password", "token")
GITHUB_COPILOT_CONFIG_FIELDS: tuple[str, ...] = ("api_base_url", "github_login")
GITHUB_COPILOT_SECRET_FIELDS: tuple[str, ...] = ("github_token",)
PROVIDER_CONFIG_FIELDS: dict[str, tuple[str, ...]] = {
    AI_PLATFORM_PROVIDER: AI_PLATFORM_CONFIG_FIELDS,
    GITHUB_COPILOT_PROVIDER: GITHUB_COPILOT_CONFIG_FIELDS,
}
PROVIDER_SECRET_FIELDS: dict[str, tuple[str, ...]] = {
    AI_PLATFORM_PROVIDER: AI_PLATFORM_SECRET_FIELDS,
    GITHUB_COPILOT_PROVIDER: GITHUB_COPILOT_SECRET_FIELDS,
}
_URL_FIELDS = frozenset({"chat_host", "ib2b_host", "api_base_url"})
MAX_CONFIG_VALUE_LENGTH = 500
MAX_SECRET_LENGTH = 8192


@dataclass(frozen=True)
class ProviderDefinition:
    name: str
    provider_type: str
    config: dict[str, str]
    secrets: dict[str, str]
    models: list[str]
    default_model: str
    default_reasoning_effort: str


@dataclass(frozen=True)
class InferenceSelection:
    provider: LlmProviderRecord
    model: str
    reasoning_effort: str


def normalize_provider_definition(
    *,
    settings: Settings,
    provider_type: str | None,
    name: str | None,
    models: list[str] | None,
    default_model: str | None,
    default_reasoning_effort: str | None,
    config: dict[str, Any] | None,
    secrets: dict[str, Any] | None,
    existing: LlmProviderRecord | None = None,
) -> ProviderDefinition:
    """Merge a create or update payload with the existing record and validate the result."""
    if existing is not None:
        canonical_type = existing.provider_type
        if provider_type is not None and normalize_provider_type(provider_type) != canonical_type:
            raise LlmProviderError("provider_type cannot be changed after creation")
    else:
        canonical_type = normalize_provider_type(provider_type) or ""
        if not canonical_type:
            raise LlmProviderError("provider_type must be ai_platform or github_copilot")

    normalized_name = (name if name is not None else (existing.name if existing else "")).strip()
    if not normalized_name:
        raise LlmProviderError("name is required")
    if len(normalized_name) > MAX_PROVIDER_NAME_LENGTH:
        raise LlmProviderError(f"name must be at most {MAX_PROVIDER_NAME_LENGTH} characters")

    if models is None:
        normalized_models = list(existing.models) if existing else list(models_for_provider(canonical_type))
    else:
        try:
            normalized_models = normalize_model_list(models)
        except ValueError as exc:
            raise LlmProviderError(str(exc)) from exc
    if not normalized_models:
        raise LlmProviderError("at least one model is required")

    if default_model is not None and default_model.strip():
        chosen_model = default_model.strip()
    elif existing is not None and existing.default_model in normalized_models:
        chosen_model = existing.default_model
    else:
        catalog_default = default_model_for_provider(canonical_type)
        chosen_model = catalog_default if catalog_default in normalized_models else normalized_models[0]
    if chosen_model not in normalized_models:
        raise LlmProviderError("default_model must be one of the enabled models")

    if default_reasoning_effort is not None:
        effort = normalize_reasoning_effort(default_reasoning_effort, default=DEFAULT_REASONING_EFFORT)
        if effort is None:
            supported = ", ".join(REASONING_EFFORTS)
            raise LlmProviderError(f"default_reasoning_effort must be one of: {supported}")
    else:
        effort = existing.default_reasoning_effort if existing else DEFAULT_REASONING_EFFORT

    merged_config = _merge_fields(
        existing.config if existing else {},
        config,
        allowed=PROVIDER_CONFIG_FIELDS[canonical_type],
        max_length=MAX_CONFIG_VALUE_LENGTH,
        label="config",
    )
    merged_secrets = _merge_fields(
        existing.secrets if existing else {},
        secrets,
        allowed=PROVIDER_SECRET_FIELDS[canonical_type],
        max_length=MAX_SECRET_LENGTH,
        label="secrets",
        strip=False,
    )
    for field_name in _URL_FIELDS & set(merged_config):
        merged_config[field_name] = _validated_origin(merged_config[field_name], field_name)

    if canonical_type == AI_PLATFORM_PROVIDER:
        _validate_ai_platform(settings, merged_config, merged_secrets)

    return ProviderDefinition(
        name=normalized_name,
        provider_type=canonical_type,
        config=merged_config,
        secrets=merged_secrets,
        models=normalized_models,
        default_model=chosen_model,
        default_reasoning_effort=effort,
    )


def credentials_configured(provider: LlmProviderRecord, settings: Settings) -> bool:
    if provider.provider_type == AI_PLATFORM_PROVIDER:
        return AIPlatformProviderConfig.from_provider(provider, settings).credentials_configured
    if provider.provider_type == GITHUB_COPILOT_PROVIDER:
        return GitHubCopilotProviderConfig.from_provider(provider).credentials_configured
    return False


def credential_summary(provider: LlmProviderRecord, settings: Settings) -> str | None:
    if provider.provider_type == AI_PLATFORM_PROVIDER:
        config = AIPlatformProviderConfig.from_provider(provider, settings)
        if config.token.strip():
            return "Trust token configured"
        if config.exchange_credentials_configured:
            return f"iB2B credentials for {config.username}"
        return None
    if provider.provider_type == GITHUB_COPILOT_PROVIDER:
        config = GitHubCopilotProviderConfig.from_provider(provider)
        if not config.credentials_configured:
            return None
        login = provider.config.get("github_login")
        if isinstance(login, str) and login.strip():
            return f"GitHub account {login.strip()}"
        return "GitHub token configured"
    return None


def provider_public_view(provider: LlmProviderRecord, settings: Settings) -> dict[str, Any]:
    """The API representation of a provider. Secrets are reported by name only."""
    allowed = PROVIDER_CONFIG_FIELDS.get(provider.provider_type, ())
    return {
        "provider_id": provider.id,
        "name": provider.name,
        "provider_type": provider.provider_type,
        "provider_label": provider_label(provider.provider_type),
        "models": list(provider.models),
        "default_model": provider.default_model,
        "default_reasoning_effort": provider.default_reasoning_effort,
        "is_default": provider.is_default,
        "credentials_configured": credentials_configured(provider, settings),
        "credential_summary": credential_summary(provider, settings),
        "secret_fields": sorted(key for key, value in provider.secrets.items() if value),
        "config": {
            key: provider.config[key]
            for key in allowed
            if isinstance(provider.config.get(key), str) and provider.config[key]
        },
        "created_at": provider.created_at,
        "updated_at": provider.updated_at,
    }


def resolve_inference_selection(
    *,
    store: Any,
    settings: Settings,
    user_id: str,
    provider_id: str | None,
    model: str | None,
    reasoning_effort: str | None,
    fallback_provider_id: str | None = None,
) -> InferenceSelection:
    """Pick the provider, model, and thinking level for one request."""
    provider: LlmProviderRecord | None = None
    if provider_id:
        provider = store.get_llm_provider(provider_id)
        if provider is None or provider.user_id != user_id:
            raise LlmProviderNotFound("AI provider not found")
    else:
        if fallback_provider_id:
            candidate = store.get_llm_provider(fallback_provider_id)
            if candidate is not None and candidate.user_id == user_id:
                provider = candidate
        if provider is None:
            provider = store.get_default_llm_provider(user_id)
        if provider is None:
            raise LlmProviderNotReady(
                "No AI provider is configured; add one under AI Providers first"
            )

    chosen_model = (model or "").strip() or provider.default_model
    if chosen_model not in provider.models:
        raise LlmProviderError(
            f"model {chosen_model[:60]} is not enabled for provider {provider.name}"
        )
    effort = normalize_reasoning_effort(reasoning_effort, default=provider.default_reasoning_effort)
    if effort is None:
        supported = ", ".join(REASONING_EFFORTS)
        raise LlmProviderError(f"reasoning_effort must be one of: {supported}")
    if not credentials_configured(provider, settings):
        raise LlmProviderNotReady(
            f"AI provider {provider.name} has no usable credentials; "
            "complete its setup under AI Providers"
        )
    return InferenceSelection(provider=provider, model=chosen_model, reasoning_effort=effort)


async def smoke_test_provider(
    *,
    provider: LlmProviderRecord,
    gateway: Any,
    user_id: str,
) -> tuple[bool, str]:
    """Send a minimal completion through the provider and report the outcome."""
    try:
        response = await gateway.responses(
            user_id=user_id,
            model=provider.default_model,
            instructions="You are a connectivity check. Reply with the single word OK.",
            input=[{"role": "user", "content": [{"type": "input_text", "text": "ping"}]}],
            stream=False,
            metadata={"purpose": "provider_test"},
            reasoning_effort="low",
        )
    except ModelGatewayError as exc:
        return False, sanitize_error_message(exc, max_length=600)
    except Exception as exc:
        return False, sanitize_error_message(exc, max_length=600)
    if not isinstance(response, dict):
        return False, "the provider returned a stream instead of a completion"
    text = str(response.get("output_text") or "").strip()
    label = provider_label(provider.provider_type)
    if text:
        return True, f"{label} responded with model {provider.default_model}."
    return True, f"{label} accepted the request for model {provider.default_model}."


def _merge_fields(
    current: dict[str, Any],
    updates: dict[str, Any] | None,
    *,
    allowed: tuple[str, ...],
    max_length: int,
    label: str,
    strip: bool = True,
) -> dict[str, str]:
    merged: dict[str, str] = {
        key: str(value)
        for key, value in current.items()
        if key in allowed and isinstance(value, str) and value
    }
    if updates is None:
        return merged
    for key, value in updates.items():
        if key not in allowed:
            raise LlmProviderError(f"unknown {label} field: {str(key)[:40]}")
        if value is None or (isinstance(value, str) and not value.strip()):
            merged.pop(key, None)
            continue
        if not isinstance(value, str):
            raise LlmProviderError(f"{label} field {key} must be a string")
        text = value.strip() if strip else value
        if len(text) > max_length:
            raise LlmProviderError(f"{label} field {key} is too long")
        merged[key] = text
    return merged


def _validated_origin(value: str, field_name: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise LlmProviderError(f"{field_name} must be an http(s) URL")
    return value.rstrip("/")


def _validate_ai_platform(
    settings: Settings,
    config: dict[str, str],
    secrets: dict[str, str],
) -> None:
    defaults = settings.ai_platform_form_defaults()
    if not (config.get("chat_host") or defaults["chat_host"]):
        raise LlmProviderError("chat_host is required for an AI Platform provider")
    username = config.get("username", "")
    password = secrets.get("password", "")
    usercase = config.get("usercase", "")
    if (username or password) and not (username and password and usercase):
        raise LlmProviderError(
            "iB2B credentials require username, password, and usercase together"
        )
    if password and not (config.get("ib2b_host") or defaults["ib2b_host"]):
        raise LlmProviderError("ib2b_host is required for iB2B credentials")
    if password and not (config.get("ib2b_uri") or defaults["ib2b_uri"]):
        raise LlmProviderError("ib2b_uri is required for iB2B credentials")
