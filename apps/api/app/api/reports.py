from __future__ import annotations

from collections import defaultdict
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from logan_analysis.models import OFFENDING_SIGNALS
from pydantic import AwareDatetime

from app.dependencies import current_user, get_store, require_case_owner
from app.store import Store, UserRecord

router = APIRouter(prefix="/api/cases", tags=["cases"])


def _require_report_value(
    store: Store,
    case_id: str,
    run_id: str,
    value: Any,
) -> Any:
    if value is not None:
        return value
    run = store.get_analysis_run(run_id)
    if run is None or run.case_id != case_id:
        raise HTTPException(status_code=404, detail="analysis run not found")
    if run.status in {"queued", "processing"}:
        raise HTTPException(status_code=409, detail="analysis result is not ready")
    if run.status == "failed":
        raise HTTPException(status_code=409, detail="analysis failed before producing a result")
    if run.status == "cancelled":
        raise HTTPException(status_code=409, detail="analysis was cancelled")
    raise HTTPException(status_code=409, detail="analysis completed without a readable result")


@router.get("/{case_id}/analysis-runs/{run_id}/summary")
def data_summary(
    case_id: str,
    run_id: str,
    golden_signal: str | None = None,
    scope: Literal["attention", "all"] = "attention",
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user: UserRecord = Depends(current_user),
    store: Store = Depends(get_store),
) -> dict[str, object]:
    require_case_owner(
        store=store,
        user=user,
        case_id=case_id,
    )
    result = _require_report_value(
        store,
        case_id,
        run_id,
        store.get_analysis_report_summary(case_id, run_id),
    )
    annotations = {annotation.template_id: annotation for annotation in result.annotations}
    samples = {sample.template_id: sample for sample in result.samples}
    items = []
    for template in result.templates:
        annotation = annotations.get(template.template_id)
        signal = annotation.golden_signal if annotation else "unknown"
        if not annotation and scope != "all":
            continue
        if golden_signal and signal != golden_signal:
            continue
        if not golden_signal and scope == "attention" and signal not in OFFENDING_SIGNALS:
            continue
        sample = samples.get(template.template_id)
        items.append(
            {
                "template_id": template.template_id,
                "representative_log_id": (
                    sample.log_id if sample else template.representative_log_id
                ),
                "template_text": template.template_text,
                "representative_message": (sample.message if sample else template.template_text),
                "golden_signal": signal,
                "fault_categories": annotation.fault_categories if annotation else [],
                "entities": annotation.entities if annotation else {},
                "occurrence_count": template.occurrence_count,
                "first_seen": template.first_seen.isoformat() if template.first_seen else None,
                "last_seen": template.last_seen.isoformat() if template.last_seen else None,
                "files": template.files,
                "services": template.services,
                "severity_score": annotation.severity_score if annotation else 0.0,
                "confidence": annotation.confidence if annotation else 0.0,
            }
        )
    items.sort(key=lambda item: (-item["severity_score"], item["first_seen"] or ""))
    raw_count = int(result.progress.get("raw_lines") or 0)
    if not raw_count:
        raw_count = sum(len(file.lines) for file in result.files)
    total = len(items)
    offending_total = sum(
        1 for annotation in annotations.values() if annotation.golden_signal in OFFENDING_SIGNALS
    )
    return {
        "items": items[offset : offset + limit],
        "total": total,
        "reduction": {
            "raw_log_lines": raw_count,
            "offending_templates": offending_total,
            "visible_templates": total,
            "annotated_templates": len(annotations),
            "scope": scope,
            "estimated_review_reduction": 1 - (total / raw_count) if raw_count else 0,
        },
    }


@router.get("/{case_id}/analysis-runs/{run_id}/temporal")
def temporal(
    case_id: str,
    run_id: str,
    group_by: Literal["golden_signal", "service", "fault_category", "template"] = "golden_signal",
    user: UserRecord = Depends(current_user),
    store: Store = Depends(get_store),
) -> dict[str, object]:
    require_case_owner(
        store=store,
        user=user,
        case_id=case_id,
    )
    aggregates = _require_report_value(
        store,
        case_id,
        run_id,
        store.get_analysis_temporal(case_id, run_id),
    )
    grouped: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for aggregate in aggregates:
        if group_by == "service":
            name = aggregate.service or "unknown"
        elif group_by == "fault_category":
            name = aggregate.fault_category or "unknown"
        elif group_by == "template":
            name = aggregate.template_id or "unknown"
        else:
            name = aggregate.golden_signal
        grouped[name][aggregate.window_start.isoformat()] += aggregate.count
    return {
        "window_size_seconds": (aggregates[0].window_size_seconds if aggregates else 60),
        "series": [
            {
                "name": name,
                "points": [
                    {"window_start": window_start, "count": count}
                    for window_start, count in sorted(points.items())
                ],
            }
            for name, points in sorted(grouped.items())
        ],
    }


@router.get("/{case_id}/analysis-runs/{run_id}/logs")
def logs(
    case_id: str,
    run_id: str,
    window_start: AwareDatetime | None = None,
    window_end: AwareDatetime | None = None,
    q: str | None = None,
    service: str | None = None,
    template_id: str | None = None,
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    user: UserRecord = Depends(current_user),
    store: Store = Depends(get_store),
) -> dict[str, object]:
    require_case_owner(
        store=store,
        user=user,
        case_id=case_id,
    )
    page = _require_report_value(
        store,
        case_id,
        run_id,
        store.get_analysis_logs_page(
            case_id,
            run_id,
            window_start=window_start,
            window_end=window_end,
            q=q,
            service=service,
            template_id=template_id,
            limit=limit,
            offset=offset,
        ),
    )
    facets = {
        name: [
            {"value": key, "count": count}
            for key, count in page.facets.get(name, {}).items()
        ]
        for name in ("service", "golden_signal", "fault_category")
    }
    return {
        "items": [
            {
                "log_id": line.log_id,
                "timestamp": line.timestamp.isoformat() if line.timestamp else None,
                "level": line.level,
                "service": line.service,
                "file_path": line.file_path,
                "line_number": line.line_number,
                "line_numbers": line.line_numbers,
                "message": line.redacted_message,
                "template_id": line.template_id,
                "template_text": page.template_text_by_id.get(line.template_id or ""),
                "golden_signal": line.golden_signal,
                "fault_categories": line.fault_categories,
                "entities": line.entities,
            }
            for line in page.rows
        ],
        "total": page.total,
        "facets": facets,
    }


@router.get("/{case_id}/analysis-runs/{run_id}/causal-graph")
def causal_graph(
    case_id: str,
    run_id: str,
    max_nodes: int = Query(100, ge=1, le=500),
    min_confidence: float = Query(0.0, ge=0, le=1),
    user: UserRecord = Depends(current_user),
    store: Store = Depends(get_store),
) -> dict[str, object]:
    require_case_owner(
        store=store,
        user=user,
        case_id=case_id,
    )
    graph = _require_report_value(
        store,
        case_id,
        run_id,
        store.get_analysis_causal_graph(case_id, run_id),
    )
    node_ids = {node.id for node in graph.nodes[:max_nodes]}
    edges = [
        edge
        for edge in graph.edges
        if (
            edge.confidence >= min_confidence
            and edge.source in node_ids
            and edge.target in node_ids
        )
    ]
    return {
        "nodes": [node.model_dump(mode="json") for node in graph.nodes[:max_nodes]],
        "edges": [edge.model_dump(mode="json") for edge in edges],
        "root_cause_candidates": [
            candidate.model_dump(mode="json") for candidate in graph.root_cause_candidates
        ],
    }


@router.get("/{case_id}/analysis-runs/{run_id}/causal-summary")
def causal_summary(
    case_id: str,
    run_id: str,
    user: UserRecord = Depends(current_user),
    store: Store = Depends(get_store),
) -> dict[str, object]:
    require_case_owner(
        store=store,
        user=user,
        case_id=case_id,
    )
    result = _require_report_value(
        store,
        case_id,
        run_id,
        store.get_analysis_causal_summary(case_id, run_id),
    )
    return result.model_dump(mode="json")
