from __future__ import annotations

import json
import os

import pytest

from app.config import Settings
from app.services.copilot_model_gateway import CopilotModelGateway
from logan_workers.models import TemplateAnnotationResult


def _has_token() -> bool:
    return bool(os.getenv("LOGAN_GITHUB_COPILOT_TOKEN") or os.getenv("LOGAN_GITHUB_SOURCE_TOKEN"))


@pytest.mark.staging
@pytest.mark.asyncio
async def test_copilot_responses_annotation_smoke() -> None:
    if os.getenv("LOGAN_RUN_COPILOT_STAGING_SMOKE") != "true":
        pytest.skip("set LOGAN_RUN_COPILOT_STAGING_SMOKE=true to run real Copilot smoke")
    if not _has_token():
        pytest.skip("set LOGAN_GITHUB_COPILOT_TOKEN or LOGAN_GITHUB_SOURCE_TOKEN")

    app_settings = Settings(
        llm_provider="github_copilot",
        github_copilot_token=os.getenv("LOGAN_GITHUB_COPILOT_TOKEN") or None,
        github_source_token=os.getenv("LOGAN_GITHUB_SOURCE_TOKEN") or None,
        copilot_model=os.getenv("LOGAN_COPILOT_MODEL", "gpt-5.4"),
        copilot_reasoning_effort=os.getenv("LOGAN_COPILOT_REASONING_EFFORT", "high"),
        copilot_base_url=os.getenv("LOGAN_COPILOT_BASE_URL") or None,
        copilot_timeout_seconds=float(os.getenv("LOGAN_COPILOT_TIMEOUT_SECONDS", "30")),
    )
    gateway = CopilotModelGateway(app_settings=app_settings)

    response = await gateway.responses(
        user_id="copilot-staging-smoke",
        model=app_settings.copilot_model,
        instructions=(
            "Return only a JSON object with keys golden_signal, fault_categories, "
            "entities, severity_score, confidence, and rationale."
        ),
        input=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": (
                            "Classify this redacted log template for LogAn: "
                            "gateway failed status=500 while calling /checkout."
                        ),
                    }
                ],
            }
        ],
        stream=False,
        metadata={"purpose": "copilot_staging_smoke"},
        reasoning_effort=app_settings.copilot_reasoning_effort,
        response_format={"type": "json_object"},
    )

    assert isinstance(response, dict)
    assert response["provider"] == "github_copilot"
    assert response["token_source"] in {
        "env_github_copilot_token",
        "env_github_source_token",
    }
    parsed = response.get("output_json")
    if not isinstance(parsed, dict):
        pytest.fail("Copilot /responses did not return a parseable JSON object")
    annotation = TemplateAnnotationResult.model_validate(parsed)
    assert annotation.golden_signal
    assert 0 <= annotation.confidence <= 1

    serialized = json.dumps(response, default=str)
    for token in (
        os.getenv("LOGAN_GITHUB_COPILOT_TOKEN"),
        os.getenv("LOGAN_GITHUB_SOURCE_TOKEN"),
    ):
        if token:
            assert token not in serialized
