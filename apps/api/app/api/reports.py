from __future__ import annotations

import html
import json
import uuid
from collections import Counter, defaultdict
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from logan_workers.activities.export import export_analysis
from logan_workers.models import OFFENDING_SIGNALS, ExportArtifact

from app.dependencies import current_user, get_store, require_case_permission
from app.schemas.case import (
    CausalSummaryUpdateRequest,
    ExportRequest,
    FeedbackRequest,
)
from app.store import MetadataStore, UserRecord

router = APIRouter(prefix="/api/cases", tags=["cases"])


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _require_result(store: MetadataStore, case_id: str, run_id: str):
    result = store.get_analysis_result(case_id, run_id)
    if not result:
        raise HTTPException(status_code=404, detail="analysis result not found")
    return result


def _query_report(
    store: MetadataStore,
    method_name: str,
    **kwargs: Any,
) -> dict[str, object] | None:
    method = getattr(store, method_name, None)
    if not callable(method):
        return None
    return method(**kwargs)


def _causal_summary_export_artifact(
    *,
    case_id: str,
    run_id: str,
    export_type: str,
    summary: dict[str, object],
) -> ExportArtifact:
    export_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{run_id}:{export_type}"))
    summary_markdown = str(summary.get("summary_markdown") or "")
    if export_type == "markdown":
        content = summary_markdown
    elif export_type == "html":
        content = (
            "<!doctype html><html><head><meta charset=\"utf-8\"><title>LogAn Export</title></head>"
            "<body><main><pre>"
            + html.escape(summary_markdown)
            + "</pre></main></body></html>"
        )
    elif export_type == "json":
        content = json.dumps(
            {
                "case_id": case_id,
                "analysis_run_id": run_id,
                "summary": summary,
            },
            indent=2,
            sort_keys=True,
        )
    else:
        raise ValueError(f"unsupported export type: {export_type}")
    return ExportArtifact(
        export_id=export_id,
        export_type=export_type,  # type: ignore[arg-type]
        content=content,
        object_uri=f"memory://exports/{run_id}/{export_id}.{export_type}",
    )


def _record_raw_log_search(
    *,
    store: MetadataStore,
    request: Request,
    user: UserRecord,
    case_id: str,
    run_id: str,
    window_start: str | None,
    window_end: str | None,
    q: str | None,
    service: str | None,
    limit: int,
    offset: int,
) -> None:
    store.record_audit(
        action="raw_log.search",
        user_id=user.id,
        target_type="analysis_run",
        target_id=run_id,
        case_id=case_id,
        metadata={
            "window_start": window_start,
            "window_end": window_end,
            "q": q,
            "service": service,
            "limit": limit,
            "offset": offset,
        },
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )


@router.get("/{case_id}/analysis-runs/{run_id}/summary")
def data_summary(
    case_id: str,
    run_id: str,
    golden_signal: str | None = None,
    scope: str = "attention",
    limit: int = 100,
    offset: int = 0,
    user: UserRecord = Depends(current_user),
    store: MetadataStore = Depends(get_store),
) -> dict[str, object]:
    require_case_permission(
        store=store,
        user=user,
        case_id=case_id,
        permission="view",
        hide_forbidden=True,
    )
    report = _query_report(
        store,
        "get_report_summary",
        case_id=case_id,
        run_id=run_id,
        golden_signal=golden_signal,
        scope=scope,
        limit=limit,
        offset=offset,
    )
    if report is not None:
        return report

    result = _require_result(store, case_id, run_id)
    summary_scope = "all" if scope == "all" else "attention"
    annotations = {annotation.template_id: annotation for annotation in result.annotations}
    samples = {sample.template_id: sample for sample in result.samples}
    items = []
    for template in result.templates:
        annotation = annotations.get(template.template_id)
        signal = annotation.golden_signal if annotation else "unknown"
        if not annotation and summary_scope != "all":
            continue
        if golden_signal and signal != golden_signal:
            continue
        if (
            not golden_signal
            and summary_scope == "attention"
            and signal not in OFFENDING_SIGNALS
        ):
            continue
        sample = samples.get(template.template_id)
        items.append(
            {
                "template_id": template.template_id,
                "representative_log_id": (
                    sample.log_id if sample else template.representative_log_id
                ),
                "template_text": template.template_text,
                "representative_message": (
                    sample.message if sample else template.template_text
                ),
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
    raw_count = sum(len(file.lines) for file in result.files)
    total = len(items)
    offending_total = sum(
        1
        for annotation in annotations.values()
        if annotation.golden_signal in OFFENDING_SIGNALS
    )
    return {
        "items": items[offset : offset + limit],
        "total": total,
        "reduction": {
            "raw_log_lines": raw_count,
            "offending_templates": offending_total,
            "visible_templates": total,
            "annotated_templates": len(annotations),
            "scope": summary_scope,
            "estimated_review_reduction": 1 - (total / raw_count) if raw_count else 0,
        },
    }


@router.get("/{case_id}/analysis-runs/{run_id}/temporal")
def temporal(
    case_id: str,
    run_id: str,
    window_size_seconds: int = 60,
    group_by: str = "golden_signal",
    user: UserRecord = Depends(current_user),
    store: MetadataStore = Depends(get_store),
) -> dict[str, object]:
    del window_size_seconds
    require_case_permission(
        store=store,
        user=user,
        case_id=case_id,
        permission="view",
        hide_forbidden=True,
    )
    report = _query_report(
        store,
        "get_report_temporal",
        case_id=case_id,
        run_id=run_id,
        group_by=group_by,
    )
    if report is not None:
        return report

    result = _require_result(store, case_id, run_id)
    grouped: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for aggregate in result.temporal:
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
        "window_size_seconds": (
            result.temporal[0].window_size_seconds if result.temporal else 60
        ),
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
    request: Request,
    case_id: str,
    run_id: str,
    window_start: str | None = None,
    window_end: str | None = None,
    q: str | None = None,
    service: str | None = None,
    limit: int = 200,
    offset: int = 0,
    user: UserRecord = Depends(current_user),
    store: MetadataStore = Depends(get_store),
) -> dict[str, object]:
    require_case_permission(
        store=store,
        user=user,
        case_id=case_id,
        permission="view",
        hide_forbidden=True,
    )
    start = _parse_dt(window_start)
    end = _parse_dt(window_end)
    report = _query_report(
        store,
        "get_report_logs",
        case_id=case_id,
        run_id=run_id,
        window_start=start,
        window_end=end,
        q=q,
        service=service,
        limit=limit,
        offset=offset,
    )
    if report is not None:
        _record_raw_log_search(
            store=store,
            request=request,
            user=user,
            case_id=case_id,
            run_id=run_id,
            window_start=window_start,
            window_end=window_end,
            q=q,
            service=service,
            limit=limit,
            offset=offset,
        )
        return report

    result = _require_result(store, case_id, run_id)
    _record_raw_log_search(
        store=store,
        request=request,
        user=user,
        case_id=case_id,
        run_id=run_id,
        window_start=window_start,
        window_end=window_end,
        q=q,
        service=service,
        limit=limit,
        offset=offset,
    )
    rows = result.normalized_logs
    if start:
        rows = [line for line in rows if line.timestamp and line.timestamp >= start]
    if end:
        rows = [line for line in rows if line.timestamp and line.timestamp <= end]
    if q:
        lowered = q.lower()
        rows = [
            line
            for line in rows
            if lowered in line.redacted_message.lower()
            or lowered in (line.template_text or "").lower()
            or any(
                lowered in value.lower()
                for values in line.entities.values()
                for value in values
            )
        ]
    if service:
        rows = [line for line in rows if line.service == service]
    facets = {
        "service": [
            {"value": key, "count": count}
            for key, count in Counter(line.service or "unknown" for line in rows).items()
        ],
        "golden_signal": [
            {"value": key, "count": count}
            for key, count in Counter(line.golden_signal for line in rows).items()
        ],
        "fault_category": [
            {"value": key, "count": count}
            for key, count in Counter(
                category
                for line in rows
                for category in line.fault_categories
            ).items()
        ],
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
                "template_text": line.template_text,
                "golden_signal": line.golden_signal,
                "fault_categories": line.fault_categories,
                "entities": line.entities,
            }
            for line in rows[offset : offset + limit]
        ],
        "total": len(rows),
        "facets": facets,
    }


@router.get("/{case_id}/analysis-runs/{run_id}/causal-graph")
def causal_graph(
    case_id: str,
    run_id: str,
    max_nodes: int = 100,
    min_confidence: float = Query(0.0, ge=0, le=1),
    user: UserRecord = Depends(current_user),
    store: MetadataStore = Depends(get_store),
) -> dict[str, object]:
    require_case_permission(
        store=store,
        user=user,
        case_id=case_id,
        permission="view",
        hide_forbidden=True,
    )
    report = _query_report(
        store,
        "get_report_causal_graph",
        case_id=case_id,
        run_id=run_id,
        max_nodes=max_nodes,
        min_confidence=min_confidence,
    )
    if report is not None:
        return report

    result = _require_result(store, case_id, run_id)
    graph = result.causal_graph
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
            candidate.model_dump(mode="json")
            for candidate in graph.root_cause_candidates
        ],
    }


@router.get("/{case_id}/analysis-runs/{run_id}/causal-summary")
def causal_summary(
    case_id: str,
    run_id: str,
    user: UserRecord = Depends(current_user),
    store: MetadataStore = Depends(get_store),
) -> dict[str, object]:
    require_case_permission(
        store=store,
        user=user,
        case_id=case_id,
        permission="view",
        hide_forbidden=True,
    )
    report = _query_report(
        store,
        "get_report_causal_summary",
        case_id=case_id,
        run_id=run_id,
    )
    if report is not None:
        return report

    result = _require_result(store, case_id, run_id)
    return result.causal_summary.model_dump(mode="json")


@router.patch("/{case_id}/analysis-runs/{run_id}/causal-summary")
def update_causal_summary(
    case_id: str,
    run_id: str,
    payload: CausalSummaryUpdateRequest,
    user: UserRecord = Depends(current_user),
    store: MetadataStore = Depends(get_store),
) -> dict[str, object]:
    require_case_permission(
        store=store,
        user=user,
        case_id=case_id,
        permission="edit",
        hide_forbidden=False,
    )
    updated = store.update_causal_summary(
        case_id=case_id,
        run_id=run_id,
        summary_markdown=payload.summary_markdown,
        customer_update_markdown=payload.customer_update_markdown,
        user_id=user.id,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="analysis result not found")
    return updated


@router.post("/{case_id}/analysis-runs/{run_id}/exports")
def create_export(
    case_id: str,
    run_id: str,
    payload: ExportRequest,
    user: UserRecord = Depends(current_user),
    store: MetadataStore = Depends(get_store),
) -> dict[str, object]:
    require_case_permission(
        store=store,
        user=user,
        case_id=case_id,
        permission="edit",
        hide_forbidden=False,
    )
    result = store.get_analysis_result(case_id, run_id)
    if result is not None:
        try:
            artifact = export_analysis(result, payload.export_type)
        except ValueError:
            raise HTTPException(status_code=400, detail="unsupported export type") from None
    else:
        summary = _query_report(
            store,
            "get_report_causal_summary",
            case_id=case_id,
            run_id=run_id,
        )
        if summary is None:
            raise HTTPException(status_code=404, detail="analysis result not found")
        if payload.include_sections and "causal_summary" not in payload.include_sections:
            raise HTTPException(status_code=404, detail="analysis result not found")
        try:
            artifact = _causal_summary_export_artifact(
                case_id=case_id,
                run_id=run_id,
                export_type=payload.export_type,
                summary=summary,
            )
        except ValueError:
            raise HTTPException(status_code=400, detail="unsupported export type") from None
    if not artifact:
        raise HTTPException(status_code=400, detail="unsupported export type")
    store.create_export(
        export_id=artifact.export_id,
        case_id=case_id,
        analysis_run_id=run_id,
        export_type=payload.export_type,
        object_uri=artifact.object_uri,
        user_id=user.id,
    )
    return {
        "export_id": artifact.export_id,
        "download_url": artifact.object_uri,
        "expires_in": 900,
    }


@router.post("/{case_id}/feedback")
def feedback(
    case_id: str,
    payload: FeedbackRequest,
    user: UserRecord = Depends(current_user),
    store: MetadataStore = Depends(get_store),
) -> dict[str, object]:
    require_case_permission(
        store=store,
        user=user,
        case_id=case_id,
        permission="edit",
        hide_forbidden=False,
    )
    record = store.record_feedback(
        case_id=case_id,
        analysis_run_id=payload.analysis_run_id,
        user_id=user.id,
        target_type=payload.target_type,
        target_id=payload.target_id,
        feedback_type=payload.feedback_type,
        rating=payload.rating,
        comment=payload.comment,
        corrected_value=payload.corrected_value,
    )
    return {"feedback_id": record.id}
