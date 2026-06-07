from __future__ import annotations

import csv
import io
import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from app.dependencies import current_user, get_store, require_admin
from app.schemas.admin import (
    AdminAuditLogListResponse,
    AdminAuditLogResponse,
    AdminCaseGroupAccessListResponse,
    AdminCaseGroupAccessRequest,
    AdminCaseGroupAccessResponse,
    AdminPolicyGroupCreateRequest,
    AdminPolicyGroupListResponse,
    AdminPolicyGroupMemberListResponse,
    AdminPolicyGroupMemberRequest,
    AdminPolicyGroupMemberResponse,
    AdminPolicyGroupPatchRequest,
    AdminPolicyGroupResponse,
    AdminSettingsResponse,
    AdminUserListResponse,
    AdminUserPatchRequest,
    AdminUserResponse,
    RetentionRunResponse,
)
from app.store import (
    AuditLogRecord,
    CaseGroupAccessRecord,
    MetadataStore,
    PolicyGroupMemberRecord,
    PolicyGroupRecord,
    UserRecord,
    sanitize_error_message,
)


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
    "message",
    "model_input",
    "password",
    "path",
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
        organization_id=user.organization_id,
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
        sanitized = sanitize_error_message(value, max_length=500)
        lowered = sanitized.lower()
        if (
            "raw prompt" in lowered
            or "raw log" in lowered
            or "log payload" in lowered
            or "password" in lowered
            or "api_key" in lowered
            or "api-key" in lowered
        ):
            return None
        return sanitized
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


def _policy_group_response(
    store: MetadataStore, group: PolicyGroupRecord
) -> AdminPolicyGroupResponse:
    try:
        member_count = len(store.list_policy_group_members(group.id))
    except KeyError:
        member_count = 0
    return AdminPolicyGroupResponse(
        id=group.id,
        organization_id=group.organization_id,
        name=group.name,
        slug=group.slug,
        description=group.description,
        member_count=member_count,
        created_at=group.created_at,
        updated_at=group.updated_at,
    )


def _policy_group_member_response(
    member: PolicyGroupMemberRecord,
) -> AdminPolicyGroupMemberResponse:
    return AdminPolicyGroupMemberResponse(
        id=member.id,
        group_id=member.group_id,
        user_id=member.user_id,
        role=member.role,
        added_by=member.added_by,
        email=member.email,
        username=member.username,
        full_name=member.full_name,
        created_at=member.created_at,
        updated_at=member.updated_at,
    )


def _case_group_access_response(
    access: CaseGroupAccessRecord,
) -> AdminCaseGroupAccessResponse:
    return AdminCaseGroupAccessResponse(
        id=access.id,
        case_id=access.case_id,
        group_id=access.group_id,
        role=access.role,
        granted_by=access.granted_by,
        group_name=access.group_name,
        group_slug=access.group_slug,
        created_at=access.created_at,
        updated_at=access.updated_at,
    )


def _audit_visible_to_admin(
    store: MetadataStore, record: AuditLogRecord, admin: UserRecord
) -> bool:
    metadata_org = record.metadata.get("organization_id") if isinstance(record.metadata, dict) else None
    if isinstance(metadata_org, str) and metadata_org != admin.organization_id:
        return False
    if record.case_id:
        case = store.get_case(record.case_id)
        return case is not None and case.organization_id == admin.organization_id
    if record.user_id:
        user = store.get_user(record.user_id)
        return user is not None and user.organization_id == admin.organization_id
    return True


def _audit_export_rows(records: list[AuditLogRecord]) -> list[dict[str, Any]]:
    return [
        _audit_response(record).model_dump(mode="json")
        for record in records
    ]


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
    items, total = store.list_users(
        q=q,
        role=role,
        is_active=active,
        organization_id=user.organization_id,
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
    if updated.organization_id != admin.organization_id:
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


@router.get("/policy-groups", response_model=AdminPolicyGroupListResponse)
def list_policy_groups(
    user: UserRecord = Depends(_admin_user),
    store: MetadataStore = Depends(get_store),
) -> AdminPolicyGroupListResponse:
    groups = store.list_policy_groups(organization_id=user.organization_id)
    return AdminPolicyGroupListResponse(
        items=[_policy_group_response(store, group) for group in groups],
        total=len(groups),
    )


@router.post("/policy-groups", response_model=AdminPolicyGroupResponse)
def create_policy_group(
    payload: AdminPolicyGroupCreateRequest,
    user: UserRecord = Depends(_admin_user),
    store: MetadataStore = Depends(get_store),
) -> AdminPolicyGroupResponse:
    try:
        group = store.create_policy_group(
            organization_id=user.organization_id,
            name=payload.name,
            slug=payload.slug,
            description=payload.description,
            created_by=user.id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _policy_group_response(store, group)


@router.patch("/policy-groups/{group_id}", response_model=AdminPolicyGroupResponse)
def update_policy_group(
    group_id: str,
    payload: AdminPolicyGroupPatchRequest,
    user: UserRecord = Depends(_admin_user),
    store: MetadataStore = Depends(get_store),
) -> AdminPolicyGroupResponse:
    group = store.get_policy_group(group_id)
    if group is None or group.organization_id != user.organization_id:
        raise HTTPException(status_code=404, detail="policy group not found")
    try:
        updated = store.update_policy_group(
            group_id=group_id,
            name=payload.name,
            slug=payload.slug,
            description=payload.description,
            updated_by=user.id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _policy_group_response(store, updated)


@router.get(
    "/policy-groups/{group_id}/members",
    response_model=AdminPolicyGroupMemberListResponse,
)
def list_policy_group_members(
    group_id: str,
    user: UserRecord = Depends(_admin_user),
    store: MetadataStore = Depends(get_store),
) -> AdminPolicyGroupMemberListResponse:
    group = store.get_policy_group(group_id)
    if group is None or group.organization_id != user.organization_id:
        raise HTTPException(status_code=404, detail="policy group not found")
    members = store.list_policy_group_members(group_id)
    return AdminPolicyGroupMemberListResponse(
        items=[_policy_group_member_response(member) for member in members],
        total=len(members),
    )


@router.post(
    "/policy-groups/{group_id}/members",
    response_model=AdminPolicyGroupMemberResponse,
)
def upsert_policy_group_member(
    group_id: str,
    payload: AdminPolicyGroupMemberRequest,
    user: UserRecord = Depends(_admin_user),
    store: MetadataStore = Depends(get_store),
) -> AdminPolicyGroupMemberResponse:
    group = store.get_policy_group(group_id)
    member_user = store.get_user(payload.user_id)
    if group is None or group.organization_id != user.organization_id:
        raise HTTPException(status_code=404, detail="policy group not found")
    if member_user is None or member_user.organization_id != user.organization_id:
        raise HTTPException(status_code=404, detail="user not found")
    try:
        member = store.upsert_policy_group_member(
            group_id=group_id,
            user_id=payload.user_id,
            role=payload.role,
            added_by=user.id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _policy_group_member_response(member)


@router.delete("/policy-groups/{group_id}/members/{user_id}")
def remove_policy_group_member(
    group_id: str,
    user_id: str,
    user: UserRecord = Depends(_admin_user),
    store: MetadataStore = Depends(get_store),
) -> dict[str, object]:
    group = store.get_policy_group(group_id)
    if group is None or group.organization_id != user.organization_id:
        raise HTTPException(status_code=404, detail="policy group not found")
    removed = store.remove_policy_group_member(
        group_id=group_id,
        user_id=user_id,
        removed_by=user.id,
    )
    return {"status": "removed" if removed else "not_found", "removed": removed}


@router.get(
    "/cases/{case_id}/policy-groups",
    response_model=AdminCaseGroupAccessListResponse,
)
def list_case_policy_groups(
    case_id: str,
    user: UserRecord = Depends(_admin_user),
    store: MetadataStore = Depends(get_store),
) -> AdminCaseGroupAccessListResponse:
    case = store.get_case(case_id)
    if case is None or case.organization_id != user.organization_id:
        raise HTTPException(status_code=404, detail="case not found")
    access = store.list_case_group_access(case_id)
    return AdminCaseGroupAccessListResponse(
        items=[_case_group_access_response(item) for item in access],
        total=len(access),
    )


@router.post(
    "/cases/{case_id}/policy-groups",
    response_model=AdminCaseGroupAccessResponse,
)
def upsert_case_policy_group(
    case_id: str,
    payload: AdminCaseGroupAccessRequest,
    user: UserRecord = Depends(_admin_user),
    store: MetadataStore = Depends(get_store),
) -> AdminCaseGroupAccessResponse:
    case = store.get_case(case_id)
    group = store.get_policy_group(payload.group_id)
    if case is None or case.organization_id != user.organization_id:
        raise HTTPException(status_code=404, detail="case not found")
    if group is None or group.organization_id != user.organization_id:
        raise HTTPException(status_code=404, detail="policy group not found")
    try:
        access = store.upsert_case_group_access(
            case_id=case_id,
            group_id=payload.group_id,
            role=payload.role,
            granted_by=user.id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _case_group_access_response(access)


@router.delete("/cases/{case_id}/policy-groups/{group_id}")
def remove_case_policy_group(
    case_id: str,
    group_id: str,
    user: UserRecord = Depends(_admin_user),
    store: MetadataStore = Depends(get_store),
) -> dict[str, object]:
    case = store.get_case(case_id)
    if case is None or case.organization_id != user.organization_id:
        raise HTTPException(status_code=404, detail="case not found")
    removed = store.remove_case_group_access(
        case_id=case_id,
        group_id=group_id,
        removed_by=user.id,
    )
    return {"status": "removed" if removed else "not_found", "removed": removed}


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
    all_items = store.list_audit_logs(
        case_id=case_id,
        action=action,
        user_id=user_id,
    )
    all_items = [
        item for item in all_items if _audit_visible_to_admin(store, item, user)
    ]
    all_items = sorted(all_items, key=lambda item: (item.created_at, item.id), reverse=True)
    items = all_items[offset : offset + limit]
    return AdminAuditLogListResponse(
        items=[_audit_response(item) for item in items],
        total=len(all_items),
        offset=offset,
        limit=limit,
    )


@router.get("/audit-logs/export")
def export_audit_logs(
    format: str = Query("json", pattern="^(json|ndjson|csv)$"),
    case_id: str | None = None,
    action: str | None = None,
    user_id: str | None = None,
    limit: int = Query(1000, ge=1, le=10000),
    offset: int = Query(0, ge=0),
    user: UserRecord = Depends(_admin_user),
    store: MetadataStore = Depends(get_store),
) -> Response:
    all_items = store.list_audit_logs(
        case_id=case_id,
        action=action,
        user_id=user_id,
    )
    all_items = [
        item for item in all_items if _audit_visible_to_admin(store, item, user)
    ]
    all_items = sorted(all_items, key=lambda item: (item.created_at, item.id), reverse=True)
    rows = _audit_export_rows(all_items[offset : offset + limit])
    store.record_audit(
        action="admin.audit.export",
        user_id=user.id,
        target_type="audit_logs",
        metadata={
            "format": format,
            "count": len(rows),
            "case_id": case_id,
            "action": action,
            "exported_user_id": user_id,
            "organization_id": user.organization_id,
        },
    )
    if format == "ndjson":
        body = "\n".join(json.dumps(row, sort_keys=True) for row in rows)
        if body:
            body += "\n"
        return Response(
            content=body,
            media_type="application/x-ndjson",
            headers={"content-disposition": "attachment; filename=logan-audit.ndjson"},
        )
    if format == "csv":
        buffer = io.StringIO()
        fieldnames = [
            "id",
            "created_at",
            "action",
            "user_id",
            "case_id",
            "target_type",
            "target_id",
            "metadata",
        ]
        writer = csv.DictWriter(buffer, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    **{key: row.get(key) for key in fieldnames if key != "metadata"},
                    "metadata": json.dumps(row.get("metadata") or {}, sort_keys=True),
                }
            )
        return Response(
            content=buffer.getvalue(),
            media_type="text/csv",
            headers={"content-disposition": "attachment; filename=logan-audit.csv"},
        )
    return Response(
        content=json.dumps(rows, indent=2, sort_keys=True),
        media_type="application/json",
        headers={"content-disposition": "attachment; filename=logan-audit.json"},
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
