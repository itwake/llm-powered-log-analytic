"""Validation and selection logic for user-managed AI providers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

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
from app.records import LlmProviderRecord, sanitize_error_message
from app.services.aiplatform_model_gateway import AIPlatformCredentials
from app.services.github_copilot_model_gateway import GitHubCopilotCredentials
from app.services.model_gateway import ModelGatewayError


class LlmProviderError(ValueError):
    status_code = 400


class LlmProviderNotFound(LlmProviderError):
    status_code = 404


class LlmProviderNotReady(LlmProviderError):
    status_code = 409


# Only per-user credentials are stored on a provider. Endpoints and transport headers are
# deployment settings in app/config.py, so a user never has to know them.
AI_PLATFORM_CONFIG_FIELDS: tuple[str, ...] = ("username", "usercase")
AI_PLATFORM_SECRET_FIELDS: tuple[str, ...] = ("password",)
GITHUB_COPILOT_CONFIG_FIELDS: tuple[str, ...] = ("github_login",)
GITHUB_COPILOT_SECRET_FIELDS: tuple[str, ...] = ("github_token",)
PROVIDER_CONFIG_FIELDS: dict[str, tuple[str, ...]] = {
    AI_PLATFORM_PROVIDER: AI_PLATFORM_CONFIG_FIELDS,
    GITHUB_COPILOT_PROVIDER: GITHUB_COPILOT_CONFIG_FIELDS,
}
PROVIDER_SECRET_FIELDS: dict[str, tuple[str, ...]] = {
    AI_PLATFORM_PROVIDER: AI_PLATFORM_SECRET_FIELDS,
    GITHUB_COPILOT_PROVIDER: GITHUB_COPILOT_SECRET_FIELDS,
}
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
        normalized_models = (
            list(existing.models) if existing else list(models_for_provider(canonical_type))
        )
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
        chosen_model = (
            catalog_default if catalog_default in normalized_models else normalized_models[0]
        )
    if chosen_model not in normalized_models:
        raise LlmProviderError("default_model must be one of the enabled models")

    if default_reasoning_effort is not None:
        effort = normalize_reasoning_effort(
            default_reasoning_effort,
            default=DEFAULT_REASONING_EFFORT,
        )
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


def credentials_configured(provider: LlmProviderRecord) -> bool:
    if provider.provider_type == AI_PLATFORM_PROVIDER:
        return AIPlatformCredentials.from_provider(provider).configured
    if provider.provider_type == GITHUB_COPILOT_PROVIDER:
        return GitHubCopilotCredentials.from_provider(provider).configured
    return False


def credential_summary(provider: LlmProviderRecord) -> str | None:
    if provider.provider_type == AI_PLATFORM_PROVIDER:
        credentials = AIPlatformCredentials.from_provider(provider)
        if credentials.configured:
            return f"iB2B credentials for {credentials.username}"
        return None
    if provider.provider_type == GITHUB_COPILOT_PROVIDER:
        if not GitHubCopilotCredentials.from_provider(provider).configured:
            return None
        login = provider.config.get("github_login")
        if isinstance(login, str) and login.strip():
            return f"GitHub account {login.strip()}"
        return "GitHub token configured"
    return None


def provider_public_view(provider: LlmProviderRecord) -> dict[str, Any]:
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
        "credentials_configured": credentials_configured(provider),
        "credential_summary": credential_summary(provider),
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
            provider = next(
                (item for item in store.list_llm_providers(user_id) if credentials_configured(item)),
                None,
            )
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
    if not credentials_configured(provider):
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
    label = provider_label(provider.provider_type)
    if str(response.get("output_text") or "").strip():
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


def _validate_ai_platform(
    settings: Settings,
    config: dict[str, str],
    secrets: dict[str, str],
) -> None:
    missing_endpoints = [
        name
        for name, value in (
            ("LOGAN_AI_PLATFORM_CHAT_HOST", settings.ai_platform_chat_host),
            ("LOGAN_AI_PLATFORM_IB2B_HOST", settings.ai_platform_ib2b_host),
            ("LOGAN_AI_PLATFORM_IB2B_URI", settings.ai_platform_ib2b_uri),
        )
        if not (value or "").strip()
    ]
    if missing_endpoints:
        raise LlmProviderError(
            "AI Platform endpoints are not configured for this deployment; set "
            + ", ".join(missing_endpoints)
        )
    provided = [
        bool(config.get("username", "").strip()),
        bool(secrets.get("password", "").strip()),
        bool(config.get("usercase", "").strip()),
    ]
    if any(provided) and not all(provided):
        raise LlmProviderError(
            "AI Platform credentials require username, password, and usercase together"
        )
