from __future__ import annotations

from app.config import Settings
from app.services.aiplatform_model_gateway import AIPlatformModelGateway
from logan_analysis.ports import ModelGateway


def create_model_gateway(app_settings: Settings) -> ModelGateway | None:
    """Build the configured gateway for the API-owned analysis pipeline."""

    provider = app_settings.normalized_llm_provider
    if provider == "none":
        return None
    if provider == "ai_platform":
        return AIPlatformModelGateway(app_settings=app_settings)
    raise ValueError("LOGAN_LLM_PROVIDER must be ai_platform or none")
