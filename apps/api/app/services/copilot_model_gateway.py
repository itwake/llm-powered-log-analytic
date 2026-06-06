from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from app.config import settings


class CopilotModelGateway:
    provider = "github_copilot"

    async def responses(
        self,
        *,
        user_id: str,
        model: str,
        instructions: str | None,
        input: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        stream: bool = False,
        metadata: dict[str, Any] | None = None,
        reasoning_effort: str = "high",
        temperature: float | None = None,
        response_format: dict[str, Any] | None = None,
    ) -> dict[str, Any] | AsyncIterator[dict[str, Any]]:
        if settings.llm_provider != "github_copilot":
            raise RuntimeError("LogAn only configures github_copilot as the default provider")
        payload = {
            "model": model,
            "instructions": instructions,
            "input": input,
            "tools": tools or [],
            "stream": stream,
            "metadata": metadata or {},
            "reasoning": {"effort": reasoning_effort},
        }
        if temperature is not None:
            payload["temperature"] = temperature
        if response_format is not None:
            payload["response_format"] = response_format
        return {
            "provider": "github_copilot",
            "model": model,
            "payload": payload,
            "output_text": "Mock local Copilot gateway response; no external token was used.",
        }
