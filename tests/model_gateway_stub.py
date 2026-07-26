from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any


class StubModelGateway:
    provider = "ai_platform"

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def responses(
        self,
        **kwargs: Any,
    ) -> dict[str, Any] | AsyncIterator[dict[str, Any]]:
        self.calls.append(kwargs)
        if kwargs.get("stream"):
            return self._stream()
        if kwargs.get("metadata", {}).get("purpose") == "causal_summary":
            return {"output_json": {}}
        return {
            "output_json": {
                "golden_signal": "error",
                "fault_categories": ["application"],
                "entities": {},
                "severity_score": 0.8,
                "confidence": 0.9,
                "rationale": "The representative log lines contain an error signal.",
            }
        }

    async def _stream(self) -> AsyncIterator[dict[str, Any]]:
        yield {"type": "message.delta", "delta": "Test response."}
        yield {"type": "message.completed", "output_text": "Test response."}
