from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
import re
from typing import Any, Protocol

from logan_workers.activities.export import export_analysis
from logan_workers.models import AnalysisResult
from logan_workers.pipeline import AnalyzeCasePipeline

from app.config import Settings, settings
from app.core.security import (
    default_session_expiry,
    encrypt_token_for_settings,
    hash_password,
    hash_token,
    issue_session_token,
    token_hint,
    verify_password,
)
from app.services.analysis_inputs import (
    analysis_input_backend_counts,
    materialize_analysis_inputs,
)
from app.services.object_store import (
    S3ClientFactory,
    is_local_backend,
    is_s3_backend,
    local_upload_object_uri,
    s3_upload_object_uri,
    safe_filename,
)


GLOBAL_USER_ROLES = frozenset({"admin", "engineer"})
CASE_COLLABORATOR_ROLES = frozenset({"owner", "editor", "viewer"})
POLICY_GROUP_ROLES = CASE_COLLABORATOR_ROLES
CASE_PERMISSION_ROLES: dict[str, frozenset[str]] = {
    "view": frozenset({"owner", "editor", "viewer"}),
    "edit": frozenset({"owner", "editor"}),
    "owner": frozenset({"owner"}),
}
DEFAULT_ORGANIZATION_ID = "default"
DEFAULT_ORGANIZATION_SLUG = "default"
DEFAULT_ORGANIZATION_NAME = "Default Organization"
RAW_LOG_RETAINED_MARKER = "[raw log text scrubbed by retention policy]"
MODEL_INVOCATION_AUDIT_ACTION = "model.invocation"
_JOB_EVENT_LOGGER = logging.getLogger("logan.analysis.progress")


_SENSITIVE_ERROR_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"(?i)(authorization\s*[:=]\s*bearer\s+)[^\s,;]+"),
        r"\1<REDACTED>",
    ),
    (re.compile(r"(?i)(bearer\s+)[^\s,;]+"), r"\1<REDACTED>"),
    (
        re.compile(
            r"(?i)\b(token|api[_-]?key|password|secret|credential|source[_-]?token)"
            r"\s*[:=]\s*[^,\s;]+"
        ),
        r"\1=<REDACTED>",
    ),
    (
        re.compile(r"\b(?:gh[opsru]_[A-Za-z0-9_]{8,}|github_pat_[A-Za-z0-9_]+)\b"),
        "<REDACTED>",
    ),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{10,}\b"), "<REDACTED>"),
    (
        re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
        "<REDACTED>",
    ),
    (
        re.compile(r"(?<![A-Za-z0-9_])/(?:root|home|var|tmp|etc|opt|srv|workspace|Users)(?:/[^\s,;:)]+)+"),
        "<PATH>",
    ),
    (re.compile(r"\b[A-Za-z]:\\(?:[^\\\s,;:]+\\?)+"), "<PATH>"),
    (re.compile(r"\b[A-Za-z0-9_-]{40,}\b"), "<REDACTED>"),
)
_SENSITIVE_METADATA_KEY_PARTS = {
    "authorization",
    "credential",
    "input",
    "message",
    "model",
    "password",
    "prompt",
    "raw_message",
    "raw_text",
    "representative_lines",
    "secret",
    "source_token",
    "template_context",
    "token",
    "path",
}
_SAFE_STRING_LIST_METADATA = {"export_types"}
_SECRET_WORKFLOW_KEY_PARTS = {
    "access_key",
    "api_key",
    "authorization",
    "credential",
    "database_url",
    "log_content",
    "password",
    "raw_log",
    "raw_message",
    "raw_text",
    "secret",
    "source_log",
    "source_token",
    "token",
}
_SENSITIVE_ARTIFACT_KEY_PARTS = {
    "access_key",
    "api_key",
    "authorization",
    "cookie",
    "credential",
    "database_url",
    "db_url",
    "file_path",
    "filepath",
    "full_path",
    "input_path",
    "input_paths",
    "model_input",
    "model_inputs",
    "password",
    "prompt",
    "raw_log",
    "raw_message",
    "raw_text",
    "representative_lines",
    "secret",
    "source_log",
    "source_token",
    "token",
}
_SAFE_ARTIFACT_STRING_KEYS = {
    "artifact_error",
    "artifact_type",
    "content_type",
    "error_code",
    "event_type",
    "manifest_version",
    "sha256",
    "status",
    "storage_backend",
}
_SAFE_ARTIFACT_LIST_STRINGS = {"export_types"}
_SAFE_ARTIFACT_LIST_VALUES = {"html", "json", "markdown"}


def sanitize_error_message(error: object, *, max_length: int = 500) -> str:
    message = str(error)
    for pattern, replacement in _SENSITIVE_ERROR_PATTERNS:
        message = pattern.sub(replacement, message)
    if len(message) > max_length:
        message = f"{message[: max_length - 3]}..."
    return message


def model_invocation_audit_metadata(
    *, run: AnalysisRunRecord | Any, result: AnalysisResult
) -> dict[str, Any]:
    return {
        "analysis_run_id": getattr(run, "id", result.analysis_run_id),
        "model_provider": getattr(run, "model_provider", ""),
        "model_name": getattr(run, "model_name", ""),
        "model_reasoning_effort": getattr(run, "model_reasoning_effort", ""),
        "prompt_version": getattr(run, "prompt_version", "annotation_v1"),
        "representative_sample_count": len(result.samples),
        "model_input_count": len(result.model_inputs),
        "annotation_count": len(result.annotations),
        "template_count": len(result.templates),
        "redacted": True,
    }


def _is_sensitive_metadata_key(key: str) -> bool:
    lowered = key.lower()
    return any(part in lowered for part in _SENSITIVE_METADATA_KEY_PARTS)


def _sanitize_metadata_value(value: Any, *, parent_key: str) -> Any:
    if value is None or isinstance(value, bool | int | float):
        return value
    if isinstance(value, str):
        if parent_key in _SAFE_STRING_LIST_METADATA and value in {"html", "json", "markdown"}:
            return value
        return None
    if isinstance(value, list):
        sanitized_items = [
            _sanitize_metadata_value(item, parent_key=parent_key) for item in value
        ]
        return [item for item in sanitized_items if item is not None]
    if isinstance(value, dict):
        return sanitize_job_metadata(value)
    return None


def sanitize_job_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(metadata, dict):
        return {}
    sanitized: dict[str, Any] = {}
    for key, value in metadata.items():
        key_text = str(key)
        if _is_sensitive_metadata_key(key_text):
            continue
        sanitized_value = _sanitize_metadata_value(value, parent_key=key_text)
        if sanitized_value is not None:
            sanitized[key_text] = sanitized_value
    return sanitized


def log_job_event(record: "JobEventRecord") -> None:
    metadata = sanitize_job_metadata(record.metadata)
    fields: dict[str, Any] = {
        "case_id": record.case_id,
        "analysis_run_id": record.analysis_run_id,
        "step_name": record.step_name,
        "event_type": record.event_type,
        "status": record.status,
        "attempt": record.attempt,
        "metadata": metadata,
    }
    error_message = sanitize_error_message(record.error_message) if record.error_message else None
    if error_message:
        fields["error_message"] = error_message
    metadata_text = json.dumps(metadata, sort_keys=True, separators=(",", ":"))
    error_text = f" error_message={json.dumps(error_message)}" if error_message else ""
    _JOB_EVENT_LOGGER.info(
        "analysis_event case_id=%s analysis_run_id=%s step=%s event=%s "
        "status=%s attempt=%s metadata=%s%s",
        record.case_id,
        record.analysis_run_id,
        record.step_name,
        record.event_type,
        record.status,
        record.attempt,
        metadata_text,
        error_text,
        extra={"logan_analysis_event": fields},
    )


def _is_sensitive_artifact_key(key: str) -> bool:
    lowered = key.lower()
    return any(part in lowered for part in _SENSITIVE_ARTIFACT_KEY_PARTS)


def _sanitize_artifact_metadata_value(value: Any, *, parent_key: str) -> Any:
    if value is None or isinstance(value, bool | int | float):
        return value
    if isinstance(value, str):
        if (
            parent_key in _SAFE_ARTIFACT_STRING_KEYS
            or parent_key.endswith("_hash")
            or parent_key.endswith("_sha256")
        ):
            return sanitize_error_message(value, max_length=200)
        if (
            parent_key in _SAFE_ARTIFACT_LIST_STRINGS
            and value in _SAFE_ARTIFACT_LIST_VALUES
        ):
            return value
        return None
    if isinstance(value, list):
        sanitized_items = [
            _sanitize_artifact_metadata_value(item, parent_key=parent_key)
            for item in value[:50]
        ]
        return [item for item in sanitized_items if item is not None]
    if isinstance(value, dict):
        return sanitize_artifact_metadata(value)
    return None


def sanitize_artifact_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(metadata, dict):
        return {}
    sanitized: dict[str, Any] = {}
    for key, value in metadata.items():
        key_text = str(key)
        if _is_sensitive_artifact_key(key_text):
            continue
        sanitized_value = _sanitize_artifact_metadata_value(value, parent_key=key_text)
        if sanitized_value is not None:
            sanitized[key_text] = sanitized_value
    return sanitized


def sanitize_workflow_payload(value: Any) -> Any:
    if value is None or isinstance(value, bool | int | float):
        return value
    if isinstance(value, str):
        return sanitize_error_message(value, max_length=2000)
    if isinstance(value, list):
        return [sanitize_workflow_payload(item) for item in value]
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            lowered = key_text.lower()
            if any(part in lowered for part in _SECRET_WORKFLOW_KEY_PARTS):
                continue
            sanitized[key_text] = sanitize_workflow_payload(item)
        return sanitized
    return None


def merge_recorded_progress(
    result_progress: dict[str, Any],
    recorded_progress: dict[str, Any] | None,
) -> dict[str, Any]:
    if not isinstance(recorded_progress, dict):
        return result_progress
    recorded_steps = recorded_progress.get("steps")
    if not isinstance(recorded_steps, dict):
        return result_progress
    merged = dict(result_progress)
    result_steps = merged.get("steps") if isinstance(merged.get("steps"), dict) else {}
    merged["steps"] = {**recorded_steps, **result_steps}
    return merged


@dataclass
class OrganizationRecord:
    id: str
    name: str
    slug: str
    is_default: bool = False
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class UserRecord:
    id: str
    email: str
    username: str
    full_name: str | None
    password_hash: str
    role: str = "engineer"
    is_active: bool = True
    organization_id: str = DEFAULT_ORGANIZATION_ID
    external_id: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class SessionRecord:
    id: str
    user_id: str
    token_hash: str
    expires_at: datetime
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    revoked_at: datetime | None = None


@dataclass
class CredentialRecord:
    id: str
    user_id: str
    credential_type: str
    encrypted_token: bytes
    token_hint: str
    github_base_url: str
    runtime_type: str = "ai_platform"
    key_id: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime | None = None
    revoked_at: datetime | None = None


@dataclass
class CaseRecord:
    id: str
    case_key: str
    title: str
    issue_description: str | None
    product: str | None
    service: str | None
    environment: str | None
    incident_start: datetime | None
    incident_end: datetime | None
    timezone: str = "UTC"
    status: str = "created"
    created_by: str = ""
    organization_id: str = DEFAULT_ORGANIZATION_ID
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class CaseCollaboratorRecord:
    id: str
    case_id: str
    user_id: str
    role: str
    added_by: str | None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    email: str | None = None
    username: str | None = None
    full_name: str | None = None


@dataclass
class PolicyGroupRecord:
    id: str
    organization_id: str
    name: str
    slug: str
    description: str | None = None
    external_id: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class PolicyGroupMemberRecord:
    id: str
    group_id: str
    user_id: str
    role: str = "viewer"
    added_by: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    email: str | None = None
    username: str | None = None
    full_name: str | None = None


@dataclass
class CaseGroupAccessRecord:
    id: str
    case_id: str
    group_id: str
    role: str
    granted_by: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    group_name: str | None = None
    group_slug: str | None = None


@dataclass
class UploadRecord:
    id: str
    case_id: str
    filename: str
    content_type: str | None
    size_bytes: int
    object_uri: str
    sha256: str | None = None
    completed: bool = False
    upload_metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class AnalysisRunRecord:
    id: str
    case_id: str
    run_number: int
    status: str
    config: dict[str, Any]
    model_provider: str
    model_name: str
    model_reasoning_effort: str
    prompt_version: str = "annotation_v1"
    created_by: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error_message: str | None = None
    result: AnalysisResult | None = None
    progress: dict[str, Any] = field(default_factory=dict)


@dataclass
class JobEventRecord:
    id: str
    case_id: str
    analysis_run_id: str
    step_name: str
    event_type: str
    status: str
    attempt: int
    idempotency_key: str
    metadata: dict[str, Any] = field(default_factory=dict)
    error_message: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class AnalyticsSinkWriteRecord:
    id: str
    case_id: str
    analysis_run_id: str
    sink_name: str
    destination: str
    idempotency_key: str
    payload_hash: str
    status: str
    attempt_count: int
    row_count: int
    last_error: str | None = None
    last_attempt_at: datetime | None = None
    next_retry_at: datetime | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class AnalysisStepArtifactRecord:
    id: str
    case_id: str
    analysis_run_id: str
    step_name: str
    artifact_type: str
    object_uri: str
    sha256: str
    size_bytes: int
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))


def apply_job_event_progress(
    progress: dict[str, Any] | None, event: JobEventRecord
) -> dict[str, Any]:
    next_progress = dict(progress or {})
    raw_steps = next_progress.get("steps")
    steps = dict(raw_steps) if isinstance(raw_steps, dict) else {}
    raw_step = steps.get(event.step_name)
    step = dict(raw_step) if isinstance(raw_step, dict) else {}
    step["status"] = event.status
    step["attempt"] = event.attempt
    step[f"{event.event_type}_at"] = event.created_at.isoformat()
    if event.metadata:
        step["metadata"] = event.metadata
        next_progress.update(event.metadata)
        if "files" in event.metadata:
            next_progress["files_total"] = event.metadata["files"]
            next_progress["files_processed"] = event.metadata["files"]
        if "samples" in event.metadata:
            next_progress["representative_samples"] = event.metadata["samples"]
        if "annotations" in event.metadata:
            next_progress["annotated_templates"] = event.metadata["annotations"]
    if event.error_message:
        step["error_message"] = event.error_message
        next_progress["error_message"] = event.error_message
    steps[event.step_name] = step
    next_progress["steps"] = steps
    next_progress["current_step"] = (
        "completed"
        if event.step_name == "export_artifacts" and event.event_type == "completed"
        else event.step_name
    )
    return next_progress


def merge_analysis_result_progress(
    existing_progress: dict[str, Any] | None,
    result_progress: dict[str, Any],
) -> dict[str, Any]:
    progress = dict(result_progress)
    if "orchestrator" not in progress and isinstance(existing_progress, dict):
        orchestrator = existing_progress.get("orchestrator")
        if orchestrator:
            progress["orchestrator"] = orchestrator
    return progress


@dataclass
class FeedbackRecord:
    id: str
    case_id: str
    analysis_run_id: str | None
    user_id: str
    target_type: str
    target_id: str | None
    feedback_type: str
    rating: int | None
    comment: str | None
    corrected_value: dict[str, Any] | None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class ExportRecord:
    id: str
    case_id: str
    analysis_run_id: str
    export_type: str
    object_uri: str
    created_by: str
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class AuditLogRecord:
    id: str
    action: str
    user_id: str | None = None
    target_type: str | None = None
    target_id: str | None = None
    case_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    ip_address: str | None = None
    user_agent: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class RetentionResultRecord:
    audit_logs_deleted: int = 0
    raw_log_lines_scrubbed: int = 0
    exports_deleted: int = 0
    analysis_results_cleared: int = 0
    step_artifacts_deleted: int = 0


REVOCABLE_CREDENTIAL_TYPES = frozenset({"github_source_oauth", "ai_platform_token"})


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def _credential_is_active(record: CredentialRecord, *, now: datetime | None = None) -> bool:
    if record.revoked_at is not None:
        return False
    expires_at = _as_utc(record.expires_at)
    return expires_at is None or expires_at > (now or datetime.now(UTC))


def _case_role_allows(role: str | None, permission: str) -> bool:
    return role in CASE_PERMISSION_ROLES.get(permission, frozenset())


def _validate_global_role(role: str) -> str:
    if role not in GLOBAL_USER_ROLES:
        raise ValueError("role must be one of: admin, engineer")
    return role


def _validate_case_role(role: str) -> str:
    if role not in CASE_COLLABORATOR_ROLES:
        raise ValueError("collaborator role must be one of: owner, editor, viewer")
    return role


def _validate_policy_group_role(role: str) -> str:
    if role not in POLICY_GROUP_ROLES:
        raise ValueError("policy group role must be one of: owner, editor, viewer")
    return role


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "group"


class MetadataStore(Protocol):
    settings: Settings

    def ensure_organization(
        self,
        *,
        organization_id: str = DEFAULT_ORGANIZATION_ID,
        name: str = DEFAULT_ORGANIZATION_NAME,
        slug: str = DEFAULT_ORGANIZATION_SLUG,
        is_default: bool = False,
    ) -> OrganizationRecord: ...

    def get_organization(self, organization_id: str) -> OrganizationRecord | None: ...

    def list_organizations(self) -> list[OrganizationRecord]: ...

    def register_user(
        self,
        *,
        email: str,
        username: str,
        full_name: str | None,
        password: str,
        organization_id: str | None = None,
        external_id: str | None = None,
    ) -> UserRecord: ...

    def authenticate(self, email_or_username: str, password: str) -> UserRecord | None: ...

    def create_session(self, user_id: str) -> tuple[str, SessionRecord]: ...

    def get_user_by_session(self, token: str | None) -> UserRecord | None: ...

    def revoke_session(self, token: str | None) -> None: ...

    def get_user(self, user_id: str) -> UserRecord | None: ...

    def list_users(
        self,
        *,
        q: str | None = None,
        role: str | None = None,
        is_active: bool | None = None,
        organization_id: str | None = None,
        offset: int = 0,
        limit: int | None = None,
    ) -> tuple[list[UserRecord], int]: ...

    def update_user_profile(
        self,
        *,
        user_id: str,
        email: str | None = None,
        username: str | None = None,
        full_name: str | None = None,
        external_id: str | None = None,
        updated_by: str | None = None,
    ) -> UserRecord: ...

    def update_user_role(
        self, *, user_id: str, role: str, updated_by: str | None = None
    ) -> UserRecord: ...

    def set_user_active(
        self, *, user_id: str, is_active: bool, updated_by: str | None = None
    ) -> UserRecord: ...

    def save_credential(
        self,
        *,
        user_id: str,
        credential_type: str,
        token: str,
        github_base_url: str,
        expires_at: datetime | None = None,
    ) -> CredentialRecord: ...

    def get_credential(
        self, *, user_id: str, credential_type: str
    ) -> CredentialRecord | None: ...

    def revoke_credentials(
        self, user_id: str, credential_types: set[str] | list[str] | tuple[str, ...] | None = None
    ) -> int: ...

    def has_credential(self, user_id: str) -> bool: ...

    def create_case(self, *, user_id: str, data: dict[str, Any]) -> CaseRecord: ...

    def get_case(self, case_id: str) -> CaseRecord | None: ...

    def list_cases(
        self,
        *,
        status: str | None = None,
        product: str | None = None,
        offset: int = 0,
        limit: int | None = None,
    ) -> tuple[list[CaseRecord], int]: ...

    def list_cases_for_user(
        self,
        user: UserRecord,
        *,
        status: str | None = None,
        product: str | None = None,
        offset: int = 0,
        limit: int | None = None,
    ) -> tuple[list[CaseRecord], int]: ...

    def user_can_access_case(
        self, user_id: str, case_id: str, permission: str
    ) -> bool: ...

    def list_case_collaborators(self, case_id: str) -> list[CaseCollaboratorRecord]: ...

    def upsert_case_collaborator(
        self, *, case_id: str, user_id: str, role: str, added_by: str
    ) -> CaseCollaboratorRecord: ...

    def remove_case_collaborator(
        self, *, case_id: str, user_id: str, removed_by: str
    ) -> bool: ...

    def create_policy_group(
        self,
        *,
        organization_id: str,
        name: str,
        slug: str | None = None,
        description: str | None = None,
        external_id: str | None = None,
        created_by: str | None = None,
    ) -> PolicyGroupRecord: ...

    def update_policy_group(
        self,
        *,
        group_id: str,
        name: str | None = None,
        slug: str | None = None,
        description: str | None = None,
        external_id: str | None = None,
        updated_by: str | None = None,
    ) -> PolicyGroupRecord: ...

    def get_policy_group(self, group_id: str) -> PolicyGroupRecord | None: ...

    def list_policy_groups(
        self, *, organization_id: str | None = None
    ) -> list[PolicyGroupRecord]: ...

    def list_policy_group_members(self, group_id: str) -> list[PolicyGroupMemberRecord]: ...

    def upsert_policy_group_member(
        self, *, group_id: str, user_id: str, role: str = "viewer", added_by: str | None = None
    ) -> PolicyGroupMemberRecord: ...

    def remove_policy_group_member(
        self, *, group_id: str, user_id: str, removed_by: str | None = None
    ) -> bool: ...

    def list_case_group_access(self, case_id: str) -> list[CaseGroupAccessRecord]: ...

    def upsert_case_group_access(
        self, *, case_id: str, group_id: str, role: str, granted_by: str | None = None
    ) -> CaseGroupAccessRecord: ...

    def remove_case_group_access(
        self, *, case_id: str, group_id: str, removed_by: str | None = None
    ) -> bool: ...

    def create_upload(
        self, *, case_id: str, filename: str, content_type: str | None, size_bytes: int
    ) -> UploadRecord: ...

    def get_upload(self, upload_id: str) -> UploadRecord | None: ...

    def update_upload_metadata(
        self, *, upload_id: str, metadata: dict[str, Any]
    ) -> UploadRecord: ...

    def complete_upload(self, *, upload_id: str, sha256: str) -> UploadRecord: ...

    async def start_analysis(
        self,
        *,
        case_id: str,
        user_id: str,
        input_paths: list[str],
        config: dict[str, Any],
        gateway: Any | None = None,
        s3_client_factory: S3ClientFactory | None = None,
    ) -> AnalysisRunRecord: ...

    def get_analysis_run(self, run_id: str) -> AnalysisRunRecord | None: ...

    def list_analysis_runs(self, case_id: str) -> list[AnalysisRunRecord]: ...

    def record_job_event(
        self,
        *,
        case_id: str,
        analysis_run_id: str,
        step_name: str,
        event_type: str,
        status: str,
        attempt: int = 1,
        idempotency_key: str,
        metadata: dict[str, Any] | None = None,
        error_message: str | None = None,
    ) -> JobEventRecord: ...

    def apply_analysis_job_event(
        self, *, run_id: str, event: dict[str, Any]
    ) -> JobEventRecord: ...

    def complete_analysis_run(
        self, *, run_id: str, result: AnalysisResult, user_id: str
    ) -> AnalysisRunRecord: ...

    def fail_analysis_run(
        self, *, run_id: str, error_message: str, user_id: str
    ) -> AnalysisRunRecord: ...

    def list_job_events(
        self,
        *,
        case_id: str | None = None,
        analysis_run_id: str | None = None,
        step_name: str | None = None,
    ) -> list[JobEventRecord]: ...

    def upsert_analysis_step_artifact(
        self,
        *,
        case_id: str,
        analysis_run_id: str,
        step_name: str,
        artifact_type: str,
        object_uri: str,
        sha256: str,
        size_bytes: int,
        metadata: dict[str, Any] | None = None,
    ) -> AnalysisStepArtifactRecord: ...

    def list_analysis_step_artifacts(
        self,
        *,
        case_id: str | None = None,
        analysis_run_id: str | None = None,
        step_name: str | None = None,
    ) -> list[AnalysisStepArtifactRecord]: ...

    def get_analysis_result(self, case_id: str, run_id: str) -> AnalysisResult | None: ...

    def update_causal_summary(
        self,
        *,
        case_id: str,
        run_id: str,
        summary_markdown: str,
        customer_update_markdown: str | None,
        user_id: str,
    ) -> dict[str, object] | None: ...

    def create_export(
        self,
        *,
        export_id: str,
        case_id: str,
        analysis_run_id: str,
        export_type: str,
        object_uri: str,
        user_id: str,
    ) -> ExportRecord: ...

    def get_export(self, export_id: str) -> ExportRecord | None: ...

    def record_feedback(
        self,
        *,
        case_id: str,
        analysis_run_id: str | None,
        user_id: str,
        target_type: str,
        target_id: str | None,
        feedback_type: str,
        rating: int | None,
        comment: str | None,
        corrected_value: dict[str, Any] | None,
    ) -> FeedbackRecord: ...

    def get_feedback(self, feedback_id: str) -> FeedbackRecord | None: ...

    def record_audit(
        self,
        *,
        action: str,
        user_id: str | None = None,
        target_type: str | None = None,
        target_id: str | None = None,
        case_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> AuditLogRecord: ...

    def list_audit_logs(
        self,
        *,
        case_id: str | None = None,
        action: str | None = None,
        user_id: str | None = None,
        offset: int = 0,
        limit: int | None = None,
    ) -> list[AuditLogRecord]: ...

    def run_retention(self, *, now: datetime | None = None) -> RetentionResultRecord: ...


class InMemoryStore:
    def __init__(self, app_settings: Settings = settings) -> None:
        self.settings = app_settings
        self.organizations: dict[str, OrganizationRecord] = {}
        self.users: dict[str, UserRecord] = {}
        self.users_by_email: dict[str, str] = {}
        self.users_by_username: dict[str, str] = {}
        self.sessions_by_hash: dict[str, SessionRecord] = {}
        self.credentials_by_user: dict[tuple[str, str], CredentialRecord] = {}
        self.cases: dict[str, CaseRecord] = {}
        self.case_collaborators: dict[tuple[str, str], CaseCollaboratorRecord] = {}
        self.policy_groups: dict[str, PolicyGroupRecord] = {}
        self.policy_group_members: dict[tuple[str, str], PolicyGroupMemberRecord] = {}
        self.case_group_access: dict[tuple[str, str], CaseGroupAccessRecord] = {}
        self.uploads: dict[str, UploadRecord] = {}
        self.runs: dict[str, AnalysisRunRecord] = {}
        self.job_events: dict[str, JobEventRecord] = {}
        self.job_event_keys: dict[tuple[str, str, str], str] = {}
        self.analysis_step_artifacts: dict[str, AnalysisStepArtifactRecord] = {}
        self.analysis_step_artifact_keys: dict[tuple[str, str, str], str] = {}
        self.feedback: dict[str, FeedbackRecord] = {}
        self.exports: dict[str, ExportRecord] = {}
        self.audit_logs: dict[str, AuditLogRecord] = {}
        self.ensure_organization(is_default=True)

    def ensure_organization(
        self,
        *,
        organization_id: str = DEFAULT_ORGANIZATION_ID,
        name: str = DEFAULT_ORGANIZATION_NAME,
        slug: str = DEFAULT_ORGANIZATION_SLUG,
        is_default: bool = False,
    ) -> OrganizationRecord:
        existing = self.organizations.get(organization_id)
        if existing is not None:
            return existing
        record = OrganizationRecord(
            id=organization_id,
            name=name,
            slug=slug,
            is_default=is_default,
        )
        self.organizations[record.id] = record
        return record

    def get_organization(self, organization_id: str) -> OrganizationRecord | None:
        return self.organizations.get(organization_id)

    def list_organizations(self) -> list[OrganizationRecord]:
        return sorted(self.organizations.values(), key=lambda item: (item.name, item.id))

    def register_user(
        self,
        *,
        email: str,
        username: str,
        full_name: str | None,
        password: str,
        organization_id: str | None = None,
        external_id: str | None = None,
    ) -> UserRecord:
        if email in self.users_by_email or username in self.users_by_username:
            raise ValueError("user already exists")
        org_id = organization_id or DEFAULT_ORGANIZATION_ID
        self.ensure_organization(organization_id=org_id)
        user = UserRecord(
            id=str(uuid.uuid4()),
            email=email,
            username=username,
            full_name=full_name,
            password_hash=hash_password(password),
            organization_id=org_id,
            external_id=external_id,
        )
        self.users[user.id] = user
        self.users_by_email[email] = user.id
        self.users_by_username[username] = user.id
        return user

    def authenticate(self, email_or_username: str, password: str) -> UserRecord | None:
        user_id = self.users_by_email.get(email_or_username) or self.users_by_username.get(
            email_or_username
        )
        if not user_id:
            return None
        user = self.users[user_id]
        if not user.is_active:
            return None
        if not verify_password(password, user.password_hash):
            return None
        return user

    def create_session(self, user_id: str) -> tuple[str, SessionRecord]:
        token = issue_session_token()
        record = SessionRecord(
            id=str(uuid.uuid4()),
            user_id=user_id,
            token_hash=hash_token(token),
            expires_at=default_session_expiry(),
        )
        self.sessions_by_hash[record.token_hash] = record
        return token, record

    def get_user_by_session(self, token: str | None) -> UserRecord | None:
        if not token:
            return None
        session = self.sessions_by_hash.get(hash_token(token))
        if not session or session.revoked_at or session.expires_at < datetime.now(UTC):
            return None
        user = self.users.get(session.user_id)
        return user if user and user.is_active else None

    def revoke_session(self, token: str | None) -> None:
        if not token:
            return
        session = self.sessions_by_hash.get(hash_token(token))
        if session:
            session.revoked_at = datetime.now(UTC)

    def get_user(self, user_id: str) -> UserRecord | None:
        return self.users.get(user_id)

    def list_users(
        self,
        *,
        q: str | None = None,
        role: str | None = None,
        is_active: bool | None = None,
        organization_id: str | None = None,
        offset: int = 0,
        limit: int | None = None,
    ) -> tuple[list[UserRecord], int]:
        items = list(self.users.values())
        if organization_id:
            items = [item for item in items if item.organization_id == organization_id]
        if q:
            lowered = q.lower()
            items = [
                item
                for item in items
                if lowered in item.email.lower()
                or lowered in item.username.lower()
                or lowered in (item.full_name or "").lower()
            ]
        if role:
            items = [item for item in items if item.role == role]
        if is_active is not None:
            items = [item for item in items if item.is_active == is_active]
        items.sort(key=lambda item: (item.created_at, item.email, item.id))
        total = len(items)
        return items[offset : offset + limit if limit is not None else None], total

    def update_user_profile(
        self,
        *,
        user_id: str,
        email: str | None = None,
        username: str | None = None,
        full_name: str | None = None,
        external_id: str | None = None,
        updated_by: str | None = None,
    ) -> UserRecord:
        user = self.users.get(user_id)
        if user is None:
            raise KeyError(user_id)
        if email is not None and email != user.email:
            if email in self.users_by_email:
                raise ValueError("user already exists")
            self.users_by_email.pop(user.email, None)
            self.users_by_email[email] = user.id
            user.email = email
        if username is not None and username != user.username:
            if username in self.users_by_username:
                raise ValueError("user already exists")
            self.users_by_username.pop(user.username, None)
            self.users_by_username[username] = user.id
            user.username = username
        if full_name is not None:
            user.full_name = full_name
        if external_id is not None:
            user.external_id = external_id
        self.record_audit(
            action="admin.user.profile_update",
            user_id=updated_by,
            target_type="user",
            target_id=user_id,
            metadata={"updated": True},
        )
        return user

    def update_user_role(
        self, *, user_id: str, role: str, updated_by: str | None = None
    ) -> UserRecord:
        _validate_global_role(role)
        user = self.users.get(user_id)
        if user is None:
            raise KeyError(user_id)
        previous_role = user.role
        user.role = role
        self.record_audit(
            action="admin.user.role_update",
            user_id=updated_by,
            target_type="user",
            target_id=user_id,
            metadata={"previous_role": previous_role, "role": role},
        )
        return user

    def set_user_active(
        self, *, user_id: str, is_active: bool, updated_by: str | None = None
    ) -> UserRecord:
        user = self.users.get(user_id)
        if user is None:
            raise KeyError(user_id)
        previous_active = user.is_active
        user.is_active = is_active
        self.record_audit(
            action="admin.user.active_update",
            user_id=updated_by,
            target_type="user",
            target_id=user_id,
            metadata={"previous_active": previous_active, "is_active": is_active},
        )
        return user

    def save_credential(
        self,
        *,
        user_id: str,
        credential_type: str,
        token: str,
        github_base_url: str,
        expires_at: datetime | None = None,
    ) -> CredentialRecord:
        encrypted_token, key_id = encrypt_token_for_settings(token, self.settings)
        record = CredentialRecord(
            id=str(uuid.uuid4()),
            user_id=user_id,
            credential_type=credential_type,
            encrypted_token=encrypted_token,
            token_hint=token_hint(token),
            github_base_url=github_base_url,
            key_id=key_id,
            expires_at=_as_utc(expires_at),
        )
        self.credentials_by_user[(user_id, credential_type)] = record
        return record

    def get_credential(self, *, user_id: str, credential_type: str) -> CredentialRecord | None:
        record = self.credentials_by_user.get((user_id, credential_type))
        if record is None or not _credential_is_active(record):
            return None
        return record

    def revoke_credentials(
        self, user_id: str, credential_types: set[str] | list[str] | tuple[str, ...] | None = None
    ) -> int:
        credential_type_filter = set(credential_types) if credential_types is not None else None
        revoked_at = datetime.now(UTC)
        revoked_count = 0
        for (record_user_id, credential_type), record in self.credentials_by_user.items():
            if record_user_id != user_id:
                continue
            if credential_type_filter is not None and credential_type not in credential_type_filter:
                continue
            if record.revoked_at is not None:
                continue
            record.revoked_at = revoked_at
            revoked_count += 1
        return revoked_count

    def has_credential(self, user_id: str) -> bool:
        return any(
            self.get_credential(user_id=user_id, credential_type=credential_type) is not None
            for credential_type in REVOCABLE_CREDENTIAL_TYPES
        )

    def create_case(self, *, user_id: str, data: dict[str, Any]) -> CaseRecord:
        case_id = str(uuid.uuid4())
        case_key = f"LOGAN-{datetime.now(UTC):%Y%m%d}-{len(self.cases) + 1:04d}"
        user = self.users.get(user_id)
        organization_id = user.organization_id if user else DEFAULT_ORGANIZATION_ID
        self.ensure_organization(organization_id=organization_id)
        record = CaseRecord(
            id=case_id,
            case_key=case_key,
            created_by=user_id,
            organization_id=organization_id,
            **data,
        )
        self.cases[case_id] = record
        self.case_collaborators[(case_id, user_id)] = CaseCollaboratorRecord(
            id=str(uuid.uuid4()),
            case_id=case_id,
            user_id=user_id,
            role="owner",
            added_by=user_id,
            email=self.users.get(user_id).email if user_id in self.users else None,
            username=self.users.get(user_id).username if user_id in self.users else None,
            full_name=self.users.get(user_id).full_name if user_id in self.users else None,
        )
        self.record_audit(
            action="case.create",
            user_id=user_id,
            target_type="case",
            target_id=case_id,
            case_id=case_id,
        )
        return record

    def get_case(self, case_id: str) -> CaseRecord | None:
        return self.cases.get(case_id)

    def list_cases(
        self,
        *,
        status: str | None = None,
        product: str | None = None,
        offset: int = 0,
        limit: int | None = None,
    ) -> tuple[list[CaseRecord], int]:
        items = list(self.cases.values())
        if status:
            items = [item for item in items if item.status == status]
        if product:
            items = [item for item in items if item.product == product]
        total = len(items)
        return items[offset : offset + limit if limit is not None else None], total

    def list_cases_for_user(
        self,
        user: UserRecord,
        *,
        status: str | None = None,
        product: str | None = None,
        offset: int = 0,
        limit: int | None = None,
    ) -> tuple[list[CaseRecord], int]:
        items = [
            item for item in self.cases.values() if item.organization_id == user.organization_id
        ]
        if user.role != "admin":
            collaborator_case_ids = {
                case_id
                for (case_id, collaborator_user_id), collaborator in self.case_collaborators.items()
                if collaborator_user_id == user.id
                and _case_role_allows(collaborator.role, "view")
            }
            group_case_ids = self._case_ids_for_user_policy_groups(user.id, "view")
            items = [
                item
                for item in items
                if item.created_by == user.id
                or item.id in collaborator_case_ids
                or item.id in group_case_ids
            ]
        if status:
            items = [item for item in items if item.status == status]
        if product:
            items = [item for item in items if item.product == product]
        items.sort(key=lambda item: (item.created_at, item.id))
        total = len(items)
        return items[offset : offset + limit if limit is not None else None], total

    def user_can_access_case(
        self, user_id: str, case_id: str, permission: str
    ) -> bool:
        user = self.users.get(user_id)
        if user is None or not user.is_active:
            return False
        if user.role == "admin":
            case = self.cases.get(case_id)
            return case is not None and case.organization_id == user.organization_id
        case = self.cases.get(case_id)
        if case is None:
            return False
        if case.organization_id != user.organization_id:
            return False
        if case.created_by == user_id:
            return True
        collaborator = self.case_collaborators.get((case_id, user_id))
        if _case_role_allows(collaborator.role if collaborator else None, permission):
            return True
        return case_id in self._case_ids_for_user_policy_groups(user_id, permission)

    def _case_ids_for_user_policy_groups(self, user_id: str, permission: str) -> set[str]:
        user = self.users.get(user_id)
        if user is None:
            return set()
        group_ids = {
            group_id
            for (group_id, member_user_id), member in self.policy_group_members.items()
            if member_user_id == user_id
            and group_id in self.policy_groups
            and self.policy_groups[group_id].organization_id == user.organization_id
        }
        return {
            case_id
            for (case_id, group_id), access in self.case_group_access.items()
            if group_id in group_ids
            and case_id in self.cases
            and self.cases[case_id].organization_id == user.organization_id
            and _case_role_allows(access.role, permission)
        }

    def list_case_collaborators(self, case_id: str) -> list[CaseCollaboratorRecord]:
        case = self.cases.get(case_id)
        if case is None:
            raise KeyError(case_id)
        items = [
            self._with_user_details(collaborator)
            for (collaborator_case_id, _user_id), collaborator in self.case_collaborators.items()
            if collaborator_case_id == case_id
        ]
        if case.created_by and not any(item.user_id == case.created_by for item in items):
            user = self.users.get(case.created_by)
            items.append(
                CaseCollaboratorRecord(
                    id=f"implicit-owner:{case_id}:{case.created_by}",
                    case_id=case_id,
                    user_id=case.created_by,
                    role="owner",
                    added_by=case.created_by,
                    created_at=case.created_at,
                    updated_at=case.created_at,
                    email=user.email if user else None,
                    username=user.username if user else None,
                    full_name=user.full_name if user else None,
                )
            )
        return sorted(items, key=lambda item: (item.role != "owner", item.created_at, item.user_id))

    def upsert_case_collaborator(
        self, *, case_id: str, user_id: str, role: str, added_by: str
    ) -> CaseCollaboratorRecord:
        _validate_case_role(role)
        if case_id not in self.cases:
            raise KeyError(case_id)
        if user_id not in self.users:
            raise KeyError(user_id)
        if self.cases[case_id].organization_id != self.users[user_id].organization_id:
            raise ValueError("user and case must belong to the same organization")
        now = datetime.now(UTC)
        key = (case_id, user_id)
        existing = self.case_collaborators.get(key)
        record = CaseCollaboratorRecord(
            id=existing.id if existing else str(uuid.uuid4()),
            case_id=case_id,
            user_id=user_id,
            role=role,
            added_by=added_by,
            created_at=existing.created_at if existing else now,
            updated_at=now,
        )
        self.case_collaborators[key] = record
        self.record_audit(
            action="case.collaborator.add",
            user_id=added_by,
            target_type="user",
            target_id=user_id,
            case_id=case_id,
            metadata={"role": role, "previous_role": existing.role if existing else None},
        )
        return self._with_user_details(record)

    def remove_case_collaborator(
        self, *, case_id: str, user_id: str, removed_by: str
    ) -> bool:
        if case_id not in self.cases:
            raise KeyError(case_id)
        removed = self.case_collaborators.pop((case_id, user_id), None)
        if removed is None:
            return False
        self.record_audit(
            action="case.collaborator.remove",
            user_id=removed_by,
            target_type="user",
            target_id=user_id,
            case_id=case_id,
            metadata={"role": removed.role},
        )
        return True

    def create_policy_group(
        self,
        *,
        organization_id: str,
        name: str,
        slug: str | None = None,
        description: str | None = None,
        external_id: str | None = None,
        created_by: str | None = None,
    ) -> PolicyGroupRecord:
        self.ensure_organization(organization_id=organization_id)
        normalized_slug = _slugify(slug or name)
        if any(
            group.organization_id == organization_id and group.slug == normalized_slug
            for group in self.policy_groups.values()
        ):
            raise ValueError("policy group already exists")
        record = PolicyGroupRecord(
            id=str(uuid.uuid4()),
            organization_id=organization_id,
            name=name,
            slug=normalized_slug,
            description=description,
            external_id=external_id,
        )
        self.policy_groups[record.id] = record
        self.record_audit(
            action="policy_group.create",
            user_id=created_by,
            target_type="policy_group",
            target_id=record.id,
            metadata={"organization_id": organization_id, "slug": normalized_slug},
        )
        return record

    def update_policy_group(
        self,
        *,
        group_id: str,
        name: str | None = None,
        slug: str | None = None,
        description: str | None = None,
        external_id: str | None = None,
        updated_by: str | None = None,
    ) -> PolicyGroupRecord:
        group = self.policy_groups.get(group_id)
        if group is None:
            raise KeyError(group_id)
        normalized_slug = _slugify(slug or name or group.slug)
        if normalized_slug != group.slug and any(
            item.organization_id == group.organization_id and item.slug == normalized_slug
            for item in self.policy_groups.values()
        ):
            raise ValueError("policy group already exists")
        if name is not None:
            group.name = name
        group.slug = normalized_slug
        if description is not None:
            group.description = description
        if external_id is not None:
            group.external_id = external_id
        group.updated_at = datetime.now(UTC)
        self.record_audit(
            action="policy_group.update",
            user_id=updated_by,
            target_type="policy_group",
            target_id=group_id,
            metadata={"organization_id": group.organization_id, "slug": group.slug},
        )
        return group

    def get_policy_group(self, group_id: str) -> PolicyGroupRecord | None:
        return self.policy_groups.get(group_id)

    def list_policy_groups(
        self, *, organization_id: str | None = None
    ) -> list[PolicyGroupRecord]:
        items = list(self.policy_groups.values())
        if organization_id is not None:
            items = [item for item in items if item.organization_id == organization_id]
        return sorted(items, key=lambda item: (item.name, item.id))

    def list_policy_group_members(self, group_id: str) -> list[PolicyGroupMemberRecord]:
        if group_id not in self.policy_groups:
            raise KeyError(group_id)
        items = [
            self._with_policy_group_member_user_details(member)
            for (member_group_id, _user_id), member in self.policy_group_members.items()
            if member_group_id == group_id
        ]
        return sorted(items, key=lambda item: (item.role != "owner", item.email or "", item.user_id))

    def upsert_policy_group_member(
        self, *, group_id: str, user_id: str, role: str = "viewer", added_by: str | None = None
    ) -> PolicyGroupMemberRecord:
        _validate_policy_group_role(role)
        group = self.policy_groups.get(group_id)
        if group is None:
            raise KeyError(group_id)
        user = self.users.get(user_id)
        if user is None:
            raise KeyError(user_id)
        if user.organization_id != group.organization_id:
            raise ValueError("user and policy group must belong to the same organization")
        now = datetime.now(UTC)
        key = (group_id, user_id)
        existing = self.policy_group_members.get(key)
        record = PolicyGroupMemberRecord(
            id=existing.id if existing else str(uuid.uuid4()),
            group_id=group_id,
            user_id=user_id,
            role=role,
            added_by=added_by,
            created_at=existing.created_at if existing else now,
            updated_at=now,
        )
        self.policy_group_members[key] = record
        self.record_audit(
            action="policy_group.member.add",
            user_id=added_by,
            target_type="user",
            target_id=user_id,
            metadata={
                "group_id": group_id,
                "role": role,
                "previous_role": existing.role if existing else None,
            },
        )
        return self._with_policy_group_member_user_details(record)

    def remove_policy_group_member(
        self, *, group_id: str, user_id: str, removed_by: str | None = None
    ) -> bool:
        if group_id not in self.policy_groups:
            raise KeyError(group_id)
        removed = self.policy_group_members.pop((group_id, user_id), None)
        if removed is None:
            return False
        self.record_audit(
            action="policy_group.member.remove",
            user_id=removed_by,
            target_type="user",
            target_id=user_id,
            metadata={"group_id": group_id, "role": removed.role},
        )
        return True

    def list_case_group_access(self, case_id: str) -> list[CaseGroupAccessRecord]:
        if case_id not in self.cases:
            raise KeyError(case_id)
        items = [
            self._with_case_group_details(access)
            for (access_case_id, _group_id), access in self.case_group_access.items()
            if access_case_id == case_id
        ]
        return sorted(items, key=lambda item: (item.role != "owner", item.group_name or "", item.group_id))

    def upsert_case_group_access(
        self, *, case_id: str, group_id: str, role: str, granted_by: str | None = None
    ) -> CaseGroupAccessRecord:
        _validate_policy_group_role(role)
        case = self.cases.get(case_id)
        if case is None:
            raise KeyError(case_id)
        group = self.policy_groups.get(group_id)
        if group is None:
            raise KeyError(group_id)
        if group.organization_id != case.organization_id:
            raise ValueError("case and policy group must belong to the same organization")
        now = datetime.now(UTC)
        key = (case_id, group_id)
        existing = self.case_group_access.get(key)
        record = CaseGroupAccessRecord(
            id=existing.id if existing else str(uuid.uuid4()),
            case_id=case_id,
            group_id=group_id,
            role=role,
            granted_by=granted_by,
            created_at=existing.created_at if existing else now,
            updated_at=now,
        )
        self.case_group_access[key] = record
        self.record_audit(
            action="case.policy_group.grant",
            user_id=granted_by,
            target_type="policy_group",
            target_id=group_id,
            case_id=case_id,
            metadata={"role": role, "previous_role": existing.role if existing else None},
        )
        return self._with_case_group_details(record)

    def remove_case_group_access(
        self, *, case_id: str, group_id: str, removed_by: str | None = None
    ) -> bool:
        if case_id not in self.cases:
            raise KeyError(case_id)
        removed = self.case_group_access.pop((case_id, group_id), None)
        if removed is None:
            return False
        self.record_audit(
            action="case.policy_group.revoke",
            user_id=removed_by,
            target_type="policy_group",
            target_id=group_id,
            case_id=case_id,
            metadata={"role": removed.role},
        )
        return True

    def _with_policy_group_member_user_details(
        self, member: PolicyGroupMemberRecord
    ) -> PolicyGroupMemberRecord:
        user = self.users.get(member.user_id)
        return PolicyGroupMemberRecord(
            id=member.id,
            group_id=member.group_id,
            user_id=member.user_id,
            role=member.role,
            added_by=member.added_by,
            created_at=member.created_at,
            updated_at=member.updated_at,
            email=user.email if user else member.email,
            username=user.username if user else member.username,
            full_name=user.full_name if user else member.full_name,
        )

    def _with_case_group_details(self, access: CaseGroupAccessRecord) -> CaseGroupAccessRecord:
        group = self.policy_groups.get(access.group_id)
        return CaseGroupAccessRecord(
            id=access.id,
            case_id=access.case_id,
            group_id=access.group_id,
            role=access.role,
            granted_by=access.granted_by,
            created_at=access.created_at,
            updated_at=access.updated_at,
            group_name=group.name if group else access.group_name,
            group_slug=group.slug if group else access.group_slug,
        )

    def _with_user_details(
        self, collaborator: CaseCollaboratorRecord
    ) -> CaseCollaboratorRecord:
        user = self.users.get(collaborator.user_id)
        return CaseCollaboratorRecord(
            id=collaborator.id,
            case_id=collaborator.case_id,
            user_id=collaborator.user_id,
            role=collaborator.role,
            added_by=collaborator.added_by,
            created_at=collaborator.created_at,
            updated_at=collaborator.updated_at,
            email=user.email if user else collaborator.email,
            username=user.username if user else collaborator.username,
            full_name=user.full_name if user else collaborator.full_name,
        )

    def create_upload(
        self, *, case_id: str, filename: str, content_type: str | None, size_bytes: int
    ) -> UploadRecord:
        upload_id = str(uuid.uuid4())
        stored_filename = safe_filename(filename)
        if is_local_backend(self.settings):
            object_uri = local_upload_object_uri(
                case_id=case_id,
                file_id=upload_id,
                filename=stored_filename,
                app_settings=self.settings,
            )
        elif is_s3_backend(self.settings):
            object_uri = s3_upload_object_uri(
                case_id=case_id,
                file_id=upload_id,
                filename=stored_filename,
                app_settings=self.settings,
            )
        else:
            object_uri = f"memory://uploads/{case_id}/{upload_id}/{stored_filename}"
        record = UploadRecord(
            id=upload_id,
            case_id=case_id,
            filename=filename,
            content_type=content_type,
            size_bytes=size_bytes,
            object_uri=object_uri,
        )
        self.uploads[upload_id] = record
        if case_id in self.cases:
            self.cases[case_id].status = "uploading"
        return record

    def get_upload(self, upload_id: str) -> UploadRecord | None:
        return self.uploads.get(upload_id)

    def update_upload_metadata(
        self, *, upload_id: str, metadata: dict[str, Any]
    ) -> UploadRecord:
        record = self.uploads[upload_id]
        record.upload_metadata = dict(metadata)
        return record

    def complete_upload(self, *, upload_id: str, sha256: str) -> UploadRecord:
        record = self.uploads[upload_id]
        record.sha256 = sha256
        record.completed = True
        return record

    async def start_analysis(
        self,
        *,
        case_id: str,
        user_id: str,
        input_paths: list[str],
        config: dict[str, Any],
        gateway: Any | None = None,
        s3_client_factory: S3ClientFactory | None = None,
    ) -> AnalysisRunRecord:
        case = self.cases[case_id]
        run_number = 1 + len([run for run in self.runs.values() if run.case_id == case_id])
        run = AnalysisRunRecord(
            id=str(uuid.uuid4()),
            case_id=case_id,
            run_number=run_number,
            status="processing",
            config=config,
            model_provider=self.settings.llm_provider,
            model_name=config.get("model", {}).get("model", self.settings.ai_platform_model),
            model_reasoning_effort=config.get("model", {}).get(
                "reasoning_effort", self.settings.ai_platform_reasoning_effort
            ),
            created_by=user_id,
            started_at=datetime.now(UTC),
        )
        self.runs[run.id] = run
        case.status = "processing"
        self.record_audit(
            action="analysis.start",
            user_id=user_id,
            target_type="analysis_run",
            target_id=run.id,
            case_id=case_id,
        )
        try:
            if not input_paths:
                fixture_dir = Path("tests/fixtures/logs/checkout_incident")
                input_paths = [str(path) for path in sorted(fixture_dir.glob("*.log"))]
            orchestrator = (self.settings.analysis_orchestrator or "local").lower()
            if orchestrator not in {"local", "temporal"}:
                raise ValueError(
                    "LOGAN_ANALYSIS_ORCHESTRATOR must be one of: local, temporal"
                )
            if orchestrator == "temporal":
                from logan_workers.temporal_client import (
                    TemporalClientConfig,
                    start_analyze_case_workflow,
                )

                run.progress = {"current_step": "workflow_start", "orchestrator": "temporal"}
                await start_analyze_case_workflow(
                    case_id=case_id,
                    analysis_run_id=run.id,
                    paths=input_paths,
                    case_context=sanitize_workflow_payload(
                        {
                            "title": case.title,
                            "issue_description": case.issue_description,
                            "product": case.product,
                            "environment": case.environment,
                            "user_id": user_id,
                        }
                    ),
                    config=sanitize_workflow_payload(config),
                    activity_start_to_close_seconds=(
                        self.settings.temporal_activity_start_to_close_seconds
                    ),
                    activity_max_attempts=self.settings.temporal_activity_max_attempts,
                    temporal_config=TemporalClientConfig(
                        address=self.settings.temporal_address,
                        namespace=self.settings.temporal_namespace,
                        task_queue=self.settings.temporal_task_queue,
                    ),
                )
                return run

            def record_progress(event: dict[str, Any]) -> None:
                job_event = self.record_job_event(
                    case_id=case_id,
                    analysis_run_id=run.id,
                    step_name=str(event["step_name"]),
                    event_type=str(event["event_type"]),
                    status=str(event["status"]),
                    attempt=int(event.get("attempt", 1)),
                    idempotency_key=str(event["idempotency_key"]),
                    metadata=(
                        event.get("metadata")
                        if isinstance(event.get("metadata"), dict)
                        else {}
                    ),
                    error_message=event.get("error_message"),
                )
                run.progress = apply_job_event_progress(run.progress, job_event)

            with materialize_analysis_inputs(
                input_paths,
                self.settings,
                run_id=run.id,
                s3_client_factory=s3_client_factory,
            ) as materialized_paths:
                record_progress(
                    {
                        "step_name": "materialize_inputs",
                        "event_type": "completed",
                        "status": "completed",
                        "attempt": 1,
                        "idempotency_key": "materialize_inputs:attempt:1",
                        "metadata": {
                            "source_count": len(input_paths),
                            "materialized_count": len(materialized_paths),
                            "storage_backend_counts": analysis_input_backend_counts(
                                input_paths
                            ),
                        },
                    }
                )
                result = await AnalyzeCasePipeline().run(
                    case_id=case_id,
                    analysis_run_id=run.id,
                    paths=materialized_paths,
                    case_context={
                        "title": case.title,
                        "issue_description": case.issue_description,
                        "product": case.product,
                        "environment": case.environment,
                        "user_id": user_id,
                    },
                    config=config,
                    gateway=gateway,
                    progress_callback=record_progress,
                )
            result = result.model_copy(
                update={"progress": merge_recorded_progress(result.progress, run.progress)}
            )
            run = self.complete_analysis_run(run_id=run.id, result=result, user_id=user_id)
        except Exception as exc:
            error_message = sanitize_error_message(exc)
            run.status = "failed"
            run.error_message = error_message
            case.status = "failed"
            self.record_audit(
                action="analysis.fail",
                user_id=user_id,
                target_type="analysis_run",
                target_id=run.id,
                case_id=case_id,
                metadata={"error_message": error_message},
            )
            raise
        return run

    def get_analysis_run(self, run_id: str) -> AnalysisRunRecord | None:
        return self.runs.get(run_id)

    def list_analysis_runs(self, case_id: str) -> list[AnalysisRunRecord]:
        return sorted(
            [run for run in self.runs.values() if run.case_id == case_id],
            key=lambda run: run.run_number,
            reverse=True,
        )

    def record_job_event(
        self,
        *,
        case_id: str,
        analysis_run_id: str,
        step_name: str,
        event_type: str,
        status: str,
        attempt: int = 1,
        idempotency_key: str,
        metadata: dict[str, Any] | None = None,
        error_message: str | None = None,
    ) -> JobEventRecord:
        key = (analysis_run_id, idempotency_key, event_type)
        existing_id = self.job_event_keys.get(key)
        if existing_id is not None:
            record = self.job_events[existing_id]
            self._materialize_step_artifact_for_event(record)
            return record
        record = JobEventRecord(
            id=str(uuid.uuid4()),
            case_id=case_id,
            analysis_run_id=analysis_run_id,
            step_name=step_name,
            event_type=event_type,
            status=status,
            attempt=attempt,
            idempotency_key=idempotency_key,
            metadata=sanitize_job_metadata(metadata),
            error_message=sanitize_error_message(error_message) if error_message else None,
        )
        self.job_events[record.id] = record
        self.job_event_keys[key] = record.id
        log_job_event(record)
        self._materialize_step_artifact_for_event(record)
        return record

    def _materialize_step_artifact_for_event(self, event: JobEventRecord) -> None:
        from app.services.analysis_artifacts import materialize_step_artifact_for_event

        materialize_step_artifact_for_event(
            store=self,
            event=event,
            app_settings=self.settings,
        )

    def apply_analysis_job_event(
        self, *, run_id: str, event: dict[str, Any]
    ) -> JobEventRecord:
        run = self.runs.get(run_id)
        if run is None:
            raise KeyError(run_id)
        job_event = self.record_job_event(
            case_id=run.case_id,
            analysis_run_id=run.id,
            step_name=str(event["step_name"]),
            event_type=str(event["event_type"]),
            status=str(event["status"]),
            attempt=int(event.get("attempt", 1)),
            idempotency_key=str(event["idempotency_key"]),
            metadata=event.get("metadata") if isinstance(event.get("metadata"), dict) else {},
            error_message=event.get("error_message"),
        )
        run.progress = apply_job_event_progress(run.progress, job_event)
        return job_event

    def complete_analysis_run(
        self, *, run_id: str, result: AnalysisResult, user_id: str
    ) -> AnalysisRunRecord:
        run = self.runs.get(run_id)
        if run is None:
            raise KeyError(run_id)
        if run.status == "completed" and run.result is not None:
            return run
        case = self.cases.get(run.case_id)
        run.result = result
        run.progress = merge_analysis_result_progress(run.progress, result.progress)
        run.status = "completed"
        run.completed_at = datetime.now(UTC)
        run.error_message = None
        if case is not None:
            case.status = "ready"
        if not any(
            record.action == MODEL_INVOCATION_AUDIT_ACTION
            and record.target_type == "analysis_run"
            and record.target_id == run.id
            for record in self.audit_logs.values()
        ):
            self.record_audit(
                action=MODEL_INVOCATION_AUDIT_ACTION,
                user_id=user_id,
                target_type="analysis_run",
                target_id=run.id,
                case_id=run.case_id,
                metadata=model_invocation_audit_metadata(run=run, result=result),
            )
        self.record_audit(
            action="analysis.complete",
            user_id=user_id,
            target_type="analysis_run",
            target_id=run.id,
            case_id=run.case_id,
            metadata={"progress": run.progress},
        )
        return run

    def fail_analysis_run(
        self, *, run_id: str, error_message: str, user_id: str
    ) -> AnalysisRunRecord:
        run = self.runs.get(run_id)
        if run is None:
            raise KeyError(run_id)
        case = self.cases.get(run.case_id)
        sanitized_error = sanitize_error_message(error_message)
        run.status = "failed"
        run.error_message = sanitized_error
        progress = dict(run.progress or {})
        progress["error_message"] = sanitized_error
        progress.setdefault("current_step", "failed")
        run.progress = progress
        if case is not None:
            case.status = "failed"
        self.record_audit(
            action="analysis.fail",
            user_id=user_id,
            target_type="analysis_run",
            target_id=run.id,
            case_id=run.case_id,
            metadata={"error_message": sanitized_error},
        )
        return run

    def list_job_events(
        self,
        *,
        case_id: str | None = None,
        analysis_run_id: str | None = None,
        step_name: str | None = None,
    ) -> list[JobEventRecord]:
        items = list(self.job_events.values())
        if case_id is not None:
            items = [item for item in items if item.case_id == case_id]
        if analysis_run_id is not None:
            items = [item for item in items if item.analysis_run_id == analysis_run_id]
        if step_name is not None:
            items = [item for item in items if item.step_name == step_name]
        return sorted(items, key=lambda item: (item.created_at, item.id))

    def upsert_analysis_step_artifact(
        self,
        *,
        case_id: str,
        analysis_run_id: str,
        step_name: str,
        artifact_type: str,
        object_uri: str,
        sha256: str,
        size_bytes: int,
        metadata: dict[str, Any] | None = None,
    ) -> AnalysisStepArtifactRecord:
        now = datetime.now(UTC)
        key = (analysis_run_id, step_name, artifact_type)
        existing_id = self.analysis_step_artifact_keys.get(key)
        if existing_id is not None:
            record = self.analysis_step_artifacts[existing_id]
            record.object_uri = object_uri
            record.sha256 = sha256
            record.size_bytes = size_bytes
            record.metadata = sanitize_artifact_metadata(metadata)
            record.updated_at = now
            return record
        record = AnalysisStepArtifactRecord(
            id=str(uuid.uuid4()),
            case_id=case_id,
            analysis_run_id=analysis_run_id,
            step_name=step_name,
            artifact_type=artifact_type,
            object_uri=object_uri,
            sha256=sha256,
            size_bytes=size_bytes,
            metadata=sanitize_artifact_metadata(metadata),
            created_at=now,
            updated_at=now,
        )
        self.analysis_step_artifacts[record.id] = record
        self.analysis_step_artifact_keys[key] = record.id
        return record

    def list_analysis_step_artifacts(
        self,
        *,
        case_id: str | None = None,
        analysis_run_id: str | None = None,
        step_name: str | None = None,
    ) -> list[AnalysisStepArtifactRecord]:
        items = list(self.analysis_step_artifacts.values())
        if case_id is not None:
            items = [item for item in items if item.case_id == case_id]
        if analysis_run_id is not None:
            items = [item for item in items if item.analysis_run_id == analysis_run_id]
        if step_name is not None:
            items = [item for item in items if item.step_name == step_name]
        return sorted(items, key=lambda item: (item.created_at, item.step_name, item.id))

    def get_analysis_result(self, case_id: str, run_id: str) -> AnalysisResult | None:
        run = self.runs.get(run_id)
        if not run or run.case_id != case_id:
            return None
        return run.result

    def update_causal_summary(
        self,
        *,
        case_id: str,
        run_id: str,
        summary_markdown: str,
        customer_update_markdown: str | None,
        user_id: str,
    ) -> dict[str, object] | None:
        run = self.runs.get(run_id)
        if not run or run.case_id != case_id or run.result is None:
            return None

        current_summary = run.result.causal_summary
        updated_summary = current_summary.model_copy(
            update={
                "summary_markdown": summary_markdown,
                "customer_update_markdown": (
                    current_summary.customer_update_markdown
                    if customer_update_markdown is None
                    else customer_update_markdown
                ),
                "edited": True,
            }
        )
        updated_result = run.result.model_copy(update={"causal_summary": updated_summary})
        updated_exports = {
            export_type: export_analysis(updated_result, export_type)
            for export_type in ("markdown", "html", "json")
        }
        run.result = updated_result.model_copy(update={"exports": updated_exports})
        self.record_audit(
            action="causal_summary.edit",
            user_id=user_id,
            target_type="causal_summary",
            target_id=run_id,
            case_id=case_id,
            metadata={
                "analysis_run_id": run_id,
                "summary_length": len(summary_markdown),
                "customer_update_length": len(updated_summary.customer_update_markdown),
                "evidence_refs_count": len(updated_summary.evidence_refs),
                "edited": True,
            },
        )
        return run.result.causal_summary.model_dump(mode="json")

    def create_export(
        self,
        *,
        export_id: str,
        case_id: str,
        analysis_run_id: str,
        export_type: str,
        object_uri: str,
        user_id: str,
    ) -> ExportRecord:
        record = self.exports.get(export_id)
        if record is None:
            record = ExportRecord(
                id=export_id,
                case_id=case_id,
                analysis_run_id=analysis_run_id,
                export_type=export_type,
                object_uri=object_uri,
                created_by=user_id,
            )
            self.exports[record.id] = record
            self.record_audit(
                action="export.create",
                user_id=user_id,
                target_type="export",
                target_id=export_id,
                case_id=case_id,
                metadata={"analysis_run_id": analysis_run_id, "export_type": export_type},
            )
        return record

    def get_export(self, export_id: str) -> ExportRecord | None:
        return self.exports.get(export_id)

    def record_feedback(
        self,
        *,
        case_id: str,
        analysis_run_id: str | None,
        user_id: str,
        target_type: str,
        target_id: str | None,
        feedback_type: str,
        rating: int | None,
        comment: str | None,
        corrected_value: dict[str, Any] | None,
    ) -> FeedbackRecord:
        record = FeedbackRecord(
            id=uuid.uuid4().hex,
            case_id=case_id,
            analysis_run_id=analysis_run_id,
            user_id=user_id,
            target_type=target_type,
            target_id=target_id,
            feedback_type=feedback_type,
            rating=rating,
            comment=comment,
            corrected_value=corrected_value,
        )
        self.feedback[record.id] = record
        self.record_audit(
            action="feedback.submit",
            user_id=user_id,
            target_type=target_type,
            target_id=target_id,
            case_id=case_id,
            metadata={"analysis_run_id": analysis_run_id, "feedback_type": feedback_type},
        )
        return record

    def get_feedback(self, feedback_id: str) -> FeedbackRecord | None:
        return self.feedback.get(feedback_id)

    def record_audit(
        self,
        *,
        action: str,
        user_id: str | None = None,
        target_type: str | None = None,
        target_id: str | None = None,
        case_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> AuditLogRecord:
        record = AuditLogRecord(
            id=str(uuid.uuid4()),
            action=action,
            user_id=user_id,
            target_type=target_type,
            target_id=target_id,
            case_id=case_id,
            metadata=metadata or {},
            ip_address=ip_address,
            user_agent=user_agent,
        )
        self.audit_logs[record.id] = record
        return record

    def list_audit_logs(
        self,
        *,
        case_id: str | None = None,
        action: str | None = None,
        user_id: str | None = None,
        offset: int = 0,
        limit: int | None = None,
    ) -> list[AuditLogRecord]:
        items = list(self.audit_logs.values())
        if case_id:
            items = [item for item in items if item.case_id == case_id]
        if action:
            items = [item for item in items if item.action == action]
        if user_id:
            items = [item for item in items if item.user_id == user_id]
        items = sorted(items, key=lambda item: item.created_at)
        return items[offset : offset + limit if limit is not None else None]

    def run_retention(self, *, now: datetime | None = None) -> RetentionResultRecord:
        current_time = now or datetime.now(UTC)
        result = RetentionResultRecord()

        audit_cutoff = current_time.timestamp() - self.settings.audit_retention_days * 86400
        old_audit_ids = [
            audit_id
            for audit_id, audit in self.audit_logs.items()
            if audit.created_at.timestamp() < audit_cutoff
        ]
        for audit_id in old_audit_ids:
            self.audit_logs.pop(audit_id, None)
        result.audit_logs_deleted = len(old_audit_ids)

        raw_cutoff = current_time.timestamp() - self.settings.raw_log_retention_days * 86400
        for run in self.runs.values():
            run_time = run.completed_at or run.started_at or current_time
            if run_time.timestamp() >= raw_cutoff or run.result is None:
                continue
            for raw_entry in run.result.raw_entries:
                if raw_entry.raw_message != RAW_LOG_RETAINED_MARKER:
                    raw_entry.raw_message = RAW_LOG_RETAINED_MARKER
                    result.raw_log_lines_scrubbed += 1
            for file in run.result.files:
                for line in file.lines:
                    line.raw_text = RAW_LOG_RETAINED_MARKER

        report_cutoff = current_time.timestamp() - self.settings.report_retention_days * 86400
        old_export_ids = [
            export_id
            for export_id, export in self.exports.items()
            if export.created_at.timestamp() < report_cutoff
        ]
        for export_id in old_export_ids:
            self.exports.pop(export_id, None)
        result.exports_deleted = len(old_export_ids)

        from app.services.analysis_artifacts import best_effort_delete_step_artifact_object

        old_artifact_ids = [
            artifact_id
            for artifact_id, artifact in self.analysis_step_artifacts.items()
            if artifact.created_at.timestamp() < report_cutoff
        ]
        for artifact_id in old_artifact_ids:
            artifact = self.analysis_step_artifacts.pop(artifact_id, None)
            if artifact is None:
                continue
            self.analysis_step_artifact_keys.pop(
                (artifact.analysis_run_id, artifact.step_name, artifact.artifact_type),
                None,
            )
            best_effort_delete_step_artifact_object(
                artifact.object_uri,
                app_settings=self.settings,
            )
        result.step_artifacts_deleted = len(old_artifact_ids)
        return result


def create_store(app_settings: Settings = settings) -> MetadataStore:
    backend = (app_settings.store_backend or "auto").lower()
    if backend not in {"auto", "memory", "sqlalchemy"}:
        raise ValueError("LOGAN_STORE_BACKEND must be one of: auto, memory, sqlalchemy")
    if backend == "memory":
        return InMemoryStore(app_settings)
    if backend == "sqlalchemy" or (backend == "auto" and app_settings.database_url):
        if not app_settings.database_url:
            raise ValueError("LOGAN_DATABASE_URL is required when LOGAN_STORE_BACKEND=sqlalchemy")
        from app.sqlalchemy_store import SQLAlchemyStore

        return SQLAlchemyStore(app_settings=app_settings, database_url=app_settings.database_url)
    return InMemoryStore(app_settings)
