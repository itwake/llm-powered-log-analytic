from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from logan_workers.models import OFFENDING_SIGNALS

from app.dependencies import current_user, get_model_gateway, get_store
from app.schemas.case import (
    AnalysisRunListResponse,
    AnalysisRunRequest,
    AnalysisRunResponse,
    CaseCreateRequest,
    CaseResponse,
    ExportRequest,
    FeedbackRequest,
    JobEventListResponse,
    JobEventResponse,
    UploadCompleteRequest,
    UploadRequest,
)
from app.services.copilot_model_gateway import CopilotCredentialError, CopilotGatewayError
from app.services.object_store import (
    ObjectStoreConfigurationError,
    create_presigned_upload,
    digest_bytes,
    file_uri_to_path,
    is_local_backend,
    is_s3_backend,
    object_store_backend,
    stat_object,
    write_bytes,
)
from app.store import MetadataStore, UserRecord, sanitize_error_message


router = APIRouter(prefix="/api/cases", tags=["cases"])


def _case_response(record: Any) -> CaseResponse:
    return CaseResponse(
        case_id=record.id,
        case_key=record.case_key,
        title=record.title,
        status=record.status,
        product=record.product,
        service=record.service,
        environment=record.environment,
        incident_start=record.incident_start,
        incident_end=record.incident_end,
        timezone=record.timezone,
    )


def _analysis_run_response(record: Any) -> AnalysisRunResponse:
    progress = record.progress or (record.result.progress if record.result else {})
    current_step = progress.get("current_step") if isinstance(progress, dict) else None
    return AnalysisRunResponse(
        analysis_run_id=record.id,
        run_number=record.run_number,
        status=record.status,
        current_step=str(current_step or ("completed" if record.status == "completed" else record.status)),
        progress=progress,
        started_at=record.started_at,
        completed_at=record.completed_at,
        error_message=record.error_message,
        model_provider=record.model_provider,
        model_name=record.model_name,
    )


def _job_event_response(record: Any) -> JobEventResponse:
    return JobEventResponse(
        id=record.id,
        case_id=record.case_id,
        analysis_run_id=record.analysis_run_id,
        step_name=record.step_name,
        event_type=record.event_type,
        status=record.status,
        attempt=record.attempt,
        idempotency_key=record.idempotency_key,
        metadata=record.metadata,
        error_message=record.error_message,
        created_at=record.created_at,
    )


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _require_upload_for_case(store: MetadataStore, case_id: str, file_id: str):
    upload = store.get_upload(file_id)
    if not upload or upload.case_id != case_id:
        raise HTTPException(status_code=404, detail="upload not found for case")
    return upload


def _completed_upload_response(upload: Any, *, size_bytes: int | None = None) -> dict[str, object]:
    return {
        "file_id": upload.id,
        "status": "completed",
        "sha256": upload.sha256,
        "size_bytes": upload.size_bytes if size_bytes is None else size_bytes,
    }


def _upload_path_for_analysis(upload: Any) -> str:
    if not upload.completed:
        raise HTTPException(status_code=400, detail=f"upload {upload.id} is not completed")
    try:
        path = file_uri_to_path(upload.object_uri)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"upload {upload.id} is not file-backed and cannot be analyzed locally",
        ) from exc
    if not path.is_file():
        raise HTTPException(status_code=400, detail=f"upload {upload.id} content is missing")
    return str(path)


@router.post("", response_model=CaseResponse)
def create_case(
    payload: CaseCreateRequest,
    user: UserRecord = Depends(current_user),
    store: MetadataStore = Depends(get_store),
) -> CaseResponse:
    record = store.create_case(user_id=user.id, data=payload.model_dump())
    return _case_response(record)


@router.get("")
def list_cases(
    status: str | None = None,
    product: str | None = None,
    page: int = 1,
    page_size: int = 25,
    user: UserRecord = Depends(current_user),
    store: MetadataStore = Depends(get_store),
) -> dict[str, object]:
    del user
    offset = max(0, page - 1) * page_size
    items, total = store.list_cases(status=status, product=product, offset=offset, limit=page_size)
    return {
        "items": [_case_response(item).model_dump(mode="json") for item in items],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/{case_id}", response_model=CaseResponse)
def get_case(
    case_id: str,
    user: UserRecord = Depends(current_user),
    store: MetadataStore = Depends(get_store),
) -> CaseResponse:
    del user
    case = store.get_case(case_id)
    if not case:
        raise HTTPException(status_code=404, detail="case not found")
    return _case_response(case)


@router.post("/{case_id}/uploads")
def request_upload(
    request: Request,
    case_id: str,
    payload: UploadRequest,
    user: UserRecord = Depends(current_user),
    store: MetadataStore = Depends(get_store),
) -> dict[str, object]:
    del user
    if not store.get_case(case_id):
        raise HTTPException(status_code=404, detail="case not found")
    try:
        upload = store.create_upload(
            case_id=case_id,
            filename=payload.filename,
            content_type=payload.content_type,
            size_bytes=payload.size_bytes,
        )
    except ObjectStoreConfigurationError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    backend = object_store_backend(store.settings)
    upload_headers: dict[str, str] = {}
    expires_in = 900
    object_uri: str | None = upload.object_uri
    if is_local_backend(store.settings):
        upload_url = str(request.url_for("upload_content", case_id=case_id, file_id=upload.id))
    elif is_s3_backend(store.settings):
        try:
            presigned = create_presigned_upload(
                upload.object_uri,
                content_type=payload.content_type,
                app_settings=store.settings,
                s3_client_factory=getattr(request.app.state, "s3_client_factory", None),
            )
        except ObjectStoreConfigurationError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        upload_url = presigned.upload_url
        upload_headers = presigned.upload_headers
        backend = presigned.upload_backend
        expires_in = presigned.expires_in
        object_uri = None
    else:
        upload_url = upload.object_uri
    return {
        "file_id": upload.id,
        "upload_url": upload_url,
        "object_uri": object_uri,
        "upload_backend": backend,
        "upload_headers": upload_headers,
        "expires_in": expires_in,
    }


@router.put("/{case_id}/uploads/{file_id}/content", name="upload_content")
async def upload_content(
    request: Request,
    case_id: str,
    file_id: str,
    user: UserRecord = Depends(current_user),
    store: MetadataStore = Depends(get_store),
) -> dict[str, object]:
    del user
    upload_record = _require_upload_for_case(store, case_id, file_id)
    content = await request.body()
    sha256, size_bytes = digest_bytes(content)
    if upload_record.size_bytes != size_bytes:
        raise HTTPException(
            status_code=400,
            detail=(
                f"upload size mismatch: expected {upload_record.size_bytes} bytes, "
                f"received {size_bytes} bytes"
            ),
        )
    if upload_record.completed and upload_record.sha256 != sha256:
        raise HTTPException(
            status_code=409,
            detail="upload already completed with different sha256",
        )
    try:
        stored = write_bytes(upload_record.object_uri, content)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail="raw upload content is only supported for local file-backed uploads",
        ) from exc
    upload = store.complete_upload(upload_id=file_id, sha256=stored.sha256)
    return _completed_upload_response(upload, size_bytes=stored.size_bytes)


@router.post("/{case_id}/uploads/{file_id}/complete")
def complete_upload(
    request: Request,
    case_id: str,
    file_id: str,
    payload: UploadCompleteRequest,
    user: UserRecord = Depends(current_user),
    store: MetadataStore = Depends(get_store),
) -> dict[str, object]:
    del user
    upload_record = _require_upload_for_case(store, case_id, file_id)
    if upload_record.completed:
        if upload_record.sha256 != payload.sha256:
            raise HTTPException(
                status_code=409,
                detail="upload already completed with different sha256",
            )
        return _completed_upload_response(upload_record)
    if upload_record.object_uri.startswith("file://"):
        try:
            stored = stat_object(upload_record.object_uri)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=400, detail="upload content has not been uploaded") from exc
        if upload_record.size_bytes != stored.size_bytes:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"upload size mismatch: expected {upload_record.size_bytes} bytes, "
                    f"found {stored.size_bytes} bytes"
                ),
            )
        if stored.sha256 != payload.sha256:
            raise HTTPException(
                status_code=409,
                detail="upload sha256 does not match stored content",
            )
    elif upload_record.object_uri.startswith("s3://"):
        try:
            stored = stat_object(
                upload_record.object_uri,
                app_settings=store.settings,
                s3_client_factory=getattr(request.app.state, "s3_client_factory", None),
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=400, detail="upload content has not been uploaded") from exc
        except ObjectStoreConfigurationError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        if upload_record.size_bytes != stored.size_bytes:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"upload size mismatch: expected {upload_record.size_bytes} bytes, "
                    f"found {stored.size_bytes} bytes"
                ),
            )
        if stored.sha256 and stored.sha256 != payload.sha256:
            raise HTTPException(
                status_code=409,
                detail="upload sha256 does not match stored content metadata",
            )
    upload = store.complete_upload(upload_id=file_id, sha256=payload.sha256)
    return _completed_upload_response(upload)


@router.post("/{case_id}/analysis-runs")
async def start_analysis(
    case_id: str,
    payload: AnalysisRunRequest,
    user: UserRecord = Depends(current_user),
    store: MetadataStore = Depends(get_store),
    gateway: Any = Depends(get_model_gateway),
) -> dict[str, object]:
    if not store.get_case(case_id):
        raise HTTPException(status_code=404, detail="case not found")
    input_paths = list(payload.input_paths)
    for file_id in payload.input_file_ids:
        upload = _require_upload_for_case(store, case_id, file_id)
        input_paths.append(_upload_path_for_analysis(upload))
    try:
        run = await store.start_analysis(
            case_id=case_id,
            user_id=user.id,
            input_paths=input_paths,
            config=payload.config,
            gateway=gateway,
        )
    except CopilotCredentialError as exc:
        raise HTTPException(status_code=401, detail=sanitize_error_message(exc)) from exc
    except CopilotGatewayError as exc:
        raise HTTPException(status_code=502, detail=sanitize_error_message(exc)) from exc
    return {"analysis_run_id": run.id, "status": run.status}


@router.get("/{case_id}/analysis-runs", response_model=AnalysisRunListResponse)
def list_analysis_runs(
    case_id: str,
    user: UserRecord = Depends(current_user),
    store: MetadataStore = Depends(get_store),
) -> AnalysisRunListResponse:
    del user
    if not store.get_case(case_id):
        raise HTTPException(status_code=404, detail="case not found")
    runs = store.list_analysis_runs(case_id)
    return AnalysisRunListResponse(
        items=[_analysis_run_response(run) for run in runs],
        total=len(runs),
    )


@router.get("/{case_id}/analysis-runs/{run_id}")
def get_analysis_run(
    case_id: str,
    run_id: str,
    user: UserRecord = Depends(current_user),
    store: MetadataStore = Depends(get_store),
) -> dict[str, object]:
    del user
    run = store.get_analysis_run(run_id)
    if not run or run.case_id != case_id:
        raise HTTPException(status_code=404, detail="analysis run not found")
    return _analysis_run_response(run).model_dump(mode="json")


@router.get(
    "/{case_id}/analysis-runs/{run_id}/events",
    response_model=JobEventListResponse,
)
def list_analysis_run_events(
    case_id: str,
    run_id: str,
    user: UserRecord = Depends(current_user),
    store: MetadataStore = Depends(get_store),
) -> JobEventListResponse:
    del user
    run = store.get_analysis_run(run_id)
    if not run or run.case_id != case_id:
        raise HTTPException(status_code=404, detail="analysis run not found")
    events = store.list_job_events(case_id=case_id, analysis_run_id=run_id)
    return JobEventListResponse(
        items=[_job_event_response(event) for event in events],
        total=len(events),
    )


def _require_result(store: MetadataStore, case_id: str, run_id: str):
    result = store.get_analysis_result(case_id, run_id)
    if not result:
        raise HTTPException(status_code=404, detail="analysis result not found")
    return result


def _query_report(store: MetadataStore, method_name: str, **kwargs: Any) -> dict[str, object] | None:
    method = getattr(store, method_name, None)
    if not callable(method):
        return None
    return method(**kwargs)


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
    limit: int = 100,
    offset: int = 0,
    user: UserRecord = Depends(current_user),
    store: MetadataStore = Depends(get_store),
) -> dict[str, object]:
    del user
    report = _query_report(
        store,
        "get_report_summary",
        case_id=case_id,
        run_id=run_id,
        golden_signal=golden_signal,
        limit=limit,
        offset=offset,
    )
    if report is not None:
        return report

    result = _require_result(store, case_id, run_id)
    annotations = {annotation.template_id: annotation for annotation in result.annotations}
    samples = {sample.template_id: sample for sample in result.samples}
    items = []
    for template in result.templates:
        annotation = annotations.get(template.template_id)
        if not annotation:
            continue
        if golden_signal and annotation.golden_signal != golden_signal:
            continue
        if not golden_signal and annotation.golden_signal not in OFFENDING_SIGNALS:
            continue
        sample = samples.get(template.template_id)
        items.append(
            {
                "template_id": template.template_id,
                "representative_log_id": sample.log_id if sample else template.representative_log_id,
                "template_text": template.template_text,
                "representative_message": sample.message if sample else template.template_text,
                "golden_signal": annotation.golden_signal,
                "fault_categories": annotation.fault_categories,
                "entities": annotation.entities,
                "occurrence_count": template.occurrence_count,
                "first_seen": template.first_seen.isoformat() if template.first_seen else None,
                "last_seen": template.last_seen.isoformat() if template.last_seen else None,
                "files": template.files,
                "services": template.services,
                "severity_score": annotation.severity_score,
                "confidence": annotation.confidence,
            }
        )
    items.sort(key=lambda item: (-item["severity_score"], item["first_seen"] or ""))
    raw_count = sum(len(file.lines) for file in result.files)
    total = len(items)
    return {
        "items": items[offset : offset + limit],
        "total": total,
        "reduction": {
            "raw_log_lines": raw_count,
            "offending_templates": total,
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
    del user, window_size_seconds
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
        "window_size_seconds": result.temporal[0].window_size_seconds if result.temporal else 60,
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
            or any(lowered in value.lower() for values in line.entities.values() for value in values)
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
            for key, count in Counter(cat for line in rows for cat in line.fault_categories).items()
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
    del user
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
        if edge.confidence >= min_confidence and edge.source in node_ids and edge.target in node_ids
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
    store: MetadataStore = Depends(get_store),
) -> dict[str, object]:
    del user
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


@router.post("/{case_id}/analysis-runs/{run_id}/exports")
def create_export(
    case_id: str,
    run_id: str,
    payload: ExportRequest,
    user: UserRecord = Depends(current_user),
    store: MetadataStore = Depends(get_store),
) -> dict[str, object]:
    result = _require_result(store, case_id, run_id)
    artifact = result.exports.get(payload.export_type)
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
    if not store.get_case(case_id):
        raise HTTPException(status_code=404, detail="case not found")
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
