from __future__ import annotations

import re
import uuid
from collections import Counter

from logan_analysis.models import (
    LogTemplate,
    NormalizedLogLine,
    RepresentativeSample,
    TemplateAnnotation,
)

HEURISTIC_PROVIDER = "heuristic"
HEURISTIC_MODEL = "rules_v1"
PROMPT_VERSION = "heuristic_v1"

LEVEL_SEVERITY = {
    "FATAL": 0.9,
    "CRITICAL": 0.9,
    "ERROR": 0.7,
    "WARN": 0.4,
    "WARNING": 0.4,
    "INFO": 0.1,
    "DEBUG": 0.05,
    "TRACE": 0.05,
}

_LATENCY_RE = re.compile(
    r"\b(timed?[ _-]?out|timeout|latency|too slow|slow query|deadline exceeded)\b"
)
_AVAILABILITY_RE = re.compile(
    r"\b(connection (?:refused|reset|closed)|unavailable|cannot connect|no route|"
    r"service down|unreachable|refused|econnrefused|host not found)\b"
)
_SATURATION_RE = re.compile(
    r"\b(out of memory|oom|heap space|too many|pool exhausted|queue (?:full|overflow)|"
    r"disk full|no space|throttl|rate limit|resource exhausted)\b"
)

_FAULT_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b(nullpointerexception|npe|null pointer)\b"), "application-bug"),
    (
        re.compile(
            r"\b(exception|traceback|stack ?trace|error occurred|internal[ _]error)\b"
        ),
        "application-error",
    ),
    (
        re.compile(r"\b(database|sql|jdbc|db2|oracle|deadlock|constraint violation)\b"),
        "database",
    ),
    (
        re.compile(r"\b(reconcil|no match found|mismatch|length check failed|checksum)\b"),
        "data-integrity",
    ),
    (
        re.compile(r"\b(user ?id|user context|session|auth|login|credential|permission|denied)\b"),
        "auth-session",
    ),
    (re.compile(r"\b(timed?[ _-]?out|timeout)\b"), "timeout"),
    (
        re.compile(r"\b(connection|network|socket|unreachable|refused)\b"),
        "connectivity",
    ),
]


def _classify(text: str, level: str | None) -> tuple[str, list[str], float]:
    lowered = text[:2000].lower()
    level_name = (level or "").upper()
    severity = LEVEL_SEVERITY.get(level_name, 0.2)

    if _AVAILABILITY_RE.search(lowered):
        signal = "availability"
    elif _SATURATION_RE.search(lowered):
        signal = "saturation"
    elif _LATENCY_RE.search(lowered):
        signal = "latency"
    elif level_name in {"FATAL", "CRITICAL", "ERROR"}:
        signal = "error"
    elif level_name in {"WARN", "WARNING"}:
        signal = "error"
    else:
        signal = "information"

    categories = [label for pattern, label in _FAULT_RULES if pattern.search(lowered)]
    return signal, categories[:3], severity


def annotate_templates_heuristically(
    *,
    analysis_run_id: str,
    templates: list[LogTemplate],
    logs: list[NormalizedLogLine],
    samples: list[RepresentativeSample],
) -> list[TemplateAnnotation]:
    """Deterministic, model-free annotation from levels and message keywords.

    Guarantees the causal graph, RCA candidates, and attention-scoped summary work
    without an LLM provider; when a model gateway is configured its annotations
    replace these for the templates it covers.
    """
    level_by_template: dict[str, Counter[str]] = {}
    stack_by_template: set[str] = set()
    for line in logs:
        if not line.template_id:
            continue
        counter = level_by_template.setdefault(line.template_id, Counter())
        counter[(line.level or "").upper()] += 1
        if len(line.line_numbers) > 1:
            stack_by_template.add(line.template_id)

    sample_text_by_template: dict[str, str] = {}
    for sample in samples:
        existing = sample_text_by_template.get(sample.template_id, "")
        if len(existing) < 4000:
            sample_text_by_template[sample.template_id] = (
                f"{existing}\n{sample.message[:1000]}"
            )

    annotations: list[TemplateAnnotation] = []
    for template in templates:
        levels = level_by_template.get(template.template_id, Counter())
        dominant_level = max(
            levels,
            key=lambda name: (LEVEL_SEVERITY.get(name, 0.0), levels[name]),
            default=None,
        )
        text = f"{template.template_text}\n{sample_text_by_template.get(template.template_id, '')}"
        signal, categories, severity = _classify(text, dominant_level)
        if template.template_id in stack_by_template:
            severity = min(1.0, severity + 0.1)
            if "application-error" not in categories:
                categories = [*categories, "application-error"][:3]
        annotations.append(
            TemplateAnnotation(
                annotation_id=str(
                    uuid.uuid5(
                        uuid.NAMESPACE_URL,
                        f"{template.template_id}:{PROMPT_VERSION}",
                    )
                ),
                template_id=template.template_id,
                analysis_run_id=analysis_run_id,
                model_provider=HEURISTIC_PROVIDER,
                model_name=HEURISTIC_MODEL,
                prompt_version=PROMPT_VERSION,
                raw_model_response={},
                golden_signal=signal,
                fault_categories=categories,
                entities={},
                severity_score=severity,
                confidence=0.5,
                rationale=(
                    "Rule-based classification from log level and message keywords."
                ),
            )
        )
    return annotations
