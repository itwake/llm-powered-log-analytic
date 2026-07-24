from __future__ import annotations

from app.config import Settings
from app.services.aiplatform_model_gateway import AIPlatformModelGateway
from logan_workers.activities.inference import MockAIPlatformAnnotationGateway
from logan_workers.ports import ModelGateway


def create_model_gateway(app_settings: Settings) -> ModelGateway:
    """Build the configured gateway for both API and worker processes."""

    provider = (app_settings.llm_provider or "ai_platform").lower()
    if provider in {"mock", "local_mock"}:
        return MockAIPlatformAnnotationGateway()
    if provider in {"ai_platform", "ai-platform", "aiplatform", "ai platform"}:
        return AIPlatformModelGateway(app_settings=app_settings)
    raise ValueError("LOGAN_LLM_PROVIDER must be ai_platform or mock")
