from __future__ import annotations

import asyncio
import hashlib
import logging
import traceback
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.dependencies import current_user, get_model_gateway, get_store, require_case_owner
from app.schemas.case import (
    AnalysisRunListResponse,
    AnalysisRunRequest,
    AnalysisRunResponse,
    CaseCreateRequest,
    CaseResponse,
    CaseUpdateRequest,
    UploadContentResponse,
    UploadRequest,
    UploadStartResponse,
)
from app.services.object_store import file_uri_to_path
from app.store import Store, UserRecord

router = APIRouter(prefix="/api/cases", tags=["cases"])
logger = logging.getLogger("logan.analysis")


def _format_byte_limit(max_bytes: int) -> str:
    mib = 1024 * 1024
    if max_bytes % mib == 0:
        return f"{max_bytes // mib} MiB"
    return f"{max_bytes} bytes"


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
    progress = record.progress or {}
    return AnalysisRunResponse(
        analysis_run_id=record.id,
        run_number=record.run_number,
        status=record.status,
        current_step=str(
            progress.get("current_step")
            or ("completed" if record.status == "completed" else record.status)
        ),
        progress=progress,
        started_at=record.started_at,
        completed_at=record.completed_at,
        error_message=record.error_message,
        model_provider=record.model_provider,
        model_name=record.model_name,
    )


def _upload_for_case(store: Store, case_id: str, file_id: str):
    upload = store.get_upload(file_id)
    if upload is None or upload.case_id != case_id:
        raise HTTPException(status_code=404, detail="upload not found")
    return upload


def _upload_path(upload: Any) -> str:
    if not upload.completed:
        raise HTTPException(status_code=400, detail=f"upload {upload.id} is not completed")
    path = file_uri_to_path(upload.object_uri)
    if not path.is_file():
        raise HTTPException(status_code=400, detail=f"upload {upload.id} content is missing")
    return str(path)


def _tasks(request: Request) -> dict[str, asyncio.Task[Any]]:
    tasks = getattr(request.app.state, "analysis_tasks", None)
    if not isinstance(tasks, dict):
        tasks = {}
        request.app.state.analysis_tasks = tasks
    return tasks


def _safe_exception_diagnostics(error: BaseException) -> str:
    diagnostics = [f"error_type={type(error).__name__}"]
    error_number = getattr(error, "errno", None)
    if isinstance(error_number, int):
        diagnostics.append(f"errno={error_number}")
    windows_error = getattr(error, "winerror", None)
    if isinstance(windows_error, int):
        diagnostics.append(f"winerror={windows_error}")
    frames = traceback.extract_tb(error.__traceback__, limit=12)
    if frames:
        diagnostics.append(
            "trace=" + ">".join(f"{frame.name}:{frame.lineno}" for frame in frames)
        )
    return " ".join(diagnostics)


def _track_task(request: Request, run_id: str, task: asyncio.Task[Any]) -> None:
    tasks = _tasks(request)
    tasks[run_id] = task

    def done(completed: asyncio.Task[Any]) -> None:
        tasks.pop(run_id, None)
        if completed.cancelled():
            return
        try:
            completed.result()
        except Exception as exc:
            logger.error(
                "analysis failed run_id=%s %s",
                run_id,
                _safe_exception_diagnostics(exc),
                extra={"analysis_run_id": run_id},
            )

    task.add_done_callback(done)


@router.post("", response_model=CaseResponse)
def create_case(
    payload: CaseCreateRequest,
    user: UserRecord = Depends(current_user),
    store: Store = Depends(get_store),
) -> CaseResponse:
    return _case_response(store.create_case(user_id=user.id, data=payload.model_dump()))


@router.get("")
def list_cases(
    status: str | None = None,
    product: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    user: UserRecord = Depends(current_user),
    store: Store = Depends(get_store),
) -> dict[str, object]:
    items, total = store.list_cases_for_user(
        user,
        status=status,
        product=product,
        offset=(page - 1) * page_size,
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
    store: Store = Depends(get_store),
) -> CaseResponse:
    return _case_response(
        require_case_owner(
            store=store,
            user=user,
            case_id=case_id,
        )
    )


@router.patch("/{case_id}", response_model=CaseResponse)
def update_case(
    case_id: str,
    payload: CaseUpdateRequest,
    user: UserRecord = Depends(current_user),
    store: Store = Depends(get_store),
) -> CaseResponse:
    require_case_owner(
        store=store,
        user=user,
        case_id=case_id,
    )
    data = payload.model_dump(exclude_unset=True)
    if data.get("title") is None and "title" in data:
        raise HTTPException(status_code=400, detail="title cannot be null")
    return _case_response(store.update_case(case_id=case_id, data=data, user_id=user.id))


@router.delete("/{case_id}")
def delete_case(
    request: Request,
    case_id: str,
    user: UserRecord = Depends(current_user),
    store: Store = Depends(get_store),
) -> dict[str, bool]:
    require_case_owner(
        store=store,
        user=user,
        case_id=case_id,
    )
    for run in store.list_analysis_runs(case_id):
        task = _tasks(request).get(run.id)
        if task and not task.done():
            task.cancel()
    if not store.delete_case(case_id=case_id, user_id=user.id):
        raise HTTPException(status_code=404, detail="case not found")
    return {"deleted": True}


@router.post("/{case_id}/uploads", response_model=UploadStartResponse)
def request_upload(
    case_id: str,
    payload: UploadRequest,
    user: UserRecord = Depends(current_user),
    store: Store = Depends(get_store),
) -> UploadStartResponse:
    require_case_owner(
        store=store,
        user=user,
        case_id=case_id,
    )
    if payload.size_bytes > store.settings.max_upload_bytes:
        raise HTTPException(
            status_code=413,
            detail=(
                "upload exceeds the configured "
                f"{_format_byte_limit(store.settings.max_upload_bytes)} limit"
            ),
        )
    upload = store.create_upload(
        case_id=case_id,
        filename=payload.filename,
        content_type=payload.content_type,
        size_bytes=payload.size_bytes,
    )
    return UploadStartResponse(
        file_id=upload.id,
        upload_url=f"/api/cases/{case_id}/uploads/{upload.id}/content",
    )


@router.put(
    "/{case_id}/uploads/{file_id}/content",
    name="upload_content",
    response_model=UploadContentResponse,
)
async def upload_content(
    request: Request,
    case_id: str,
    file_id: str,
    user: UserRecord = Depends(current_user),
    store: Store = Depends(get_store),
) -> UploadContentResponse:
    require_case_owner(
        store=store,
        user=user,
        case_id=case_id,
    )
    upload = _upload_for_case(store, case_id, file_id)
    max_upload_bytes = store.settings.max_upload_bytes
    target_path = file_uri_to_path(upload.object_uri)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = target_path.with_name(
        f".{target_path.name}.{uuid.uuid4().hex}.part"
    )
    digest = hashlib.sha256()
    received_bytes = 0
    try:
        with temporary_path.open("wb") as handle:
            async for chunk in request.stream():
                received_bytes += len(chunk)
                if received_bytes > max_upload_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=(
                            "upload exceeds the configured "
                            f"{_format_byte_limit(max_upload_bytes)} limit"
                        ),
                    )
                handle.write(chunk)
                digest.update(chunk)
        if upload.size_bytes != received_bytes:
            raise HTTPException(
                status_code=400,
                detail="upload size does not match request",
            )
        sha256 = digest.hexdigest()
        if upload.completed and upload.sha256 != sha256:
            raise HTTPException(
                status_code=409,
                detail="upload content does not match",
            )
        temporary_path.replace(target_path)
    except (Exception, asyncio.CancelledError):
        temporary_path.unlink(missing_ok=True)
        raise

    completed = store.complete_upload(upload_id=file_id, sha256=sha256)
    return UploadContentResponse(
        file_id=completed.id,
        status="completed",
        sha256=sha256,
        size_bytes=received_bytes,
    )


@router.post("/{case_id}/analysis-runs", response_model=AnalysisRunResponse)
async def start_analysis(
    request: Request,
    case_id: str,
    payload: AnalysisRunRequest,
    user: UserRecord = Depends(current_user),
    store: Store = Depends(get_store),
    gateway: Any = Depends(get_model_gateway),
) -> AnalysisRunResponse:
    require_case_owner(
        store=store,
        user=user,
        case_id=case_id,
    )
    file_paths = [
        _upload_path(_upload_for_case(store, case_id, file_id))
        for file_id in payload.input_file_ids
    ]
    run = store.create_analysis_run(
        case_id=case_id,
        user_id=user.id,
    )
    task = asyncio.create_task(
        store.run_analysis(
            run_id=run.id,
            user_id=user.id,
            file_paths=file_paths,
            gateway=gateway,
        ),
        name=f"analysis-run-{run.id}",
    )
    _track_task(request, run.id, task)
    return _analysis_run_response(run)


@router.get("/{case_id}/analysis-runs", response_model=AnalysisRunListResponse)
def list_analysis_runs(
    case_id: str,
    user: UserRecord = Depends(current_user),
    store: Store = Depends(get_store),
) -> AnalysisRunListResponse:
    require_case_owner(
        store=store,
        user=user,
        case_id=case_id,
    )
    runs = store.list_analysis_runs(case_id)
    return AnalysisRunListResponse(
        items=[_analysis_run_response(run) for run in runs],
        total=len(runs),
    )


@router.get("/{case_id}/analysis-runs/{run_id}", response_model=AnalysisRunResponse)
def get_analysis_run(
    case_id: str,
    run_id: str,
    user: UserRecord = Depends(current_user),
    store: Store = Depends(get_store),
) -> AnalysisRunResponse:
    require_case_owner(
        store=store,
        user=user,
        case_id=case_id,
    )
    run = store.get_analysis_run(run_id)
    if run is None or run.case_id != case_id:
        raise HTTPException(status_code=404, detail="analysis run not found")
    return _analysis_run_response(run)


@router.post(
    "/{case_id}/analysis-runs/{run_id}/cancel",
    response_model=AnalysisRunResponse,
)
def cancel_analysis_run(
    request: Request,
    case_id: str,
    run_id: str,
    user: UserRecord = Depends(current_user),
    store: Store = Depends(get_store),
) -> AnalysisRunResponse:
    require_case_owner(
        store=store,
        user=user,
        case_id=case_id,
    )
    run = store.get_analysis_run(run_id)
    if run is None or run.case_id != case_id:
        raise HTTPException(status_code=404, detail="analysis run not found")
    cancelled = store.cancel_analysis_run(run_id=run_id, user_id=user.id)
    task = _tasks(request).get(run_id)
    if task and not task.done():
        task.cancel()
    return _analysis_run_response(cancelled)
