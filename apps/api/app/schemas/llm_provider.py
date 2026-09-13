from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class LlmProviderCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    provider_type: str = Field(description="ai_platform or github_copilot")
    models: list[str] | None = Field(
        default=None,
        description="Models offered by this provider; defaults to the catalog for its type.",
    )
    default_model: str | None = None
    default_reasoning_effort: str | None = None
    config: dict[str, str | None] = Field(
        default_factory=dict,
        description="Non-secret settings. AI Platform: username, usercase.",
    )
    secrets: dict[str, str | None] = Field(
        default_factory=dict,
        description="Credentials. AI Platform: password. GitHub Copilot: github_token, "
        "normally written by the device flow rather than sent here.",
    )


class LlmProviderUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    models: list[str] | None = None
    default_model: str | None = None
    default_reasoning_effort: str | None = None
    config: dict[str, str | None] | None = Field(
        default=None,
        description="Fields to change; null or empty removes a field.",
    )
    secrets: dict[str, str | None] | None = Field(
        default=None,
        description="Secrets to change; null or empty removes a secret.",
    )


class LlmProviderResponse(BaseModel):
    provider_id: str
    name: str
    provider_type: str
    provider_label: str
    models: list[str]
    default_model: str
    default_reasoning_effort: str
    credentials_configured: bool
    credential_summary: str | None = None
    secret_fields: list[str] = Field(default_factory=list)
    config: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class LlmProviderListResponse(BaseModel):
    items: list[LlmProviderResponse]
    total: int


class ProviderTypeCatalog(BaseModel):
    provider_type: str
    label: str
    models: list[str]
    default_model: str
    config_fields: list[str]
    secret_fields: list[str]
    supports_device_flow: bool
    available: bool = Field(
        description="Whether this deployment can host the provider type at all.",
    )
    unavailable_reason: str | None = None


class ReasoningEffortOption(BaseModel):
    value: str
    label: str


class LlmProviderCatalogResponse(BaseModel):
    provider_types: list[ProviderTypeCatalog]
    reasoning_efforts: list[ReasoningEffortOption]
    default_reasoning_effort: str


class LlmProviderTestResponse(BaseModel):
    ok: bool
    message: str
    model: str


class GitHubDeviceStartResponse(BaseModel):
    auth_id: str
    user_code: str
    verification_uri: str
    verification_uri_complete: str
    expires_in: int
    interval: int


class GitHubDeviceCheckRequest(BaseModel):
    auth_id: str = Field(min_length=1)


class GitHubDeviceCheckResponse(BaseModel):
    status: str
    github_login: str | None = None
    message: str | None = None
    interval: int | None = None
    provider: LlmProviderResponse | None = None
