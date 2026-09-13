from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.dependencies import current_user, get_gateway_registry, get_store
from app.llm_catalog import (
    DEFAULT_REASONING_EFFORT,
    GITHUB_COPILOT_PROVIDER,
    PROVIDER_TYPES,
    REASONING_EFFORT_LABELS,
    REASONING_EFFORTS,
    default_model_for_provider,
    models_for_provider,
    provider_label,
)
from app.schemas.llm_provider import (
    GitHubDeviceCheckRequest,
    GitHubDeviceCheckResponse,
    GitHubDeviceStartResponse,
    LlmProviderCatalogResponse,
    LlmProviderCreateRequest,
    LlmProviderListResponse,
    LlmProviderResponse,
    LlmProviderTestResponse,
    LlmProviderUpdateRequest,
    ProviderTypeCatalog,
    ReasoningEffortOption,
)
from app.services.github_copilot_auth import GitHubDeviceFlow
from app.services.llm_providers import (
    PROVIDER_CONFIG_FIELDS,
    PROVIDER_SECRET_FIELDS,
    LlmProviderError,
    normalize_provider_definition,
    provider_public_view,
    smoke_test_provider,
)
from app.services.model_gateway import ModelGatewayError
from app.services.model_gateway_factory import ModelGatewayRegistry
from app.store import LlmProviderRecord, Store, UserRecord, sanitize_error_message

router = APIRouter(prefix="/api/llm-providers", tags=["llm-providers"])


def _response(provider: LlmProviderRecord, store: Store) -> LlmProviderResponse:
    return LlmProviderResponse(**provider_public_view(provider, store.settings))


def _owned_provider(store: Store, user: UserRecord, provider_id: str) -> LlmProviderRecord:
    provider = store.get_llm_provider(provider_id)
    if provider is None or provider.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="AI provider not found")
    return provider


def _device_flow(request: Request, store: Store) -> GitHubDeviceFlow:
    flow = getattr(request.app.state, "github_device_flow", None)
    if not isinstance(flow, GitHubDeviceFlow):
        flow = GitHubDeviceFlow(app_settings=store.settings)
        request.app.state.github_device_flow = flow
    return flow


@router.get("/catalog", response_model=LlmProviderCatalogResponse)
def provider_catalog(
    _: UserRecord = Depends(current_user),
    store: Store = Depends(get_store),
) -> LlmProviderCatalogResponse:
    return LlmProviderCatalogResponse(
        provider_types=[
            ProviderTypeCatalog(
                provider_type=provider_type,
                label=provider_label(provider_type),
                models=list(models_for_provider(provider_type)),
                default_model=default_model_for_provider(provider_type),
                config_fields=list(PROVIDER_CONFIG_FIELDS[provider_type]),
                secret_fields=list(PROVIDER_SECRET_FIELDS[provider_type]),
                supports_device_flow=provider_type == GITHUB_COPILOT_PROVIDER,
            )
            for provider_type in PROVIDER_TYPES
        ],
        reasoning_efforts=[
            ReasoningEffortOption(value=value, label=REASONING_EFFORT_LABELS[value])
            for value in REASONING_EFFORTS
        ],
        default_reasoning_effort=DEFAULT_REASONING_EFFORT,
        ai_platform_defaults=store.settings.ai_platform_form_defaults(),
    )


@router.get("", response_model=LlmProviderListResponse)
def list_providers(
    user: UserRecord = Depends(current_user),
    store: Store = Depends(get_store),
) -> LlmProviderListResponse:
    providers = store.list_llm_providers(user.id)
    return LlmProviderListResponse(
        items=[_response(provider, store) for provider in providers],
        total=len(providers),
    )


@router.post("", response_model=LlmProviderResponse)
def create_provider(
    payload: LlmProviderCreateRequest,
    user: UserRecord = Depends(current_user),
    store: Store = Depends(get_store),
) -> LlmProviderResponse:
    try:
        definition = normalize_provider_definition(
            settings=store.settings,
            provider_type=payload.provider_type,
            name=payload.name,
            models=payload.models,
            default_model=payload.default_model,
            default_reasoning_effort=payload.default_reasoning_effort,
            config=payload.config,
            secrets=payload.secrets,
        )
        provider = store.create_llm_provider(
            user_id=user.id,
            name=definition.name,
            provider_type=definition.provider_type,
            config=definition.config,
            secrets=definition.secrets,
            models=definition.models,
            default_model=definition.default_model,
            default_reasoning_effort=definition.default_reasoning_effort,
            is_default=payload.is_default,
        )
    except LlmProviderError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _response(provider, store)


@router.get("/{provider_id}", response_model=LlmProviderResponse)
def get_provider(
    provider_id: str,
    user: UserRecord = Depends(current_user),
    store: Store = Depends(get_store),
) -> LlmProviderResponse:
    return _response(_owned_provider(store, user, provider_id), store)


@router.patch("/{provider_id}", response_model=LlmProviderResponse)
def update_provider(
    provider_id: str,
    payload: LlmProviderUpdateRequest,
    user: UserRecord = Depends(current_user),
    store: Store = Depends(get_store),
    registry: ModelGatewayRegistry = Depends(get_gateway_registry),
) -> LlmProviderResponse:
    existing = _owned_provider(store, user, provider_id)
    try:
        definition = normalize_provider_definition(
            settings=store.settings,
            provider_type=None,
            name=payload.name,
            models=payload.models,
            default_model=payload.default_model,
            default_reasoning_effort=payload.default_reasoning_effort,
            config=payload.config,
            secrets=payload.secrets,
            existing=existing,
        )
        provider = store.update_llm_provider(
            provider_id=provider_id,
            user_id=user.id,
            name=definition.name,
            config=definition.config,
            secrets=definition.secrets,
            models=definition.models,
            default_model=definition.default_model,
            default_reasoning_effort=definition.default_reasoning_effort,
            is_default=payload.is_default,
        )
    except LlmProviderError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="AI provider not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    registry.discard(provider_id)
    return _response(provider, store)


@router.delete("/{provider_id}")
def delete_provider(
    provider_id: str,
    user: UserRecord = Depends(current_user),
    store: Store = Depends(get_store),
    registry: ModelGatewayRegistry = Depends(get_gateway_registry),
) -> dict[str, bool]:
    _owned_provider(store, user, provider_id)
    if not store.delete_llm_provider(provider_id=provider_id, user_id=user.id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="AI provider not found")
    registry.discard(provider_id)
    return {"deleted": True}


@router.post("/{provider_id}/test", response_model=LlmProviderTestResponse)
async def test_provider(
    provider_id: str,
    user: UserRecord = Depends(current_user),
    store: Store = Depends(get_store),
    registry: ModelGatewayRegistry = Depends(get_gateway_registry),
) -> LlmProviderTestResponse:
    provider = _owned_provider(store, user, provider_id)
    try:
        gateway = registry.gateway_for(provider)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    ok, message = await smoke_test_provider(provider=provider, gateway=gateway, user_id=user.id)
    return LlmProviderTestResponse(ok=ok, message=message, model=provider.default_model)


@router.post("/{provider_id}/github-device/start", response_model=GitHubDeviceStartResponse)
async def start_github_device_flow(
    request: Request,
    provider_id: str,
    user: UserRecord = Depends(current_user),
    store: Store = Depends(get_store),
) -> GitHubDeviceStartResponse:
    provider = _owned_provider(store, user, provider_id)
    if provider.provider_type != GITHUB_COPILOT_PROVIDER:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="GitHub authorization applies only to GitHub Copilot providers",
        )
    flow = _device_flow(request, store)
    try:
        pending = await flow.start(user_id=user.id, provider_id=provider.id)
    except ModelGatewayError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=sanitize_error_message(exc, max_length=600),
        ) from exc
    return GitHubDeviceStartResponse(
        auth_id=pending.auth_id,
        user_code=pending.user_code,
        verification_uri=pending.verification_uri,
        verification_uri_complete=pending.verification_uri_complete,
        expires_in=pending.expires_in,
        interval=pending.interval,
    )


@router.post("/{provider_id}/github-device/check", response_model=GitHubDeviceCheckResponse)
async def check_github_device_flow(
    request: Request,
    provider_id: str,
    payload: GitHubDeviceCheckRequest,
    user: UserRecord = Depends(current_user),
    store: Store = Depends(get_store),
    registry: ModelGatewayRegistry = Depends(get_gateway_registry),
) -> GitHubDeviceCheckResponse:
    provider = _owned_provider(store, user, provider_id)
    flow = _device_flow(request, store)
    pending = flow.pending_for(user_id=user.id, auth_id=payload.auth_id)
    if pending is not None and pending.provider_id != provider.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="the authorization belongs to another provider",
        )
    result = await flow.check(user_id=user.id, auth_id=payload.auth_id)
    if result.status != "authorized" or not result.access_token:
        return GitHubDeviceCheckResponse(
            status=result.status,
            message=result.message,
            interval=result.interval,
        )
    config = {"github_login": result.github_login} if result.github_login else {"github_login": None}
    updated = store.update_llm_provider(
        provider_id=provider.id,
        user_id=user.id,
        config={**provider.config, **{k: v for k, v in config.items() if v}},
        secrets={**provider.secrets, "github_token": result.access_token},
    )
    if not result.github_login and "github_login" in updated.config:
        updated = store.update_llm_provider(
            provider_id=provider.id,
            user_id=user.id,
            config={k: v for k, v in updated.config.items() if k != "github_login"},
        )
    registry.discard(provider.id)
    return GitHubDeviceCheckResponse(
        status="authorized",
        github_login=result.github_login,
        provider=_response(updated, store),
    )
