from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from logan_workers.models import AnalysisResult
from logan_workers.pipeline import AnalyzeCasePipeline

from app.config import Settings, settings
from app.core.security import (
    default_session_expiry,
    encrypt_token,
    hash_password,
    hash_token,
    issue_session_token,
    token_hint,
    verify_password,
)


@dataclass
class UserRecord:
    id: str
    email: str
    username: str
    full_name: str | None
    password_hash: str
    role: str = "engineer"
    is_active: bool = True
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
    runtime_type: str = "github_copilot"
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class CopilotAuthRecord:
    auth_id: str
    user_id: str
    device_code: str
    user_code: str
    verification_uri: str
    verification_uri_complete: str
    expires_in: int
    interval: int
    poll_count: int = 0
    github_base_url: str = "https://github.com"
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))


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
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


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


class MetadataStore(Protocol):
    settings: Settings

    def register_user(
        self, *, email: str, username: str, full_name: str | None, password: str
    ) -> UserRecord: ...

    def authenticate(self, email_or_username: str, password: str) -> UserRecord | None: ...

    def create_session(self, user_id: str) -> tuple[str, SessionRecord]: ...

    def get_user_by_session(self, token: str | None) -> UserRecord | None: ...

    def revoke_session(self, token: str | None) -> None: ...

    def save_credential(
        self, *, user_id: str, credential_type: str, token: str, github_base_url: str
    ) -> CredentialRecord: ...

    def get_credential(
        self, *, user_id: str, credential_type: str
    ) -> CredentialRecord | None: ...

    def has_credential(self, user_id: str) -> bool: ...

    def create_copilot_auth(self, record: CopilotAuthRecord) -> CopilotAuthRecord: ...

    def get_copilot_auth(self, auth_id: str) -> CopilotAuthRecord | None: ...

    def update_copilot_auth(self, record: CopilotAuthRecord) -> CopilotAuthRecord: ...

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

    def create_upload(
        self, *, case_id: str, filename: str, content_type: str | None, size_bytes: int
    ) -> UploadRecord: ...

    def get_upload(self, upload_id: str) -> UploadRecord | None: ...

    def complete_upload(self, *, upload_id: str, sha256: str) -> UploadRecord: ...

    async def start_analysis(
        self,
        *,
        case_id: str,
        user_id: str,
        input_paths: list[str],
        config: dict[str, Any],
        gateway: Any | None = None,
    ) -> AnalysisRunRecord: ...

    def get_analysis_run(self, run_id: str) -> AnalysisRunRecord | None: ...

    def get_analysis_result(self, case_id: str, run_id: str) -> AnalysisResult | None: ...

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
        self, *, case_id: str | None = None, action: str | None = None
    ) -> list[AuditLogRecord]: ...


class InMemoryStore:
    def __init__(self, app_settings: Settings = settings) -> None:
        self.settings = app_settings
        self.users: dict[str, UserRecord] = {}
        self.users_by_email: dict[str, str] = {}
        self.users_by_username: dict[str, str] = {}
        self.sessions_by_hash: dict[str, SessionRecord] = {}
        self.credentials_by_user: dict[tuple[str, str], CredentialRecord] = {}
        self.copilot_auth: dict[str, CopilotAuthRecord] = {}
        self.cases: dict[str, CaseRecord] = {}
        self.uploads: dict[str, UploadRecord] = {}
        self.runs: dict[str, AnalysisRunRecord] = {}
        self.feedback: dict[str, FeedbackRecord] = {}
        self.exports: dict[str, ExportRecord] = {}
        self.audit_logs: dict[str, AuditLogRecord] = {}

    def register_user(
        self, *, email: str, username: str, full_name: str | None, password: str
    ) -> UserRecord:
        if email in self.users_by_email or username in self.users_by_username:
            raise ValueError("user already exists")
        user = UserRecord(
            id=str(uuid.uuid4()),
            email=email,
            username=username,
            full_name=full_name,
            password_hash=hash_password(password),
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
        return self.users.get(session.user_id)

    def revoke_session(self, token: str | None) -> None:
        if not token:
            return
        session = self.sessions_by_hash.get(hash_token(token))
        if session:
            session.revoked_at = datetime.now(UTC)

    def save_credential(
        self,
        *,
        user_id: str,
        credential_type: str,
        token: str,
        github_base_url: str,
    ) -> CredentialRecord:
        record = CredentialRecord(
            id=str(uuid.uuid4()),
            user_id=user_id,
            credential_type=credential_type,
            encrypted_token=encrypt_token(token, self.settings.credential_encryption_key),
            token_hint=token_hint(token),
            github_base_url=github_base_url,
        )
        self.credentials_by_user[(user_id, credential_type)] = record
        return record

    def get_credential(self, *, user_id: str, credential_type: str) -> CredentialRecord | None:
        return self.credentials_by_user.get((user_id, credential_type))

    def has_credential(self, user_id: str) -> bool:
        return any(key_user_id == user_id for key_user_id, _ in self.credentials_by_user)

    def create_copilot_auth(self, record: CopilotAuthRecord) -> CopilotAuthRecord:
        self.copilot_auth[record.auth_id] = record
        return record

    def get_copilot_auth(self, auth_id: str) -> CopilotAuthRecord | None:
        return self.copilot_auth.get(auth_id)

    def update_copilot_auth(self, record: CopilotAuthRecord) -> CopilotAuthRecord:
        record.updated_at = record.updated_at or datetime.now(UTC)
        self.copilot_auth[record.auth_id] = record
        return record

    def create_case(self, *, user_id: str, data: dict[str, Any]) -> CaseRecord:
        case_id = str(uuid.uuid4())
        case_key = f"LOGAN-{datetime.now(UTC):%Y%m%d}-{len(self.cases) + 1:04d}"
        record = CaseRecord(id=case_id, case_key=case_key, created_by=user_id, **data)
        self.cases[case_id] = record
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

    def create_upload(
        self, *, case_id: str, filename: str, content_type: str | None, size_bytes: int
    ) -> UploadRecord:
        upload_id = str(uuid.uuid4())
        record = UploadRecord(
            id=upload_id,
            case_id=case_id,
            filename=filename,
            content_type=content_type,
            size_bytes=size_bytes,
            object_uri=f"memory://uploads/{case_id}/{upload_id}/{filename}",
        )
        self.uploads[upload_id] = record
        if case_id in self.cases:
            self.cases[case_id].status = "uploading"
        return record

    def get_upload(self, upload_id: str) -> UploadRecord | None:
        return self.uploads.get(upload_id)

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
            model_name=config.get("model", {}).get("model", self.settings.copilot_model),
            model_reasoning_effort=config.get("model", {}).get(
                "reasoning_effort", self.settings.copilot_reasoning_effort
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
            run.result = await AnalyzeCasePipeline().run(
                case_id=case_id,
                analysis_run_id=run.id,
                paths=input_paths,
                case_context={
                    "title": case.title,
                    "issue_description": case.issue_description,
                    "product": case.product,
                    "environment": case.environment,
                    "user_id": user_id,
                },
                config=config,
                gateway=gateway,
            )
            run.progress = run.result.progress
            run.status = "completed"
            run.completed_at = datetime.now(UTC)
            case.status = "ready"
            self.record_audit(
                action="analysis.complete",
                user_id=user_id,
                target_type="analysis_run",
                target_id=run.id,
                case_id=case_id,
                metadata={"progress": run.progress},
            )
        except Exception as exc:
            run.status = "failed"
            run.error_message = str(exc)
            case.status = "failed"
            self.record_audit(
                action="analysis.fail",
                user_id=user_id,
                target_type="analysis_run",
                target_id=run.id,
                case_id=case_id,
                metadata={"error_message": str(exc)},
            )
            raise
        return run

    def get_analysis_run(self, run_id: str) -> AnalysisRunRecord | None:
        return self.runs.get(run_id)

    def get_analysis_result(self, case_id: str, run_id: str) -> AnalysisResult | None:
        run = self.runs.get(run_id)
        if not run or run.case_id != case_id:
            return None
        return run.result

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
        self, *, case_id: str | None = None, action: str | None = None
    ) -> list[AuditLogRecord]:
        items = list(self.audit_logs.values())
        if case_id:
            items = [item for item in items if item.case_id == case_id]
        if action:
            items = [item for item in items if item.action == action]
        return sorted(items, key=lambda item: item.created_at)


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
