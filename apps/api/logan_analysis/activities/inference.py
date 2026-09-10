from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from pathlib import Path
from typing import Any

from logan_analysis.algorithms.redactors import redact_bounded_text
from logan_analysis.models import (
    LogTemplate,
    RepresentativeSample,
    TemplateAnnotation,
    TemplateAnnotationResult,
)
from logan_analysis.ports import ModelGateway
from pydantic import ValidationError

logger = logging.getLogger("logan.analysis")

PROMPT_VERSION = "annotation_v1"
PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "annotation_prompt.md"
DEFAULT_MAX_SAMPLE_MESSAGE_CHARS = 1200
MAX_CASE_CONTEXT_CHARS = 600
MAX_CONTEXT_LIST_ITEMS = 10
MAX_CONTEXT_LABEL_CHARS = 160
SAFE_CASE_CONTEXT_KEYS = (
    "case_id",
    "analysis_run_id",
    "title",
    "issue_description",
    "product",
    "service",
    "environment",
)


def _load_annotation_prompt() -> str:
    try:
        return PROMPT_PATH.read_text(encoding="utf-8")
    except OSError:
        return (
            "Classify the log template and representative lines. Return only valid JSON "
            "with golden_signal, fault_categories, entities, severity_score, confidence, "
            "and rationale."
        )


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


def _safe_case_context(case_context: dict[str, Any]) -> dict[str, str | None]:
    return {
        key: (
            None
            if case_context.get(key) is None
            else redact_bounded_text(
                case_context[key],
                max_length=MAX_CASE_CONTEXT_CHARS,
            )
        )
        for key in SAFE_CASE_CONTEXT_KEYS
    }


def _safe_labels(values: list[str]) -> list[str]:
    return [
        redact_bounded_text(value, max_length=MAX_CONTEXT_LABEL_CHARS)
        for value in values[:MAX_CONTEXT_LIST_ITEMS]
    ]


def _safe_source_names(values: list[str]) -> list[str]:
    return _safe_labels([re.split(r"[\\/]", value)[-1] for value in values])


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
    message_limit = (
        max_sample_message_chars
        if max_sample_message_chars is not None and max_sample_message_chars > 0
        else DEFAULT_MAX_SAMPLE_MESSAGE_CHARS
    )
    return {
        "case_context": _safe_case_context(case_context),
        "template_context": {
            "template_id": template.template_id,
            "template_text": redact_bounded_text(
                template.template_text,
                max_length=message_limit,
            ),
            "occurrence_count": template.occurrence_count,
            "first_seen": template.first_seen.isoformat() if template.first_seen else None,
            "last_seen": template.last_seen.isoformat() if template.last_seen else None,
            "services": _safe_labels(template.services),
            "files": _safe_source_names(template.files),
        },
        "representative_lines": [
            {
                "sample_reason": redact_bounded_text(
                    sample.sample_reason,
                    max_length=MAX_CONTEXT_LABEL_CHARS,
                ),
                "timestamp": sample.timestamp.isoformat() if sample.timestamp else None,
                "level": (
                    redact_bounded_text(
                        sample.level,
                        max_length=MAX_CONTEXT_LABEL_CHARS,
                    )
                    if sample.level
                    else None
                ),
                "service": (
                    redact_bounded_text(
                        sample.service,
                        max_length=MAX_CONTEXT_LABEL_CHARS,
                    )
                    if sample.service
                    else None
                ),
                "message": redact_bounded_text(
                    sample.message,
                    max_length=message_limit,
                ),
                "evidence": {
                    "log_id": sample.log_id,
                    "template_id": sample.template_id,
                    "line_number": sample.evidence_ref.line_number,
                },
            }
            for sample in selected_samples
        ],
    }


MAX_CONCURRENT_ANNOTATIONS = 8


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
    max_concurrency: int = MAX_CONCURRENT_ANNOTATIONS,
) -> list[TemplateAnnotation]:
    samples_by_template: dict[str, list[RepresentativeSample]] = {}
    for sample in samples:
        samples_by_template.setdefault(sample.template_id, []).append(sample)

    model = str(case_context.get("model") or "gpt-5.4")
    reasoning_effort = str(case_context.get("reasoning_effort") or "high")
    instructions = _load_annotation_prompt()
    semaphore = asyncio.Semaphore(max(1, max_concurrency))

    async def annotate_one(template: LogTemplate) -> TemplateAnnotation:
        payload = build_annotation_payload(
            case_context=case_context,
            template=template,
            samples=samples_by_template.get(template.template_id, []),
            max_sample_message_chars=max_sample_message_chars,
            max_samples_per_template=max_samples_per_template,
        )
        async with semaphore:
            response = await gateway.responses(
                user_id=case_context.get("user_id", "local"),
                model=model,
                instructions=instructions,
                input=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "input_text",
                                "text": json.dumps(
                                    payload,
                                    separators=(",", ":"),
                                    sort_keys=True,
                                ),
                            }
                        ],
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
        return TemplateAnnotation(
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

    selected = _prioritized_templates(templates, max_templates=max_templates)
    results = await asyncio.gather(
        *(annotate_one(template) for template in selected),
        return_exceptions=True,
    )
    # One failing model call must not fail the whole run: templates whose
    # annotation errored keep their heuristic annotation (the pipeline merges by
    # template id).
    annotations: list[TemplateAnnotation] = []
    for template, outcome in zip(selected, results):
        if isinstance(outcome, BaseException):
            logger.warning(
                "template annotation failed; keeping heuristic annotation",
                extra={"template_id": template.template_id},
                exc_info=outcome,
            )
            continue
        annotations.append(outcome)
    return annotations
