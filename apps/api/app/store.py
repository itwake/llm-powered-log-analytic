from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

from logan_workers.models import AnalysisResult

from app.config import Settings, settings
from app.services.object_store import S3ClientFactory

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
TERMINAL_ANALYSIS_RUN_STATUSES = frozenset({"completed", "failed", "cancelled"})
CANCELLABLE_ANALYSIS_RUN_STATUSES = frozenset({"queued", "processing"})
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


class AnalysisRunCancelled(RuntimeError):
    pass


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

    def get_user_by_email(self, email: str) -> UserRecord | None: ...

    def get_user_by_username(self, username: str) -> UserRecord | None: ...

    def get_user_by_external_id(self, external_id: str) -> UserRecord | None: ...

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

    def update_case(
        self, *, case_id: str, data: dict[str, Any], user_id: str
    ) -> CaseRecord: ...

    def delete_case(self, *, case_id: str, user_id: str) -> bool: ...

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

    def create_analysis_run(
        self, *, case_id: str, user_id: str, config: dict[str, Any]
    ) -> AnalysisRunRecord: ...

    async def run_analysis(
        self,
        *,
        run_id: str,
        user_id: str,
        input_paths: list[str],
        config: dict[str, Any],
        gateway: Any | None = None,
        s3_client_factory: S3ClientFactory | None = None,
    ) -> AnalysisRunRecord: ...

    def get_analysis_run(self, run_id: str) -> AnalysisRunRecord | None: ...

    def list_analysis_runs(self, case_id: str) -> list[AnalysisRunRecord]: ...

    def cancel_analysis_run(self, *, run_id: str, user_id: str) -> AnalysisRunRecord: ...

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


EPHEMERAL_SQLITE_DATABASE_URL = "sqlite+pysqlite:///:memory:"


def create_ephemeral_store(app_settings: Settings = settings) -> MetadataStore:
    """Create an isolated SQL-backed store for tests and local disposable runs."""
    from app.sqlalchemy_store import SQLAlchemyStore

    return SQLAlchemyStore(
        app_settings=app_settings,
        database_url=EPHEMERAL_SQLITE_DATABASE_URL,
    )


class InMemoryStore:
    """Backward-compatible constructor for the former dictionary-backed store."""

    def __new__(cls, app_settings: Settings = settings) -> MetadataStore:
        return create_ephemeral_store(app_settings)


def create_store(app_settings: Settings = settings) -> MetadataStore:
    backend = (app_settings.store_backend or "auto").lower()
    if backend not in {"auto", "memory", "sqlalchemy"}:
        raise ValueError("LOGAN_STORE_BACKEND must be one of: auto, memory, sqlalchemy")
    if backend == "memory":
        return create_ephemeral_store(app_settings)
    if backend == "sqlalchemy" or (backend == "auto" and app_settings.database_url):
        if not app_settings.database_url:
            raise ValueError("LOGAN_DATABASE_URL is required when LOGAN_STORE_BACKEND=sqlalchemy")
        from app.sqlalchemy_store import SQLAlchemyStore

        return SQLAlchemyStore(app_settings=app_settings, database_url=app_settings.database_url)
    return create_ephemeral_store(app_settings)
