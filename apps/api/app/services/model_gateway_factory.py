from __future__ import annotations

import asyncio
import logging

from logan_analysis.ports import ModelGateway

from app.config import Settings
from app.llm_catalog import AI_PLATFORM_PROVIDER, GITHUB_COPILOT_PROVIDER
from app.records import LlmProviderRecord
from app.services.aiplatform_model_gateway import AIPlatformModelGateway, AIPlatformProviderConfig
from app.services.github_copilot_model_gateway import (
    GitHubCopilotModelGateway,
    GitHubCopilotProviderConfig,
)

logger = logging.getLogger("logan.analysis")


def create_model_gateway(provider: LlmProviderRecord, app_settings: Settings) -> ModelGateway:
    """Build the gateway for one user-managed provider record."""
    if provider.provider_type == AI_PLATFORM_PROVIDER:
        return AIPlatformModelGateway(
            config=AIPlatformProviderConfig.from_provider(provider, app_settings),
            app_settings=app_settings,
        )
    if provider.provider_type == GITHUB_COPILOT_PROVIDER:
        return GitHubCopilotModelGateway(
            config=GitHubCopilotProviderConfig.from_provider(provider),
            app_settings=app_settings,
        )
    raise ValueError(f"unsupported provider type: {provider.provider_type}")


class ModelGatewayRegistry:
    """Caches one gateway per provider so exchanged tokens are reused across requests.

    A gateway is rebuilt when the provider record changes. Tests may pass an ``override``
    gateway that is returned for every provider.
    """

    def __init__(self, app_settings: Settings, *, override: ModelGateway | None = None) -> None:
        self.settings = app_settings
        self.override = override
        self._gateways: dict[str, tuple[str, ModelGateway]] = {}

    def gateway_for(self, provider: LlmProviderRecord) -> ModelGateway:
        if self.override is not None:
            return self.override
        version = provider.updated_at.isoformat()
        cached = self._gateways.get(provider.id)
        if cached is not None and cached[0] == version:
            return cached[1]
        gateway = create_model_gateway(provider, self.settings)
        self._gateways[provider.id] = (version, gateway)
        if cached is not None:
            _schedule_close(cached[1])
        return gateway

    def discard(self, provider_id: str) -> None:
        cached = self._gateways.pop(provider_id, None)
        if cached is not None:
            _schedule_close(cached[1])

    async def aclose(self) -> None:
        gateways = [gateway for _, gateway in self._gateways.values()]
        self._gateways.clear()
        for gateway in gateways:
            close = getattr(gateway, "aclose", None)
            if callable(close):
                try:
                    await close()
                except Exception:
                    logger.debug("model gateway close failed", exc_info=True)
        close_override = getattr(self.override, "aclose", None)
        if callable(close_override):
            await close_override()


def _schedule_close(gateway: ModelGateway) -> None:
    close = getattr(gateway, "aclose", None)
    if not callable(close):
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    loop.create_task(close())
