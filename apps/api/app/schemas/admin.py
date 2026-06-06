from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class AdminUserResponse(BaseModel):
    id: str
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
