from __future__ import annotations

from logan_workers.models import NormalizedLogLine, TemplateAnnotation


def broadcast_annotations(
    logs: list[NormalizedLogLine], annotations: list[TemplateAnnotation]
) -> list[NormalizedLogLine]:
    by_template = {annotation.template_id: annotation for annotation in annotations}
    for line in logs:
        annotation = by_template.get(line.template_id or "")
        if not annotation:
            continue
        line.golden_signal = annotation.golden_signal
        line.fault_categories = list(annotation.fault_categories)
        entities = dict(annotation.entities)
        for key in ("request_id", "trace_id", "thread_id"):
            if key in line.parsed_fields:
                entities.setdefault(key, []).append(str(line.parsed_fields[key]))
        line.entities = {key: sorted(set(value)) for key, value in entities.items() if value}
        line.severity_score = annotation.severity_score
        line.confidence = annotation.confidence
    return logs
