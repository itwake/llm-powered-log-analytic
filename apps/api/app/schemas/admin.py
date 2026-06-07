from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class AdminUserResponse(BaseModel):
    id: str
    organization_id: str
    email: str
    username: str
    full_name: str | None = None
    role: str
    is_active: bool
    has_copilot_credential: bool = False
    created_at: datetime


class AdminUserListResponse(BaseModel):
    items: list[AdminUserResponse]
    total: int
    offset: int
    limit: int


class AdminUserPatchRequest(BaseModel):
    role: str | None = None
    is_active: bool | None = None


class AdminAuditLogResponse(BaseModel):
    id: str
    action: str
    user_id: str | None = None
    target_type: str | None = None
    target_id: str | None = None
    case_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class AdminAuditLogListResponse(BaseModel):
    items: list[AdminAuditLogResponse]
    total: int
    offset: int
    limit: int


class AdminSettingsResponse(BaseModel):
    env: str
    store_backend: str
    configured_store_backend: str
    object_backend: str
    orchestrator: str
    retention_days: dict[str, int]
    rate_limit: dict[str, int | bool]
    analytics: dict[str, str | bool]


class RetentionRunResponse(BaseModel):
    audit_logs_deleted: int = 0
    raw_log_lines_scrubbed: int = 0
    exports_deleted: int = 0
    analysis_results_cleared: int = 0
    step_artifacts_deleted: int = 0


class AdminPolicyGroupCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    slug: str | None = Field(default=None, max_length=120)
    description: str | None = Field(default=None, max_length=500)


class AdminPolicyGroupPatchRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    slug: str | None = Field(default=None, max_length=120)
    description: str | None = Field(default=None, max_length=500)


class AdminPolicyGroupResponse(BaseModel):
    id: str
    organization_id: str
    name: str
    slug: str
    description: str | None = None
    member_count: int = 0
    created_at: datetime
    updated_at: datetime


class AdminPolicyGroupListResponse(BaseModel):
    items: list[AdminPolicyGroupResponse]
    total: int


class AdminPolicyGroupMemberRequest(BaseModel):
    user_id: str
    role: str = "viewer"


class AdminPolicyGroupMemberResponse(BaseModel):
    id: str
    group_id: str
    user_id: str
    role: str
    added_by: str | None = None
    email: str | None = None
    username: str | None = None
    full_name: str | None = None
    created_at: datetime
    updated_at: datetime


class AdminPolicyGroupMemberListResponse(BaseModel):
    items: list[AdminPolicyGroupMemberResponse]
    total: int


class AdminCaseGroupAccessRequest(BaseModel):
    group_id: str
    role: str = "viewer"


class AdminCaseGroupAccessResponse(BaseModel):
    id: str
    case_id: str
    group_id: str
    role: str
    granted_by: str | None = None
    group_name: str | None = None
    group_slug: str | None = None
    created_at: datetime
    updated_at: datetime


class AdminCaseGroupAccessListResponse(BaseModel):
    items: list[AdminCaseGroupAccessResponse]
    total: int
