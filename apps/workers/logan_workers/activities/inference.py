from __future__ import annotations

from collections.abc import AsyncIterator
import uuid
from typing import Any

from pydantic import ValidationError

from logan_workers.models import (
    LogTemplate,
    RepresentativeSample,
    TemplateAnnotation,
    TemplateAnnotationResult,
)


class MockCopilotAnnotationGateway:
    provider = "github_copilot"
    model = "gpt-5.4"

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def responses(self, **kwargs: Any) -> dict[str, Any] | AsyncIterator[dict[str, Any]]:
        self.calls.append(kwargs)
        if kwargs.get("stream"):
            return self._stream_response()
        text = " ".join(
            part.get("text", "")
            for item in kwargs.get("input", [])
            for part in item.get("content", [])
            if isinstance(part, dict)
        ).lower()
        return {"output_json": self._classify(text)}

    async def _stream_response(self) -> AsyncIterator[dict[str, Any]]:
        message = "Mock analysis context response."
        yield {"type": "message.delta", "delta": message}
        yield {"type": "message.completed", "output_text": message}

    def _classify(self, text: str) -> dict[str, Any]:
        if "connection pool exhausted" in text or "pool usage high" in text:
            service = "auth-service" if "auth-service" in text else "payment-service"
            return {
                "golden_signal": "saturation",
                "fault_categories": ["resource", "database"],
                "entities": {"service": [service], "database": ["db"] if "db" in text else []},
                "severity_score": 0.88,
                "confidence": 0.92,
                "rationale": "Connection pool exhaustion indicates resource saturation.",
            }
        if "timeout calling auth-service" in text:
            return {
                "golden_signal": "availability",
                "fault_categories": ["dependency", "timeout"],
                "entities": {
                    "source_service": ["payment-service"],
                    "target_service": ["auth-service"],
                    "duration_ms": ["30000"],
                },
                "severity_score": 0.86,
                "confidence": 0.91,
                "rationale": "Payment timed out while calling auth-service.",
            }
        if "failed status" in text or "status=<*>" in text or " status=500" in text:
            return {
                "golden_signal": "error",
                "fault_categories": ["application"],
                "entities": {
                    "service": ["gateway"],
                    "status_code": ["500"],
                    "url_path": ["/checkout"],
                },
                "severity_score": 0.84,
                "confidence": 0.89,
                "rationale": "Gateway checkout requests failed with 500 errors.",
            }
        if "failed to acquire db connection" in text:
            return {
                "golden_signal": "availability",
                "fault_categories": ["database", "timeout", "resource"],
                "entities": {"service": ["auth-service"], "database": ["db"], "duration_ms": ["5000"]},
                "severity_score": 0.82,
                "confidence": 0.88,
                "rationale": "Auth service could not acquire a database connection.",
            }
        if "usage high" in text or "retry" in text:
            return {
                "golden_signal": "traffic",
                "fault_categories": ["resource"],
                "entities": {},
                "severity_score": 0.45,
                "confidence": 0.7,
                "rationale": "The line indicates elevated load or retry behavior.",
            }
        return {
            "golden_signal": "information",
            "fault_categories": [],
            "entities": {},
            "severity_score": 0.1,
            "confidence": 0.75,
            "rationale": "Routine informational log.",
        }


def build_annotation_payload(
    *,
    case_context: dict[str, Any],
    template: LogTemplate,
    samples: list[RepresentativeSample],
) -> dict[str, Any]:
    return {
        "case_context": case_context,
        "template_context": {
            "template_id": template.template_id,
            "template_text": template.template_text,
            "occurrence_count": template.occurrence_count,
            "first_seen": template.first_seen.isoformat() if template.first_seen else None,
            "last_seen": template.last_seen.isoformat() if template.last_seen else None,
            "services": template.services,
            "files": template.files,
        },
        "representative_lines": [
            {
                "sample_reason": sample.sample_reason,
                "timestamp": sample.timestamp.isoformat() if sample.timestamp else None,
                "level": sample.level,
                "service": sample.service,
                "message": sample.message,
                "evidence_ref": sample.evidence_ref.model_dump(mode="json"),
            }
            for sample in samples
        ],
    }


async def annotate_templates(
    *,
    analysis_run_id: str,
    templates: list[LogTemplate],
    samples: list[RepresentativeSample],
    case_context: dict[str, Any],
    gateway: MockCopilotAnnotationGateway | None = None,
) -> tuple[list[TemplateAnnotation], list[dict[str, Any]]]:
    gateway = gateway or MockCopilotAnnotationGateway()
    samples_by_template: dict[str, list[RepresentativeSample]] = {}
    for sample in samples:
        samples_by_template.setdefault(sample.template_id, []).append(sample)

    annotations: list[TemplateAnnotation] = []
    model_inputs: list[dict[str, Any]] = []
    for template in templates:
        payload = build_annotation_payload(
            case_context=case_context,
            template=template,
            samples=samples_by_template.get(template.template_id, []),
        )
        model_inputs.append(payload)
        response = await gateway.responses(
            user_id=case_context.get("user_id", "local"),
            model="gpt-5.4",
            instructions="template_annotation",
            input=[
                {
                    "role": "user",
                    "content": [{"type": "input_text", "text": str(payload)}],
                }
            ],
            stream=False,
            metadata={
                "case_id": case_context.get("case_id"),
                "analysis_run_id": analysis_run_id,
                "purpose": "template_annotation",
            },
            reasoning_effort="high",
            response_format={"type": "json_object"},
        )
        raw = response.get("output_json", response)
        try:
            parsed = TemplateAnnotationResult.model_validate(raw)
        except ValidationError:
            parsed = TemplateAnnotationResult(
                golden_signal="unknown",
                fault_categories=["unknown"],
                entities={},
                severity_score=0.0,
                confidence=0.0,
                rationale="Model output could not be validated.",
            )
        annotations.append(
            TemplateAnnotation(
                annotation_id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"{template.template_id}:annotation_v1")),
                template_id=template.template_id,
                analysis_run_id=analysis_run_id,
                model_provider="github_copilot",
                model_name="gpt-5.4",
                prompt_version="annotation_v1",
                raw_model_response=raw if isinstance(raw, dict) else {"raw": raw},
                **parsed.model_dump(),
            )
        )
    return annotations, model_inputs
