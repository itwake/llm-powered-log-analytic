from __future__ import annotations

import statistics
import uuid
from bisect import bisect_right
from collections import defaultdict
from datetime import datetime

from logan_analysis.models import (
    OFFENDING_SIGNALS,
    CausalEdge,
    CausalGraph,
    CausalNode,
    LogTemplate,
    NormalizedLogLine,
    RootCauseCandidate,
)


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def _event_times(logs: list[NormalizedLogLine]) -> dict[str, list[datetime]]:
    grouped: dict[str, list[datetime]] = defaultdict(list)
    for line in logs:
        if line.template_id and line.timestamp and line.golden_signal in OFFENDING_SIGNALS:
            grouped[line.template_id].append(line.timestamp)
    return {template_id: sorted(times) for template_id, times in grouped.items()}


def _support(
    source_times: list[datetime],
    target_times: list[datetime],
    max_lag_seconds: int,
) -> tuple[int, int | None]:
    lags: list[int] = []
    for target in target_times:
        index = bisect_right(source_times, target)
        if index == 0:
            continue
        lag = int((target - source_times[index - 1]).total_seconds())
        if 0 <= lag <= max_lag_seconds:
            lags.append(lag)
    return (
        len(lags),
        int(statistics.median(lags)) if lags else None,
    )


def _shared_context(
    source_lines: list[NormalizedLogLine],
    target_lines: list[NormalizedLogLine],
) -> float:
    source_services = {line.service for line in source_lines if line.service}
    target_services = {line.service for line in target_lines if line.service}
    source_entities = {
        value
        for line in source_lines
        for values in line.entities.values()
        for value in values
    }
    target_entities = {
        value
        for line in target_lines
        for values in line.entities.values()
        for value in values
    }
    if source_services & target_services:
        return 1.0
    if source_services & target_entities or target_services & source_entities:
        return 0.8
    if source_entities & target_entities:
        return 0.5
    return 0.0


def infer_causal_graph(
    *,
    case_id: str,
    analysis_run_id: str,
    templates: list[LogTemplate],
    logs: list[NormalizedLogLine],
    max_lag_seconds: int = 600,
) -> CausalGraph:
    templates_by_id = {template.template_id: template for template in templates}
    lines_by_template: dict[str, list[NormalizedLogLine]] = defaultdict(list)
    for line in logs:
        if line.template_id:
            lines_by_template[line.template_id].append(line)
    times_by_template = _event_times(logs)

    nodes: list[CausalNode] = []
    for template_id, times in times_by_template.items():
        template = templates_by_id.get(template_id)
        template_lines = lines_by_template[template_id]
        if template is None or not template_lines:
            continue
        representative = max(
            template_lines,
            key=lambda line: (line.severity_score, line.confidence),
        )
        nodes.append(
            CausalNode(
                id=template_id,
                label=template.template_text.replace("<*>", "...")[:96],
                template_id=template_id,
                golden_signal=representative.golden_signal,
                fault_categories=representative.fault_categories,
                occurrence_count=template.occurrence_count,
                first_seen=min(times),
                last_seen=max(times),
                confidence=round(representative.confidence, 4),
                evidence_refs=[representative.evidence_ref()],
            )
        )

    edges: list[CausalEdge] = []
    for source in nodes:
        for target in nodes:
            if source.id == target.id or not source.first_seen or not target.first_seen:
                continue
            if source.first_seen > target.first_seen:
                continue
            source_times = times_by_template[source.template_id]
            target_times = times_by_template[target.template_id]
            support, lag_seconds = _support(
                source_times,
                target_times,
                max_lag_seconds,
            )
            if support == 0:
                continue
            support_score = support / max(1, len(target_times))
            lag_score = 1.0 - min(1.0, (lag_seconds or 0) / max(1, max_lag_seconds))
            context_score = _shared_context(
                lines_by_template[source.template_id],
                lines_by_template[target.template_id],
            )
            source_severity = max(
                line.severity_score for line in lines_by_template[source.template_id]
            )
            confidence = _clamp(
                0.45 * support_score
                + 0.30 * lag_score
                + 0.15 * context_score
                + 0.10 * source_severity
            )
            if confidence < 0.35:
                continue
            edges.append(
                CausalEdge(
                    id=str(
                        uuid.uuid5(
                            uuid.NAMESPACE_URL,
                            f"{analysis_run_id}:{source.id}:{target.id}",
                        )
                    ),
                    source=source.id,
                    target=target.id,
                    source_template_id=source.template_id,
                    target_template_id=target.template_id,
                    lag_seconds=lag_seconds,
                    support_windows=support,
                    confidence=round(confidence, 4),
                    evidence={
                        "support_ratio": round(support_score, 4),
                        "lag_score": round(lag_score, 4),
                        "shared_context_score": round(context_score, 4),
                        "source_severity": round(source_severity, 4),
                    },
                )
            )

    outgoing: dict[str, list[float]] = defaultdict(list)
    for edge in edges:
        outgoing[edge.source_template_id].append(edge.confidence)
    earliest = min((node.first_seen for node in nodes if node.first_seen), default=None)
    latest = max((node.first_seen for node in nodes if node.first_seen), default=None)
    span = max(1.0, (latest - earliest).total_seconds()) if earliest and latest else 1.0
    for node in nodes:
        early_score = (
            1.0 - ((node.first_seen - earliest).total_seconds() / span)
            if earliest and node.first_seen
            else 0.5
        )
        edge_score = (
            statistics.mean(outgoing[node.template_id])
            if outgoing[node.template_id]
            else 0.0
        )
        severity = max(
            (line.severity_score for line in lines_by_template[node.template_id]),
            default=0.0,
        )
        node.rank_score = round(
            _clamp(0.5 * early_score + 0.3 * edge_score + 0.2 * severity),
            4,
        )

    nodes.sort(key=lambda node: (-node.rank_score, node.template_id))
    edges.sort(key=lambda edge: (-edge.confidence, edge.lag_seconds or 0))
    candidates = [
        RootCauseCandidate(
            template_id=node.template_id,
            rank=index + 1,
            score=node.rank_score,
            reason="Early high-severity signal with supported downstream associations.",
        )
        for index, node in enumerate(nodes[:5])
    ]
    return CausalGraph(
        nodes=nodes,
        edges=edges,
        root_cause_candidates=candidates,
    )
