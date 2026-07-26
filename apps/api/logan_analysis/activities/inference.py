from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from logan_analysis.models import (
    LogTemplate,
    RepresentativeSample,
    TemplateAnnotation,
    TemplateAnnotationResult,
)
from logan_analysis.ports import ModelGateway
from pydantic import ValidationError

PROMPT_VERSION = "annotation_v1"
PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "annotation_prompt.md"
TRUNCATION_SUFFIX = "...(truncated)"


def _load_annotation_prompt() -> str:
    try:
        return PROMPT_PATH.read_text(encoding="utf-8")
    except OSError:
        return (
            "Classify the log template and representative lines. Return only valid JSON "
            "with golden_signal, fault_categories, entities, severity_score, confidence, "
            "and rationale."
        )


def _truncate_text(value: str, *, max_chars: int | None) -> str:
    if max_chars is None or max_chars <= 0 or len(value) <= max_chars:
        return value
    if max_chars <= len(TRUNCATION_SUFFIX):
        return value[:max_chars]
    return f"{value[: max_chars - len(TRUNCATION_SUFFIX)]}{TRUNCATION_SUFFIX}"


def _prioritized_templates(
    templates: list[LogTemplate],
    *,
    max_templates: int | None,
) -> list[LogTemplate]:
    if max_templates is None or max_templates <= 0 or len(templates) <= max_templates:
        return templates
    return sorted(
        templates,
        key=lambda template: (-template.occurrence_count, template.template_id),
    )[:max_templates]


def build_annotation_payload(
    *,
    case_context: dict[str, Any],
    template: LogTemplate,
    samples: list[RepresentativeSample],
    max_sample_message_chars: int | None = None,
    max_samples_per_template: int | None = None,
) -> dict[str, Any]:
    selected_samples = samples
    if max_samples_per_template is not None and max_samples_per_template > 0:
        selected_samples = samples[:max_samples_per_template]
    return {
        "case_context": case_context,
        "template_context": {
            "template_id": template.template_id,
            "template_text": _truncate_text(
                template.template_text,
                max_chars=max_sample_message_chars,
            ),
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
                "message": _truncate_text(sample.message, max_chars=max_sample_message_chars),
                "evidence_ref": sample.evidence_ref.model_dump(mode="json"),
            }
            for sample in selected_samples
        ],
    }


async def annotate_templates(
    *,
    analysis_run_id: str,
    templates: list[LogTemplate],
    samples: list[RepresentativeSample],
    case_context: dict[str, Any],
    gateway: ModelGateway,
    max_templates: int | None = None,
    max_sample_message_chars: int | None = None,
    max_samples_per_template: int | None = None,
) -> list[TemplateAnnotation]:
    samples_by_template: dict[str, list[RepresentativeSample]] = {}
    for sample in samples:
        samples_by_template.setdefault(sample.template_id, []).append(sample)

    annotations: list[TemplateAnnotation] = []
    model = str(case_context.get("model") or "gpt-5.4")
    reasoning_effort = str(case_context.get("reasoning_effort") or "high")
    for template in _prioritized_templates(templates, max_templates=max_templates):
        payload = build_annotation_payload(
            case_context=case_context,
            template=template,
            samples=samples_by_template.get(template.template_id, []),
            max_sample_message_chars=max_sample_message_chars,
            max_samples_per_template=max_samples_per_template,
        )
        response = await gateway.responses(
            user_id=case_context.get("user_id", "local"),
            model=model,
            instructions=_load_annotation_prompt(),
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
                "prompt_version": PROMPT_VERSION,
            },
            reasoning_effort=reasoning_effort,
            response_format={"type": "json_object"},
        )
        if not isinstance(response, dict):
            raise ValueError("template annotation gateway returned a stream")
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
                annotation_id=str(
                    uuid.uuid5(uuid.NAMESPACE_URL, f"{template.template_id}:annotation_v1")
                ),
                template_id=template.template_id,
                analysis_run_id=analysis_run_id,
                model_provider=getattr(gateway, "provider", "ai_platform"),
                model_name=model,
                prompt_version=PROMPT_VERSION,
                raw_model_response=raw if isinstance(raw, dict) else {"raw": raw},
                **parsed.model_dump(),
            )
        )
    return annotations
