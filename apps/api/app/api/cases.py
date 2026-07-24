from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
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
    CompletedMultipartUploadPart,
    ObjectStoreConfigurationError,
    ObjectStoreError,
    abort_multipart_upload,
    complete_multipart_upload,
    create_multipart_part_urls,
    create_multipart_upload,
    create_multipart_upload_plan,
    create_presigned_upload,
    digest_bytes,
    file_uri_to_path,
    is_local_backend,
    is_s3_backend,
    list_multipart_parts,
    object_store_backend,
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


def _upload_metadata(upload: Any) -> dict[str, Any]:
    metadata = getattr(upload, "upload_metadata", {}) or {}
    return dict(metadata) if isinstance(metadata, dict) else {}


def _multipart_upload_metadata(
    *,
    multipart_upload_id: str,
    part_size_bytes: int,
    part_count: int,
) -> dict[str, Any]:
    return {
        "upload_mode": "multipart",
        "multipart_upload_id": multipart_upload_id,
        "part_size_bytes": part_size_bytes,
        "part_count": part_count,
    }


def _part_url_response(part: Any) -> dict[str, object]:
    return {
        "part_number": part.part_number,
        "upload_url": part.upload_url,
        "upload_headers": part.upload_headers,
    }


def _uploaded_part_response(part: Any) -> dict[str, object]:
    return {
        "part_number": part.part_number,
        "etag": part.etag,
        "size_bytes": part.size_bytes,
    }


def _multipart_response(
    upload: Any,
    *,
    backend: str,
    metadata: dict[str, Any],
    parts: list[Any],
    expires_in: int,
    uploaded_parts: list[Any] | None = None,
) -> dict[str, object]:
    return {
        "file_id": upload.id,
        "upload_backend": backend,
        "upload_mode": "multipart",
        "multipart_upload_id": str(metadata["multipart_upload_id"]),
        "part_size_bytes": int(metadata["part_size_bytes"]),
        "part_count": int(metadata["part_count"]),
        "parts": [_part_url_response(part) for part in parts],
        "uploaded_parts": [
            _uploaded_part_response(part) for part in (uploaded_parts or [])
        ],
        "expires_in": expires_in,
    }


def _require_multipart_upload_for_case(
    store: MetadataStore,
    case_id: str,
    file_id: str,
    *,
    allow_aborted: bool = False,
) -> tuple[Any, dict[str, Any]]:
    upload = _require_upload_for_case(store, case_id, file_id)
    metadata = _upload_metadata(upload)
    if not upload.object_uri.startswith("s3://") or metadata.get("upload_mode") != "multipart":
        raise HTTPException(status_code=400, detail="upload is not an S3 multipart upload")
    if upload.completed:
        raise HTTPException(status_code=400, detail="multipart upload is already completed")
    if metadata.get("aborted_at") and not allow_aborted:
        raise HTTPException(status_code=400, detail="multipart upload has been aborted")
    multipart_upload_id = metadata.get("multipart_upload_id")
    part_size_bytes = metadata.get("part_size_bytes")
    part_count = metadata.get("part_count")
    if (
        not isinstance(multipart_upload_id, str)
        or not multipart_upload_id
        or not isinstance(part_size_bytes, int)
        or isinstance(part_size_bytes, bool)
        or not isinstance(part_count, int)
        or isinstance(part_count, bool)
        or part_size_bytes <= 0
        or part_count <= 0
    ):
        raise HTTPException(status_code=400, detail="multipart upload metadata is incomplete")
    return upload, metadata


def _normalize_complete_parts(
    payload: UploadCompleteRequest,
    *,
    part_count: int,
) -> list[CompletedMultipartUploadPart]:
    if not payload.parts:
        raise HTTPException(status_code=400, detail="multipart completion requires parts")
    etags_by_part: dict[int, str] = {}
    for part in payload.parts:
        if part.part_number < 1 or part.part_number > part_count:
            raise HTTPException(
                status_code=400,
                detail=f"multipart part_number must be between 1 and {part_count}",
            )
        if part.part_number in etags_by_part:
            raise HTTPException(
                status_code=400,
                detail=f"duplicate multipart part_number {part.part_number}",
            )
        etags_by_part[part.part_number] = part.etag
    if len(etags_by_part) != part_count:
        raise HTTPException(
            status_code=400,
            detail=f"multipart completion requires all {part_count} parts",
        )
    return [
        CompletedMultipartUploadPart(part_number=part_number, etag=etag)
        for part_number, etag in sorted(etags_by_part.items())
    ]


def _upload_path_for_analysis(upload: Any) -> str:
    if not upload.completed:
        raise HTTPException(status_code=400, detail=f"upload {upload.id} is not completed")
    if upload.object_uri.startswith("s3://"):
        return upload.object_uri
    try:
        path = file_uri_to_path(upload.object_uri)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"upload {upload.id} is not file-backed or S3-backed",
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
    request: Request,
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
        upload_url = f"/api/cases/{case_id}/uploads/{upload.id}/content"
    elif is_s3_backend(store.settings):
        use_multipart = (
            payload.multipart is True
            or payload.size_bytes >= store.settings.s3_multipart_threshold_bytes
        )
        if use_multipart:
            part_size_bytes = (
                payload.part_size_bytes or store.settings.s3_multipart_part_size_bytes
            )
            try:
                plan = create_multipart_upload_plan(
                    size_bytes=payload.size_bytes,
                    part_size_bytes=part_size_bytes,
                    max_parts=store.settings.s3_multipart_max_parts,
                )
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            try:
                multipart_upload_id = create_multipart_upload(
                    upload.object_uri,
                    content_type=payload.content_type,
                    app_settings=store.settings,
                    s3_client_factory=getattr(request.app.state, "s3_client_factory", None),
                )
                metadata = _multipart_upload_metadata(
                    multipart_upload_id=multipart_upload_id,
                    part_size_bytes=plan.part_size_bytes,
                    part_count=plan.part_count,
                )
                parts = create_multipart_part_urls(
                    upload.object_uri,
                    multipart_upload_id=multipart_upload_id,
                    part_count=plan.part_count,
                    app_settings=store.settings,
                    s3_client_factory=getattr(request.app.state, "s3_client_factory", None),
                )
            except ObjectStoreConfigurationError as exc:
                raise HTTPException(status_code=500, detail=str(exc)) from exc
            except ObjectStoreError as exc:
                raise HTTPException(status_code=502, detail=str(exc)) from exc
            upload = store.update_upload_metadata(upload_id=upload.id, metadata=metadata)
            return _multipart_response(
                upload,
                backend=backend,
                metadata=metadata,
                parts=parts,
                expires_in=store.settings.s3_presign_expires_seconds,
            )
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
        upload = store.update_upload_metadata(
            upload_id=upload.id,
            metadata={"upload_mode": "single"},
        )
    else:
        upload_url = upload.object_uri
    response: dict[str, object] = {
        "file_id": upload.id,
        "upload_url": upload_url,
        "object_uri": object_uri,
        "upload_backend": backend,
        "upload_headers": upload_headers,
        "expires_in": expires_in,
    }
    if is_s3_backend(store.settings):
        response["upload_mode"] = "single"
    return response


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


@router.get("/{case_id}/uploads/{file_id}/multipart")
def refresh_multipart_upload(
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
    upload_record, metadata = _require_multipart_upload_for_case(store, case_id, file_id)
    try:
        parts = create_multipart_part_urls(
            upload_record.object_uri,
            multipart_upload_id=str(metadata["multipart_upload_id"]),
            part_count=int(metadata["part_count"]),
            app_settings=store.settings,
            s3_client_factory=getattr(request.app.state, "s3_client_factory", None),
        )
        uploaded_parts = list_multipart_parts(
            upload_record.object_uri,
            multipart_upload_id=str(metadata["multipart_upload_id"]),
            app_settings=store.settings,
            s3_client_factory=getattr(request.app.state, "s3_client_factory", None),
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail="multipart upload is not active") from exc
    except ObjectStoreConfigurationError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except ObjectStoreError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return _multipart_response(
        upload_record,
        backend=object_store_backend(store.settings),
        metadata=metadata,
        parts=parts,
        uploaded_parts=uploaded_parts,
        expires_in=store.settings.s3_presign_expires_seconds,
    )


@router.delete("/{case_id}/uploads/{file_id}/multipart")
def abort_case_multipart_upload(
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
    upload_record, metadata = _require_multipart_upload_for_case(
        store, case_id, file_id, allow_aborted=True
    )
    aborted_at = metadata.get("aborted_at")
    if not aborted_at:
        try:
            abort_multipart_upload(
                upload_record.object_uri,
                multipart_upload_id=str(metadata["multipart_upload_id"]),
                app_settings=store.settings,
                s3_client_factory=getattr(request.app.state, "s3_client_factory", None),
            )
        except ObjectStoreConfigurationError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        except ObjectStoreError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        aborted_at = datetime.now(UTC).isoformat()
        metadata = dict(metadata)
        metadata["aborted_at"] = aborted_at
        upload_record = store.update_upload_metadata(
            upload_id=upload_record.id,
            metadata=metadata,
        )
    return {
        "file_id": upload_record.id,
        "status": "aborted",
        "upload_backend": object_store_backend(store.settings),
        "upload_mode": "multipart",
        "aborted_at": str(aborted_at),
    }


@router.post("/{case_id}/uploads/{file_id}/complete")
def complete_upload(
    request: Request,
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
    metadata = _upload_metadata(upload_record)
    if metadata.get("upload_mode") == "multipart":
        upload_record, metadata = _require_multipart_upload_for_case(store, case_id, file_id)
        expected_upload_id = str(metadata["multipart_upload_id"])
        if payload.multipart_upload_id != expected_upload_id:
            raise HTTPException(status_code=400, detail="multipart_upload_id does not match")
        complete_parts = _normalize_complete_parts(
            payload,
            part_count=int(metadata["part_count"]),
        )
        try:
            complete_multipart_upload(
                upload_record.object_uri,
                multipart_upload_id=expected_upload_id,
                parts=complete_parts,
                app_settings=store.settings,
                s3_client_factory=getattr(request.app.state, "s3_client_factory", None),
            )
            stored = stat_object(
                upload_record.object_uri,
                app_settings=store.settings,
                s3_client_factory=getattr(request.app.state, "s3_client_factory", None),
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=400, detail="upload content has not been uploaded") from exc
        except ObjectStoreConfigurationError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        except ObjectStoreError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        if upload_record.size_bytes != stored.size_bytes:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"upload size mismatch: expected {upload_record.size_bytes} bytes, "
                    f"found {stored.size_bytes} bytes"
                ),
            )
        upload = store.complete_upload(upload_id=file_id, sha256=payload.sha256)
        return _completed_upload_response(upload)
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
                s3_client_factory=getattr(request.app.state, "s3_client_factory", None),
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
            s3_client_factory=getattr(request.app.state, "s3_client_factory", None),
        )
    except ModelCredentialError as exc:
        raise HTTPException(status_code=401, detail=sanitize_error_message(exc)) from exc
    except ModelGatewayError as exc:
        raise HTTPException(status_code=502, detail=sanitize_error_message(exc)) from exc
    except ObjectStoreConfigurationError as exc:
        raise HTTPException(status_code=500, detail=sanitize_error_message(exc)) from exc
    except ObjectStoreError as exc:
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
