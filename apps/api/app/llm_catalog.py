"""Single source of truth for the supported AI providers, models, and thinking levels.

Providers are configured per user in the web application. This module only describes what a
provider type can offer; credentials and endpoints live on the stored provider record.
"""

from __future__ import annotations

import re

AI_PLATFORM_PROVIDER = "ai_platform"
GITHUB_COPILOT_PROVIDER = "github_copilot"
NO_PROVIDER = "none"

PROVIDER_TYPES: tuple[str, ...] = (AI_PLATFORM_PROVIDER, GITHUB_COPILOT_PROVIDER)
PROVIDER_LABELS: dict[str, str] = {
    AI_PLATFORM_PROVIDER: "AI Platform",
    GITHUB_COPILOT_PROVIDER: "GitHub Copilot",
}

# Selectable models per provider type. Users may extend the list on a provider because gateway
# deployments differ; these are the defaults offered when a provider is created.
AI_PLATFORM_MODELS: tuple[str, ...] = (
    "gpt-5.4",
    "gpt-5.6-luna",
    "gpt-5.6-sol",
    "gpt-5.6-terra",
)
# The Copilot model picker, as ids the Copilot API accepts. Copilot names Anthropic models
# ``claude-<family>-<version>`` (``claude-sonnet-4``, ``claude-haiku-4.5`` are confirmed), Gemini
# ``gemini-<version>-<variant>``, and OpenAI ``gpt-<version>[-<variant>]``; the newer entries
# follow the same pattern. A provider's own list can drop or correct any of them.
GITHUB_COPILOT_MODELS: tuple[str, ...] = (
    "claude-sonnet-4",  # Sonnet 4
    "claude-haiku-4.5",  # Haiku 4.5
    "claude-fable-5",  # Fable 5
    "claude-fable-5.1",  # Fable 5.1
    "claude-opus-4.7",  # Opus 4.7
    "claude-opus-4.8",  # Opus 4.8
    "claude-opus-5",  # Opus 5
    "claude-sonnet-5",  # Sonnet 5
    "gemini-3.7-flash",  # Gemini 3.7 Flash
    "gemini-3.8-flash",  # Gemini 3.8 Flash
    "gpt-5.4",  # GPT-5.4
    "gpt-5.4-mini",  # GPT-5.4 mini
    "gpt-5-mini",  # GPT-5 mini
    "gpt-5.6-luna",  # GPT-5.6 Luna
    "gpt-5.6-sol",  # GPT-5.6 Sol
    "gpt-5.6-terra",  # GPT-5.6 Terra
    "gpt-6-astra",  # GPT-6 Astra
    "mai-code-1.1-flash",  # MAI-Code-1.1-Flash
)
PROVIDER_MODELS: dict[str, tuple[str, ...]] = {
    AI_PLATFORM_PROVIDER: AI_PLATFORM_MODELS,
    GITHUB_COPILOT_PROVIDER: GITHUB_COPILOT_MODELS,
}
PROVIDER_DEFAULT_MODEL: dict[str, str] = {
    AI_PLATFORM_PROVIDER: "gpt-5.4",
    GITHUB_COPILOT_PROVIDER: "gpt-5.6-terra",
}

# Request-level thinking control, sent as ``reasoning_effort`` to both provider types.
REASONING_EFFORTS: tuple[str, ...] = ("low", "medium", "high", "xhigh", "max")
DEFAULT_REASONING_EFFORT = "high"
REASONING_EFFORT_LABELS: dict[str, str] = {
    "low": "Low",
    "medium": "Medium",
    "high": "High",
    "xhigh": "Extra high",
    "max": "Max",
}

MAX_MODELS_PER_PROVIDER = 32
MAX_PROVIDER_NAME_LENGTH = 80
_MODEL_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,99}$")
_PROVIDER_ALIASES: dict[str, str] = {
    "ai_platform": AI_PLATFORM_PROVIDER,
    "ai-platform": AI_PLATFORM_PROVIDER,
    "ai platform": AI_PLATFORM_PROVIDER,
    "aiplatform": AI_PLATFORM_PROVIDER,
    "github_copilot": GITHUB_COPILOT_PROVIDER,
    "github-copilot": GITHUB_COPILOT_PROVIDER,
    "github copilot": GITHUB_COPILOT_PROVIDER,
    "copilot": GITHUB_COPILOT_PROVIDER,
}


def normalize_provider_type(value: object) -> str | None:
    """Return the canonical provider type for an alias, or ``None`` when unsupported."""
    text = str(value or "").strip().lower()
    return _PROVIDER_ALIASES.get(text)


def provider_label(provider_type: str) -> str:
    return PROVIDER_LABELS.get(provider_type, provider_type)


def models_for_provider(provider_type: str | None) -> tuple[str, ...]:
    return PROVIDER_MODELS.get(normalize_provider_type(provider_type) or "", ())


def default_model_for_provider(provider_type: str | None) -> str:
    canonical = normalize_provider_type(provider_type) or ""
    return PROVIDER_DEFAULT_MODEL.get(canonical, "")


def normalize_reasoning_effort(value: object, default: str | None = None) -> str | None:
    """Return a supported thinking level, ``default`` for blank input, or ``None`` if invalid."""
    text = str(value or "").strip().lower()
    if not text:
        return default
    return text if text in REASONING_EFFORTS else None


def is_valid_model_id(value: object) -> bool:
    return isinstance(value, str) and bool(_MODEL_ID_RE.match(value.strip()))


def normalize_model_list(values: object) -> list[str]:
    """Trim, validate, and de-duplicate a user-supplied model list while preserving order."""
    if not isinstance(values, (list, tuple)):
        raise ValueError("models must be a list of model identifiers")
    normalized: list[str] = []
    for value in values:
        if not isinstance(value, str):
            raise ValueError("models must contain only strings")
        model = value.strip()
        if not model:
            continue
        if not _MODEL_ID_RE.match(model):
            raise ValueError(f"model identifier is not valid: {model[:40]}")
        if model not in normalized:
            normalized.append(model)
    if len(normalized) > MAX_MODELS_PER_PROVIDER:
        raise ValueError(f"a provider supports at most {MAX_MODELS_PER_PROVIDER} models")
    return normalized


__all__ = [
    "AI_PLATFORM_MODELS",
    "AI_PLATFORM_PROVIDER",
    "DEFAULT_REASONING_EFFORT",
    "GITHUB_COPILOT_MODELS",
    "GITHUB_COPILOT_PROVIDER",
    "MAX_MODELS_PER_PROVIDER",
    "MAX_PROVIDER_NAME_LENGTH",
    "NO_PROVIDER",
    "PROVIDER_DEFAULT_MODEL",
    "PROVIDER_LABELS",
    "PROVIDER_MODELS",
    "PROVIDER_TYPES",
    "REASONING_EFFORTS",
    "REASONING_EFFORT_LABELS",
    "default_model_for_provider",
    "is_valid_model_id",
    "models_for_provider",
    "normalize_model_list",
    "normalize_provider_type",
    "normalize_reasoning_effort",
    "provider_label",
]
