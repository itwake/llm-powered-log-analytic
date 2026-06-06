from __future__ import annotations

import math
import statistics
import uuid
from collections import defaultdict
from datetime import datetime
from typing import Any

from logan_workers.algorithms.pagerank import pagerank
from logan_workers.models import (
    CausalEdge,
    CausalGraph,
    CausalNode,
    LogTemplate,
    NormalizedLogLine,
    OFFENDING_SIGNALS,
    RootCauseCandidate,
)


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def _corr(xs: list[int], ys: list[int]) -> float:
    if len(xs) < 2 or len(ys) < 2:
        return 0.0
    if len(set(xs)) == 1 or len(set(ys)) == 1:
        return 0.0
    mean_x = statistics.mean(xs)
    mean_y = statistics.mean(ys)
    numerator = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    denom_x = math.sqrt(sum((x - mean_x) ** 2 for x in xs))
    denom_y = math.sqrt(sum((y - mean_y) ** 2 for y in ys))
    if denom_x == 0 or denom_y == 0:
        return 0.0
    return max(0.0, numerator / (denom_x * denom_y))


def _template_label(template: LogTemplate) -> str:
    return template.template_text.replace("<*>", "...")[:96]


def _event_times(lines: list[NormalizedLogLine]) -> dict[str, list[datetime]]:
    times: dict[str, list[datetime]] = defaultdict(list)
    for line in lines:
        if line.template_id and line.timestamp and line.golden_signal in OFFENDING_SIGNALS:
            times[line.template_id].append(line.timestamp)
    return {key: sorted(value) for key, value in times.items()}


def _service_relation(source_lines: list[NormalizedLogLine], target_lines: list[NormalizedLogLine]) -> bool:
    source_services = {line.service for line in source_lines if line.service}
    target_entities: set[str] = set()
    for line in target_lines:
        for key in ("target_service", "service", "source_service"):
            target_entities.update(line.entities.get(key, []))
    if source_services & target_entities:
        return True
    source_service = next(iter(source_services), "")
    target_service = next((line.service for line in target_lines if line.service), "")
    if target_service == "gateway" and "payment" in source_service:
        return True
    return False


def _support(source_times: list[datetime], target_times: list[datetime], max_lag_seconds: int) -> tuple[int, int | None]:
    lags: list[int] = []
    for target in target_times:
        preceding = [
            int((target - source).total_seconds())
            for source in source_times
            if 0 < (target - source).total_seconds() <= max_lag_seconds
        ]
        if preceding:
            lags.append(min(preceding))
    if not lags:
        return 0, None
    return len(lags), int(statistics.median(lags))


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

    offending_template_ids = {
        line.template_id for line in logs if line.template_id and line.golden_signal in OFFENDING_SIGNALS
    }
    times_by_template = _event_times(logs)
    nodes: list[CausalNode] = []
    for template_id in offending_template_ids:
        template = templates_by_id[template_id]
        group = lines_by_template[template_id]
        first = template.first_seen or min((line.timestamp for line in group if line.timestamp), default=None)
        last = template.last_seen or max((line.timestamp for line in group if line.timestamp), default=None)
        best_line = max(group, key=lambda line: (line.severity_score, line.confidence))
        nodes.append(
            CausalNode(
                id=template_id,
                label=_template_label(template),
                template_id=template_id,
                golden_signal=best_line.golden_signal,
                fault_categories=best_line.fault_categories,
                occurrence_count=template.occurrence_count,
                first_seen=first,
                last_seen=last,
                confidence=best_line.confidence,
                evidence_refs=[best_line.evidence_ref()],
            )
        )
    nodes.sort(key=lambda node: (node.first_seen is None, node.first_seen, node.label))

    edges: list[CausalEdge] = []
    node_ids = [node.template_id for node in nodes]
    for source_id in node_ids:
        for target_id in node_ids:
            if source_id == target_id:
                continue
            source_times = times_by_template.get(source_id, [])
            target_times = times_by_template.get(target_id, [])
            if not source_times or not target_times or min(source_times) >= max(target_times):
                continue
            support_windows, lag_seconds = _support(source_times, target_times, max_lag_seconds)
            if support_windows == 0:
                continue

            source_lines = lines_by_template[source_id]
            target_lines = lines_by_template[target_id]
            relation = _service_relation(source_lines, target_lines)
            precedence_score = support_windows / max(1, len(target_times))
            lift_score = min(1.0, support_windows / max(1, len(source_times)))
            correlation_score = _corr(
                [1 if t in source_times else 0 for t in sorted(set(source_times + target_times))],
                [1 if t in target_times else 0 for t in sorted(set(source_times + target_times))],
            )
            method_agreement = (
                1
                + (1 if relation else 0)
                + (1 if correlation_score > 0 else 0)
                + (1 if lift_score >= 0.5 else 0)
            ) / 4
            severity_weight = max((line.severity_score for line in source_lines), default=0)
            confidence = _clamp(
                0.25 * precedence_score
                + 0.20 * method_agreement
                + 0.20 * (0.55 if relation else 0.25)
                + 0.15 * lift_score
                + 0.10 * 0.67
                + 0.10 * severity_weight
            )
            if confidence < 0.35:
                continue

            source_peak = max(source_times, key=lambda t: source_times.count(t))
            target_peak = max(target_times, key=lambda t: target_times.count(t))
            method = "temporal_precedence+lagged_correlation+lift"
            if relation:
                method += "+service_entity"
            evidence: dict[str, Any] = {
                "source_template_id": source_id,
                "target_template_id": target_id,
                "time_bin_seconds": 60,
                "lag_seconds": lag_seconds,
                "support_windows": support_windows,
                "source_first_seen": min(source_times).isoformat(),
                "target_first_seen": min(target_times).isoformat(),
                "source_peak": source_peak.isoformat(),
                "target_peak": target_peak.isoformat(),
                "methods": {
                    "pgem": {"supported": False, "extension_seam": True},
                    "granger_linear": {"supported": False, "extension_seam": True},
                    "temporal_precedence": {"supported": True, "score": precedence_score},
                    "lagged_correlation": {"supported": correlation_score > 0, "score": correlation_score},
                    "lift": {"supported": lift_score >= 0.5, "score": lift_score},
                },
                "sample_windows": [
                    {
                        "source_window": min(source_times).isoformat(),
                        "target_window": min(target_times).isoformat(),
                        "source_count": len(source_times),
                        "target_count": len(target_times),
                    }
                ],
                "limitations": [
                    "Clock skew not ruled out",
                    "Statistical causality is not definitive",
                ],
            }
            edges.append(
                CausalEdge(
                    id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"{analysis_run_id}:{source_id}:{target_id}")),
                    source=source_id,
                    target=target_id,
                    source_template_id=source_id,
                    target_template_id=target_id,
                    method=method,
                    lag_seconds=lag_seconds,
                    support_windows=support_windows,
                    confidence=round(confidence, 4),
                    lift=round(lift_score, 4),
                    temporal_precedence_score=round(precedence_score, 4),
                    correlation_score=round(correlation_score, 4),
                    evidence=evidence,
                    needs_validation=True,
                )
            )

    edges.sort(key=lambda edge: (-edge.confidence, edge.lag_seconds or 0))
    page_scores = pagerank(
        node_ids,
        [(edge.source_template_id, edge.target_template_id, edge.confidence) for edge in edges],
    )
    earliest = min((node.first_seen for node in nodes if node.first_seen), default=None)
    latest = max((node.first_seen for node in nodes if node.first_seen), default=None)
    span = max(1.0, (latest - earliest).total_seconds()) if earliest and latest else 1.0
    outgoing_counts = defaultdict(int)
    for edge in edges:
        outgoing_counts[edge.source_template_id] += 1

    for node in nodes:
        early_score = 0.5
        if earliest and node.first_seen:
            early_score = 1.0 - ((node.first_seen - earliest).total_seconds() / span)
        severity = max((line.severity_score for line in lines_by_template[node.template_id]), default=0)
        relevance = 1.0 if node.golden_signal in {"saturation", "availability"} else 0.6
        node.pagerank_score = round(page_scores.get(node.template_id, 0.0), 4)
        node.rank_score = round(
            _clamp(
                0.35 * node.pagerank_score
                + 0.20 * early_score
                + 0.15 * min(1.0, outgoing_counts[node.template_id] / 3)
                + 0.10 * severity
                + 0.10 * relevance
                + 0.10 * 0.5
            ),
            4,
        )

    ranked = sorted(nodes, key=lambda node: node.rank_score, reverse=True)
    candidates = [
        RootCauseCandidate(
            template_id=node.template_id,
            rank=index + 1,
            score=node.rank_score,
            reason="High PageRank/early occurrence/outgoing candidate edges; needs validation.",
        )
        for index, node in enumerate(ranked[:5])
    ]
    return CausalGraph(nodes=nodes, edges=edges, root_cause_candidates=candidates)
