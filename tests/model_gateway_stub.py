from __future__ import annotations

import json
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
            packet = json.loads(kwargs["input"][0]["content"][0]["text"])
            if not packet["evidence_lines"]:
                return {"output_json": {}}
            first_log_id = packet["evidence_lines"][0]["log_id"]
            return {
                "output_json": {
                    "internal_rca_markdown": (
                        "# Candidate RCA\n\nEvidence suggests a candidate issue that needs validation."
                    ),
                    "customer_update_markdown": "Engineering is validating a candidate cause.",
                    "evidence_claims": [
                        {
                            "claim": "Evidence suggests a candidate source signal needs validation.",
                            "reason": (
                                "The claim was selected because the cited evidence appears in the "
                                "bounded causal summary packet used for this run."
                            ),
                            "evidence_refs": [first_log_id],
                            "confidence": 0.72,
                            "needs_validation": True,
                        }
                    ],
                    "next_validation_steps": [
                        {
                            "title": "Validate candidate source",
                            "description": "Compare the cited evidence with metrics and traces.",
                            "priority": "high",
                            "owner_role": "SRE",
                            "evidence_refs": [first_log_id],
                        }
                    ],
                    "uncertainties": ["Synthetic gateway output still needs validation."],
                    "confidence": 0.72,
                }
            }
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
