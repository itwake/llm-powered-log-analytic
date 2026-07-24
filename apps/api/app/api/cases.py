from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from app.dependencies import current_user, get_model_gateway, get_store, require_case_permission
from app.schemas.case import (
    AnalysisRunListResponse,
    AnalysisRunRequest,
    AnalysisRunResponse,
    AnalysisStepArtifactListResponse,
    AnalysisStepArtifactResponse,
    CaseCollaboratorListResponse,
    CaseCollaboratorRequest,
    CaseCollaboratorResponse,
    CaseCreateRequest,
    CaseResponse,
    CaseUpdateRequest,
    JobEventListResponse,
    JobEventResponse,
    UploadCompleteRequest,
    UploadRequest,
)
from app.services.model_gateway import ModelCredentialError, ModelGatewayError
from app.services.object_store import (
    digest_bytes,
    file_uri_to_path,
    stat_object,
    write_bytes,
)
from app.store import MetadataStore, UserRecord, sanitize_error_message

router = APIRouter(prefix="/api/cases", tags=["cases"])
_BACKGROUND_ANALYSIS_LOGGER = logging.getLogger("logan.analysis.background")


def _case_response(record: Any) -> CaseResponse:
    return CaseResponse(
        case_id=record.id,
        case_key=record.case_key,
        title=record.title,
        issue_description=record.issue_description,
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
        current_step=str(
            current_step or ("completed" if record.status == "completed" else record.status)
        ),
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


def _analysis_step_artifact_response(record: Any) -> AnalysisStepArtifactResponse:
    return AnalysisStepArtifactResponse(
        id=record.id,
        case_id=record.case_id,
        analysis_run_id=record.analysis_run_id,
        step_name=record.step_name,
        artifact_type=record.artifact_type,
        object_uri=record.object_uri,
        sha256=record.sha256,
        size_bytes=record.size_bytes,
        metadata=record.metadata or {},
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _case_collaborator_response(record: Any) -> CaseCollaboratorResponse:
    return CaseCollaboratorResponse(
        id=record.id,
        case_id=record.case_id,
        user_id=record.user_id,
        role=record.role,
        added_by=record.added_by,
        email=record.email,
        username=record.username,
        full_name=record.full_name,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


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
            detail=f"upload {upload.id} is not file-backed",
        ) from exc
    if not path.is_file():
        raise HTTPException(status_code=400, detail=f"upload {upload.id} content is missing")
    return str(path)


def _background_analysis_tasks(request: Request) -> dict[str, asyncio.Task[Any]]:
    tasks = getattr(request.app.state, "analysis_tasks", None)
    if not isinstance(tasks, dict):
        tasks = {}
        request.app.state.analysis_tasks = tasks
    return tasks


def _track_background_analysis_task(
    request: Request,
    *,
    run_id: str,
    task: asyncio.Task[Any],
) -> None:
    tasks = _background_analysis_tasks(request)
    tasks[run_id] = task

    def cleanup(done_task: asyncio.Task[Any]) -> None:
        tasks.pop(run_id, None)
        try:
            done_task.result()
        except asyncio.CancelledError:
            return
        except Exception:
            _BACKGROUND_ANALYSIS_LOGGER.exception(
                "background analysis task failed",
                extra={"analysis_run_id": run_id},
            )

    task.add_done_callback(cleanup)


def _cancel_background_analysis_task(request: Request, run_id: str) -> None:
    task = _background_analysis_tasks(request).get(run_id)
    if task is not None and not task.done():
        task.cancel()


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
    offset = max(0, page - 1) * page_size
    items, total = store.list_cases_for_user(
        user,
        status=status,
        product=product,
        offset=offset,
        limit=page_size,
    )
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
    case = require_case_permission(
        store=store,
        user=user,
        case_id=case_id,
        permission="view",
        hide_forbidden=True,
    )
    return _case_response(case)


@router.patch("/{case_id}", response_model=CaseResponse)
def update_case(
    case_id: str,
    payload: CaseUpdateRequest,
    user: UserRecord = Depends(current_user),
    store: MetadataStore = Depends(get_store),
) -> CaseResponse:
    require_case_permission(
        store=store,
        user=user,
        case_id=case_id,
        permission="edit",
        hide_forbidden=False,
    )
    data = payload.model_dump(exclude_unset=True)
    if "title" in data and data["title"] is None:
        raise HTTPException(status_code=400, detail="title cannot be null")
    if "timezone" in data and not data["timezone"]:
        data["timezone"] = "UTC"
    try:
        updated = store.update_case(case_id=case_id, data=data, user_id=user.id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="case not found") from exc
    return _case_response(updated)


@router.delete("/{case_id}")
def delete_case(
    request: Request,
    case_id: str,
    user: UserRecord = Depends(current_user),
    store: MetadataStore = Depends(get_store),
) -> dict[str, object]:
    require_case_permission(
        store=store,
        user=user,
        case_id=case_id,
        permission="owner",
        hide_forbidden=False,
    )
    active_run_ids = [
        run.id
        for run in store.list_analysis_runs(case_id)
        if run.status not in {"completed", "failed", "cancelled"}
    ]
    deleted = store.delete_case(case_id=case_id, user_id=user.id)
    if not deleted:
        raise HTTPException(status_code=404, detail="case not found")
    for run_id in active_run_ids:
        _cancel_background_analysis_task(request, run_id)
    return {"status": "deleted", "deleted": True}


@router.get(
    "/{case_id}/collaborators",
    response_model=CaseCollaboratorListResponse,
)
def list_case_collaborators(
    case_id: str,
    user: UserRecord = Depends(current_user),
    store: MetadataStore = Depends(get_store),
) -> CaseCollaboratorListResponse:
    require_case_permission(
        store=store,
        user=user,
        case_id=case_id,
        permission="owner",
        hide_forbidden=False,
    )
    collaborators = store.list_case_collaborators(case_id)
    return CaseCollaboratorListResponse(
        items=[_case_collaborator_response(collaborator) for collaborator in collaborators],
        total=len(collaborators),
    )


@router.post(
    "/{case_id}/collaborators",
    response_model=CaseCollaboratorResponse,
)
def upsert_case_collaborator(
    case_id: str,
    payload: CaseCollaboratorRequest,
    user: UserRecord = Depends(current_user),
    store: MetadataStore = Depends(get_store),
) -> CaseCollaboratorResponse:
    require_case_permission(
        store=store,
        user=user,
        case_id=case_id,
        permission="owner",
        hide_forbidden=False,
    )
    try:
        collaborator = store.upsert_case_collaborator(
            case_id=case_id,
            user_id=payload.user_id,
            role=payload.role,
            added_by=user.id,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="user or case not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _case_collaborator_response(collaborator)


@router.delete("/{case_id}/collaborators/{user_id}")
def remove_case_collaborator(
    case_id: str,
    user_id: str,
    user: UserRecord = Depends(current_user),
    store: MetadataStore = Depends(get_store),
) -> dict[str, object]:
    require_case_permission(
        store=store,
        user=user,
        case_id=case_id,
        permission="owner",
        hide_forbidden=False,
    )
    try:
        removed = store.remove_case_collaborator(
            case_id=case_id,
            user_id=user_id,
            removed_by=user.id,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="case not found") from exc
    return {"status": "removed" if removed else "not_found", "removed": removed}


@router.post("/{case_id}/uploads")
def request_upload(
    case_id: str,
    payload: UploadRequest,
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
    upload = store.create_upload(
        case_id=case_id,
        filename=payload.filename,
        content_type=payload.content_type,
        size_bytes=payload.size_bytes,
    )
    return {
        "file_id": upload.id,
        "upload_url": f"/api/cases/{case_id}/uploads/{upload.id}/content",
    }


@router.put("/{case_id}/uploads/{file_id}/content", name="upload_content")
async def upload_content(
    request: Request,
    case_id: str,
    file_id: str,
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
    case_id: str,
    file_id: str,
    payload: UploadCompleteRequest,
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
    upload_record = _require_upload_for_case(store, case_id, file_id)
    if upload_record.completed:
        if upload_record.sha256 != payload.sha256:
            raise HTTPException(
                status_code=409,
                detail="upload already completed with different sha256",
            )
        return _completed_upload_response(upload_record)
    try:
        stored = stat_object(upload_record.object_uri)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=400,
            detail="upload content has not been uploaded",
        ) from exc
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
    upload = store.complete_upload(upload_id=file_id, sha256=payload.sha256)
    return _completed_upload_response(upload)


@router.post("/{case_id}/analysis-runs")
async def start_analysis(
    request: Request,
    case_id: str,
    payload: AnalysisRunRequest,
    background: bool = False,
    user: UserRecord = Depends(current_user),
    store: MetadataStore = Depends(get_store),
    gateway: Any = Depends(get_model_gateway),
) -> dict[str, object]:
    require_case_permission(
        store=store,
        user=user,
        case_id=case_id,
        permission="edit",
        hide_forbidden=False,
    )
    input_paths = list(payload.input_paths)
    for file_id in payload.input_file_ids:
        upload = _require_upload_for_case(store, case_id, file_id)
        input_paths.append(_upload_path_for_analysis(upload))
    if background:
        run = store.create_analysis_run(
            case_id=case_id,
            user_id=user.id,
            config=payload.config,
        )
        task = asyncio.create_task(
            store.run_analysis(
                run_id=run.id,
                user_id=user.id,
                input_paths=input_paths,
                config=payload.config,
                gateway=gateway,
            ),
            name=f"analysis-run-{run.id}",
        )
        _track_background_analysis_task(request, run_id=run.id, task=task)
        return {"analysis_run_id": run.id, "status": run.status}
    try:
        run = await store.start_analysis(
            case_id=case_id,
            user_id=user.id,
            input_paths=input_paths,
            config=payload.config,
            gateway=gateway,
        )
    except ModelCredentialError as exc:
        raise HTTPException(status_code=401, detail=sanitize_error_message(exc)) from exc
    except ModelGatewayError as exc:
        raise HTTPException(status_code=502, detail=sanitize_error_message(exc)) from exc
    return {"analysis_run_id": run.id, "status": run.status}


@router.get("/{case_id}/analysis-runs", response_model=AnalysisRunListResponse)
def list_analysis_runs(
    case_id: str,
    user: UserRecord = Depends(current_user),
    store: MetadataStore = Depends(get_store),
) -> AnalysisRunListResponse:
    require_case_permission(
        store=store,
        user=user,
        case_id=case_id,
        permission="view",
        hide_forbidden=True,
    )
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
    require_case_permission(
        store=store,
        user=user,
        case_id=case_id,
        permission="view",
        hide_forbidden=True,
    )
    run = store.get_analysis_run(run_id)
    if not run or run.case_id != case_id:
        raise HTTPException(status_code=404, detail="analysis run not found")
    return _analysis_run_response(run).model_dump(mode="json")


@router.post("/{case_id}/analysis-runs/{run_id}/cancel", response_model=AnalysisRunResponse)
def cancel_analysis_run(
    request: Request,
    case_id: str,
    run_id: str,
    user: UserRecord = Depends(current_user),
    store: MetadataStore = Depends(get_store),
) -> AnalysisRunResponse:
    require_case_permission(
        store=store,
        user=user,
        case_id=case_id,
        permission="edit",
        hide_forbidden=False,
    )
    run = store.get_analysis_run(run_id)
    if not run or run.case_id != case_id:
        raise HTTPException(status_code=404, detail="analysis run not found")
    try:
        cancelled = store.cancel_analysis_run(run_id=run_id, user_id=user.id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="analysis run not found") from exc
    _cancel_background_analysis_task(request, run_id)
    return _analysis_run_response(cancelled)


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
    require_case_permission(
        store=store,
        user=user,
        case_id=case_id,
        permission="view",
        hide_forbidden=True,
    )
    run = store.get_analysis_run(run_id)
    if not run or run.case_id != case_id:
        raise HTTPException(status_code=404, detail="analysis run not found")
    events = store.list_job_events(case_id=case_id, analysis_run_id=run_id)
    return JobEventListResponse(
        items=[_job_event_response(event) for event in events],
        total=len(events),
    )


@router.get(
    "/{case_id}/analysis-runs/{run_id}/artifacts",
    response_model=AnalysisStepArtifactListResponse,
)
def list_analysis_run_artifacts(
    case_id: str,
    run_id: str,
    user: UserRecord = Depends(current_user),
    store: MetadataStore = Depends(get_store),
) -> AnalysisStepArtifactListResponse:
    require_case_permission(
        store=store,
        user=user,
        case_id=case_id,
        permission="view",
        hide_forbidden=True,
    )
    run = store.get_analysis_run(run_id)
    if not run or run.case_id != case_id:
        raise HTTPException(status_code=404, detail="analysis run not found")
    artifacts = store.list_analysis_step_artifacts(
        case_id=case_id,
        analysis_run_id=run_id,
    )
    return AnalysisStepArtifactListResponse(
        items=[_analysis_step_artifact_response(artifact) for artifact in artifacts],
        total=len(artifacts),
    )
