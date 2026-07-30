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


# Support/lag statistics stay accurate on an evenly-spaced sample, while keeping
# pairwise edge scoring linear in the sample size instead of raw line counts.
MAX_EVENT_TIMES_PER_TEMPLATE = 2000


def _event_times(logs: list[NormalizedLogLine]) -> dict[str, list[datetime]]:
    grouped: dict[str, list[datetime]] = defaultdict(list)
    for line in logs:
        if line.template_id and line.timestamp and line.golden_signal in OFFENDING_SIGNALS:
            grouped[line.template_id].append(line.timestamp)
    sampled: dict[str, list[datetime]] = {}
    for template_id, times in grouped.items():
        times.sort()
        if len(times) > MAX_EVENT_TIMES_PER_TEMPLATE:
            step = -(-len(times) // MAX_EVENT_TIMES_PER_TEMPLATE)
            times = times[::step]
        sampled[template_id] = times
    return sampled


def _support(
    source_epochs: list[int],
    target_epochs: list[int],
    max_lag_seconds: int,
) -> tuple[int, int | None]:
    lags: list[int] = []
    for target in target_epochs:
        index = bisect_right(source_epochs, target)
        if index == 0:
            continue
        lag = target - source_epochs[index - 1]
        if lag <= max_lag_seconds:
            lags.append(lag)
    return (
        len(lags),
        int(statistics.median(lags)) if lags else None,
    )


def _shared_context(
    source_services: set[str],
    source_entities: set[str],
    target_services: set[str],
    target_entities: set[str],
) -> float:
    if source_services & target_services:
        return 1.0
    if source_services & target_entities or target_services & source_entities:
        return 0.8
    if source_entities & target_entities:
        return 0.5
    return 0.0


# Edge inference is quadratic in node count; bounding nodes keeps the graph
# readable and the computation predictable on runs with many offending templates.
MAX_CAUSAL_NODES = 200
MAX_EDGES_PER_TARGET = 6


def infer_causal_graph(
    *,
    case_id: str,
    analysis_run_id: str,
    templates: list[LogTemplate],
    logs: list[NormalizedLogLine],
    max_lag_seconds: int = 600,
    max_nodes: int = MAX_CAUSAL_NODES,
    max_edges_per_target: int = MAX_EDGES_PER_TARGET,
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

    # Per-template context is precomputed in one pass; the pairwise loop below
    # must not rescan raw log lines.
    severity_by_template: dict[str, float] = {}
    services_by_template: dict[str, set[str]] = {}
    entities_by_template: dict[str, set[str]] = {}
    for template_id, template_lines in lines_by_template.items():
        severity = 0.0
        services: set[str] = set()
        entity_values: set[str] = set()
        for line in template_lines:
            if line.severity_score > severity:
                severity = line.severity_score
            if line.service:
                services.add(line.service)
            for values in line.entities.values():
                entity_values.update(values)
        severity_by_template[template_id] = severity
        services_by_template[template_id] = services
        entities_by_template[template_id] = entity_values

    if len(nodes) > max_nodes:
        nodes.sort(
            key=lambda node: (
                -severity_by_template.get(node.template_id, 0.0),
                -node.occurrence_count,
                node.template_id,
            )
        )
        nodes = nodes[:max_nodes]

    # Integer epochs keep the pairwise support loop in cheap int math instead of
    # datetime arithmetic.
    epochs_by_template = {
        template_id: [int(time.timestamp()) for time in times]
        for template_id, times in times_by_template.items()
    }

    candidate_edges: list[CausalEdge] = []
    for source in nodes:
        for target in nodes:
            if source.id == target.id or not source.first_seen or not target.first_seen:
                continue
            if source.first_seen > target.first_seen:
                continue
            source_epochs = epochs_by_template[source.template_id]
            target_epochs = epochs_by_template[target.template_id]
            support, lag_seconds = _support(
                source_epochs,
                target_epochs,
                max_lag_seconds,
            )
            if support == 0:
                continue
            support_score = support / max(1, len(target_epochs))
            lag_score = 1.0 - min(1.0, (lag_seconds or 0) / max(1, max_lag_seconds))
            context_score = _shared_context(
                services_by_template[source.template_id],
                entities_by_template[source.template_id],
                services_by_template[target.template_id],
                entities_by_template[target.template_id],
            )
            source_severity = severity_by_template[source.template_id]
            confidence = _clamp(
                0.45 * support_score
                + 0.30 * lag_score
                + 0.15 * context_score
                + 0.10 * source_severity
            )
            if confidence < 0.35:
                continue
            candidate_edges.append(
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

    # In a dense burst almost every early template correlates with every later
    # one; keeping only the strongest explanations per effect keeps the graph
    # readable and the persisted artifact small.
    edges_by_target: dict[str, list[CausalEdge]] = defaultdict(list)
    for edge in candidate_edges:
        edges_by_target[edge.target_template_id].append(edge)
    edges = [
        edge
        for grouped_edges in edges_by_target.values()
        for edge in sorted(grouped_edges, key=lambda item: -item.confidence)[
            :max_edges_per_target
        ]
    ]

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
        severity = severity_by_template.get(node.template_id, 0.0)
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
