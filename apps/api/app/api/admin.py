from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from app.dependencies import current_user, get_store, require_admin
from app.schemas.admin import (
    AdminAuditLogListResponse,
    AdminAuditLogResponse,
    AdminSettingsResponse,
    AdminUserListResponse,
    AdminUserPatchRequest,
    AdminUserResponse,
    RetentionRunResponse,
)
from app.store import AuditLogRecord, MetadataStore, UserRecord


router = APIRouter(prefix="/api/admin", tags=["admin"])

_SENSITIVE_AUDIT_METADATA_PARTS = {
    "access_key",
    "api_key",
    "authorization",
    "content",
    "credential",
    "database_url",
    "file_path",
    "filepath",
    "input_path",
    "log_content",
    "model_input",
    "password",
    "prompt",
    "raw",
    "representative_line",
    "secret",
    "source_token",
    "token",
}
_SAFE_AUDIT_METADATA_KEYS = {
    "analysis_run_id",
    "annotation_count",
    "model_input_count",
    "model_name",
    "model_provider",
    "model_reasoning_effort",
    "prompt_version",
    "redacted",
    "representative_sample_count",
    "template_count",
}


def _admin_user(user: UserRecord = Depends(current_user)) -> UserRecord:
    return require_admin(user)


def _admin_user_response(store: MetadataStore, user: UserRecord) -> AdminUserResponse:
    return AdminUserResponse(
        id=user.id,
        email=user.email,
        username=user.username,
        full_name=user.full_name,
        role=user.role,
        is_active=user.is_active,
        has_copilot_credential=store.has_credential(user.id),
        created_at=user.created_at,
    )


def _safe_audit_metadata(value: Any) -> Any:
    if value is None or isinstance(value, bool | int | float):
        return value
    if isinstance(value, str):
        return value[:500]
    if isinstance(value, list):
        return [
            item
            for item in (_safe_audit_metadata(item) for item in value[:50])
            if item is not None
        ]
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            lowered = key_text.lower()
            if (
                lowered not in _SAFE_AUDIT_METADATA_KEYS
                and any(part in lowered for part in _SENSITIVE_AUDIT_METADATA_PARTS)
            ):
                continue
            sanitized_item = _safe_audit_metadata(item)
            if sanitized_item is not None:
                sanitized[key_text] = sanitized_item
        return sanitized
    return None


def _audit_response(record: AuditLogRecord) -> AdminAuditLogResponse:
    return AdminAuditLogResponse(
        id=record.id,
        action=record.action,
        user_id=record.user_id,
        target_type=record.target_type,
        target_id=record.target_id,
        case_id=record.case_id,
        metadata=_safe_audit_metadata(record.metadata),
        created_at=record.created_at,
    )


def _store_backend_name(store: MetadataStore) -> str:
    name = store.__class__.__name__.lower()
    return "sqlalchemy" if "sqlalchemy" in name else "memory"


@router.get("/users", response_model=AdminUserListResponse)
def list_users(
    q: str | None = None,
    role: str | None = None,
    active: bool | None = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user: UserRecord = Depends(_admin_user),
    store: MetadataStore = Depends(get_store),
) -> AdminUserListResponse:
    del user
    items, total = store.list_users(
        q=q,
        role=role,
        is_active=active,
        offset=offset,
        limit=limit,
    )
    return AdminUserListResponse(
        items=[_admin_user_response(store, item) for item in items],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.patch("/users/{user_id}", response_model=AdminUserResponse)
def update_user(
    user_id: str,
    payload: AdminUserPatchRequest,
    admin: UserRecord = Depends(_admin_user),
    store: MetadataStore = Depends(get_store),
) -> AdminUserResponse:
    if not payload.model_fields_set:
        raise HTTPException(status_code=400, detail="no user fields provided")
    updated = store.get_user(user_id)
    if updated is None:
        raise HTTPException(status_code=404, detail="user not found")
    if "role" in payload.model_fields_set:
        if payload.role is None:
            raise HTTPException(status_code=400, detail="role cannot be null")
        try:
            updated = store.update_user_role(
                user_id=user_id,
                role=payload.role,
                updated_by=admin.id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    if "is_active" in payload.model_fields_set:
        if payload.is_active is None:
            raise HTTPException(status_code=400, detail="is_active cannot be null")
        updated = store.set_user_active(
            user_id=user_id,
            is_active=payload.is_active,
            updated_by=admin.id,
        )
    return _admin_user_response(store, updated)


@router.get("/audit-logs", response_model=AdminAuditLogListResponse)
def list_audit_logs(
    case_id: str | None = None,
    action: str | None = None,
    user_id: str | None = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user: UserRecord = Depends(_admin_user),
    store: MetadataStore = Depends(get_store),
) -> AdminAuditLogListResponse:
    del user
    all_items = store.list_audit_logs(
        case_id=case_id,
        action=action,
        user_id=user_id,
    )
    all_items = sorted(all_items, key=lambda item: (item.created_at, item.id), reverse=True)
    items = all_items[offset : offset + limit]
    return AdminAuditLogListResponse(
        items=[_audit_response(item) for item in items],
        total=len(all_items),
        offset=offset,
        limit=limit,
    )


@router.get("/settings", response_model=AdminSettingsResponse)
def settings_summary(
    user: UserRecord = Depends(_admin_user),
    store: MetadataStore = Depends(get_store),
) -> AdminSettingsResponse:
    del user
    app_settings = store.settings
    return AdminSettingsResponse(
        env=app_settings.env,
        store_backend=_store_backend_name(store),
        configured_store_backend=app_settings.store_backend,
        object_backend=app_settings.object_store_backend,
        orchestrator=app_settings.analysis_orchestrator,
        retention_days={
            "audit": app_settings.audit_retention_days,
            "raw_log": app_settings.raw_log_retention_days,
            "report": app_settings.report_retention_days,
        },
        rate_limit={
            "enabled": app_settings.rate_limit_enabled,
            "requests_per_minute": app_settings.rate_limit_requests_per_minute,
        },
        analytics={
            "sinks_enabled": app_settings.analytics_sinks_enabled,
            "external_queries_enabled": app_settings.external_analytics_queries_enabled,
            "sink_failure_mode": app_settings.analytics_sink_failure_mode,
        },
    )


@router.post("/retention/run", response_model=RetentionRunResponse)
def run_retention(
    user: UserRecord = Depends(_admin_user),
    store: MetadataStore = Depends(get_store),
) -> RetentionRunResponse:
    result = store.run_retention()
    payload = {
        "audit_logs_deleted": result.audit_logs_deleted,
        "raw_log_lines_scrubbed": result.raw_log_lines_scrubbed,
        "exports_deleted": result.exports_deleted,
        "analysis_results_cleared": result.analysis_results_cleared,
        "step_artifacts_deleted": result.step_artifacts_deleted,
    }
    store.record_audit(
        action="admin.retention.run",
        user_id=user.id,
        target_type="retention",
        metadata=payload,
    )
    return RetentionRunResponse(**payload)
