from __future__ import annotations

import hashlib
import uuid
from collections import Counter, defaultdict

from logan_workers.models import LogTemplate, NormalizedLogLine, RepresentativeSample


LEVEL_SCORE = {
    "FATAL": 5,
    "CRITICAL": 5,
    "ERROR": 4,
    "WARN": 3,
    "WARNING": 3,
    "INFO": 2,
    "DEBUG": 1,
    "TRACE": 1,
}


def _sample(
    *,
    reason: str,
    rank: int,
    line: NormalizedLogLine,
) -> RepresentativeSample:
    return RepresentativeSample(
        sample_id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"{line.template_id}:{line.log_id}:{reason}")),
        template_id=line.template_id or "",
        log_id=line.log_id,
        sample_reason=reason,
        sample_rank=rank,
        timestamp=line.timestamp,
        level=line.level,
        service=line.service,
        message=line.redacted_message,
        evidence_ref=line.evidence_ref(),
    )


def select_representative_samples(
    logs: list[NormalizedLogLine], templates: list[LogTemplate], *, max_samples_per_template: int = 5
) -> list[RepresentativeSample]:
    by_template: dict[str, list[NormalizedLogLine]] = defaultdict(list)
    for line in logs:
        if line.template_id:
            by_template[line.template_id].append(line)

    samples: list[RepresentativeSample] = []
    for template in templates:
        group = sorted(
            by_template.get(template.template_id, []),
            key=lambda line: (line.timestamp is None, line.timestamp, line.ingestion_order),
        )
        if not group:
            continue

        selected: dict[str, tuple[str, NormalizedLogLine]] = {}
        selected["earliest"] = ("earliest", group[0])
        selected["highest_level"] = (
            "highest_level",
            max(group, key=lambda line: LEVEL_SCORE.get((line.level or "").upper(), 0)),
        )
        stack = next((line for line in group if "\n" in line.message), None)
        if stack:
            selected["stack_trace_head_tail"] = ("stack_trace_head_tail", stack)

        message_counts = Counter(line.redacted_message for line in group)
        selected["most_frequent_variable_combo"] = (
            "most_frequent_variable_combo",
            max(group, key=lambda line: message_counts[line.redacted_message]),
        )
        rare = min(group, key=lambda line: message_counts[line.redacted_message])
        selected["rare_variable_combo"] = ("rare_variable_combo", rare)

        unique_by_log: dict[str, tuple[str, NormalizedLogLine]] = {}
        for reason, line in selected.values():
            unique_by_log.setdefault(line.log_id, (reason, line))

        if not unique_by_log:
            fallback = group[int(hashlib.sha256(template.template_id.encode()).hexdigest(), 16) % len(group)]
            unique_by_log[fallback.log_id] = ("random_fallback", fallback)

        for rank, (reason, line) in enumerate(list(unique_by_log.values())[:max_samples_per_template]):
            samples.append(_sample(reason=reason, rank=rank, line=line))
    return samples
