from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

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


class InMemoryStore:
    def __init__(self, app_settings: Settings = settings) -> None:
        self.settings = app_settings
        self.users: dict[str, UserRecord] = {}
        self.users_by_email: dict[str, str] = {}
        self.users_by_username: dict[str, str] = {}
        self.sessions_by_hash: dict[str, SessionRecord] = {}
        self.credentials_by_user: dict[str, CredentialRecord] = {}
        self.copilot_auth: dict[str, CopilotAuthRecord] = {}
        self.cases: dict[str, CaseRecord] = {}
        self.uploads: dict[str, UploadRecord] = {}
        self.runs: dict[str, AnalysisRunRecord] = {}
        self.feedback: dict[str, FeedbackRecord] = {}

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
        self.credentials_by_user[user_id] = record
        return record

    def has_credential(self, user_id: str) -> bool:
        return user_id in self.credentials_by_user

    def create_case(self, *, user_id: str, data: dict[str, Any]) -> CaseRecord:
        case_id = str(uuid.uuid4())
        case_key = f"LOGAN-{datetime.now(UTC):%Y%m%d}-{len(self.cases) + 1:04d}"
        record = CaseRecord(id=case_id, case_key=case_key, created_by=user_id, **data)
        self.cases[case_id] = record
        return record

    def create_upload(self, *, case_id: str, filename: str, content_type: str | None, size_bytes: int) -> UploadRecord:
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
            )
            run.status = "completed"
            run.completed_at = datetime.now(UTC)
            case.status = "ready"
        except Exception as exc:
            run.status = "failed"
            run.error_message = str(exc)
            case.status = "failed"
            raise
        return run


def create_store() -> InMemoryStore:
    return InMemoryStore()
