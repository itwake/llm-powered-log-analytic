from __future__ import annotations

import httpx
from logan_analysis.ports import ModelGateway

from app.config import Settings
from app.llm_catalog import AI_PLATFORM_PROVIDER, GITHUB_COPILOT_PROVIDER
from app.records import LlmProviderRecord
from app.services.aiplatform_model_gateway import AIPlatformCredentials, AIPlatformModelGateway
from app.services.github_copilot_model_gateway import (
    GitHubCopilotCredentials,
    GitHubCopilotModelGateway,
)
from app.services.model_gateway import ModelTransportError


def create_model_gateway(
    provider: LlmProviderRecord,
    app_settings: Settings,
    *,
    http_client: httpx.AsyncClient | None = None,
) -> ModelGateway:
    """Build the gateway for one user-managed provider record."""
    if provider.provider_type == AI_PLATFORM_PROVIDER:
        return AIPlatformModelGateway(
            credentials=AIPlatformCredentials.from_provider(provider),
            app_settings=app_settings,
            http_client=http_client,
        )
    if provider.provider_type == GITHUB_COPILOT_PROVIDER:
        return GitHubCopilotModelGateway(
            credentials=GitHubCopilotCredentials.from_provider(provider),
            app_settings=app_settings,
            http_client=http_client,
        )
    raise ValueError(f"unsupported provider type: {provider.provider_type}")


class ModelGatewayRegistry:
    """Keeps one gateway per provider so exchanged provider tokens are reused.

    Gateways share one HTTP client per provider type, so discarding a gateway after its provider
    changes costs nothing and leaves no connection pool behind. Tests may pass an ``override``
    gateway that answers for every provider.
    """

    def __init__(self, app_settings: Settings, *, override: ModelGateway | None = None) -> None:
        self.settings = app_settings
        self.override = override
        self._gateways: dict[str, ModelGateway] = {}
        self._clients: dict[str, httpx.AsyncClient] = {}

    def gateway_for(self, provider: LlmProviderRecord) -> ModelGateway:
        if self.override is not None:
            return self.override
        gateway = self._gateways.get(provider.id)
        if gateway is None:
            gateway = create_model_gateway(
                provider,
                self.settings,
                http_client=self._client_for(provider.provider_type),
            )
            self._gateways[provider.id] = gateway
        return gateway

    def discard(self, provider_id: str) -> None:
        self._gateways.pop(provider_id, None)

    async def aclose(self) -> None:
        self._gateways.clear()
        clients = list(self._clients.values())
        self._clients.clear()
        for client in clients:
            await client.aclose()
        close_override = getattr(self.override, "aclose", None)
        if callable(close_override):
            await close_override()

    def _client_for(self, provider_type: str) -> httpx.AsyncClient:
        client = self._clients.get(provider_type)
        if client is None:
            if provider_type == AI_PLATFORM_PROVIDER:
                kwargs = self.settings.ai_platform_httpx_client_kwargs()
                bundle_setting = "LOGAN_AI_PLATFORM_CA_BUNDLE"
            else:
                kwargs = self.settings.github_copilot_httpx_client_kwargs()
                bundle_setting = "LOGAN_GITHUB_COPILOT_CA_BUNDLE"
            try:
                client = httpx.AsyncClient(**kwargs)
            except OSError as exc:
                # httpx loads the CA bundle here; report it as a provider transport problem
                # instead of a server error.
                raise ModelTransportError(
                    f"The TLS CA bundle for this provider cannot be loaded; check {bundle_setting}"
                    " (or SSL_CERT_FILE / REQUESTS_CA_BUNDLE) on the API host"
                ) from exc
            self._clients[provider_type] = client
        return client
