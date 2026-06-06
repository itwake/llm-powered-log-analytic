from __future__ import annotations

import hashlib
import json
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator

from logan_workers.models import AnalysisResult, OFFENDING_SIGNALS
from logan_workers.pipeline import AnalyzeCasePipeline
from sqlalchemy import create_engine, delete, func, or_, select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

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
from app.db import Base
from app.models import tables
from app.services.analytics_sinks import (
    AnalyticsSinkError,
    AnalyticsSinkPublisher,
    AnalyticsSinkWriteOperation,
    opensearch_index_name,
)
from app.services.analytics_queries import (
    AnalyticsQueryClient,
    AnalyticsQueryError,
    sanitize_analytics_query_error,
)
from app.services.object_store import (
    is_local_backend,
    is_s3_backend,
    local_upload_object_uri,
    s3_upload_object_uri,
    safe_filename,
)
from app.store import (
    AnalysisRunRecord,
    AnalyticsSinkWriteRecord,
    AuditLogRecord,
    CaseRecord,
    CopilotAuthRecord,
    COPILOT_AUTH_CREDENTIAL_TYPES,
    CredentialRecord,
    ExportRecord,
    FeedbackRecord,
    JobEventRecord,
    SessionRecord,
    UploadRecord,
    UserRecord,
    apply_job_event_progress,
    sanitize_error_message,
    sanitize_job_metadata,
    sanitize_workflow_payload,
)


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def _now() -> datetime:
    return datetime.now(UTC)


def _uuid_or_none(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return str(uuid.UUID(value))
    except ValueError:
        return None


def _worker_uuid(value: str | None, fallback_key: str) -> str:
    return _uuid_or_none(value) or str(uuid.uuid5(uuid.NAMESPACE_URL, fallback_key))


def _iso(value: datetime | None) -> str | None:
    return _utc(value).isoformat() if value else None


def _hash_json(value: dict[str, Any], *, prefix: str = "") -> str:
    encoded = json.dumps(value, separators=(",", ":"), sort_keys=True)
    return f"{prefix}{hashlib.sha256(encoded.encode('utf-8')).hexdigest()}"


def _str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if item is not None]


def _entities(value: Any) -> dict[str, list[str]]:
    if not isinstance(value, dict):
        return {}
    entities: dict[str, list[str]] = {}
    for key, raw_values in value.items():
        if isinstance(raw_values, list):
            entities[str(key)] = [str(item) for item in raw_values if item is not None]
        elif raw_values is not None:
            entities[str(key)] = [str(raw_values)]
    return entities


def _entity_values(value: Any) -> list[str]:
    entities = _entities(value)
    return [item for values in entities.values() for item in values]


def _line_numbers(parsed_fields: Any, fallback_line_number: int) -> list[int]:
    if isinstance(parsed_fields, dict) and isinstance(parsed_fields.get("stack_trace_lines"), list):
        values = [int(item) for item in parsed_fields["stack_trace_lines"] if isinstance(item, int)]
        if values:
            return values
    return [fallback_line_number]


def _template_label(template_text: str) -> str:
    return template_text.replace("<*>", "...")[:96]


def _evidence_ref_payload(
    *,
    case_id: str,
    run_id: str,
    template_id: str | None,
    line: tables.NormalizedLogLine,
    raw_line: tables.RawLogLine,
    raw_file: tables.RawFile,
) -> dict[str, object]:
    return {
        "case_id": case_id,
        "analysis_run_id": run_id,
        "template_id": template_id,
        "log_id": line.id,
        "file_path": raw_file.original_filename,
        "line_number": raw_line.line_number,
        "timestamp": _iso(line.timestamp),
    }


def _sqlite_connect_args(database_url: str) -> dict[str, Any]:
    return {"check_same_thread": False} if database_url.startswith("sqlite") else {}


def _sync_database_url(database_url: str) -> str:
    if database_url.startswith("postgresql+asyncpg://"):
        return database_url.replace("postgresql+asyncpg://", "postgresql+psycopg://", 1)
    if database_url.startswith("postgres://"):
        return database_url.replace("postgres://", "postgresql+psycopg://", 1)
    return database_url


class SQLAlchemyStore:
    def __init__(
        self,
        *,
        app_settings: Settings = settings,
        database_url: str,
        engine: Engine | None = None,
        create_schema: bool = True,
        analytics_sink_publisher: Any | None = None,
        analytics_query_client: Any | None = None,
    ) -> None:
        self.settings = app_settings
        self.analytics_sink_publisher = analytics_sink_publisher
        self.analytics_query_client = analytics_query_client
        self.database_url = _sync_database_url(database_url)
        self.engine = engine or create_engine(
            self.database_url,
            future=True,
            connect_args=_sqlite_connect_args(self.database_url),
        )
        self.session_factory = sessionmaker(self.engine, expire_on_commit=False, future=True)
        if create_schema:
            Base.metadata.create_all(self.engine)

    @contextmanager
    def _session(self) -> Iterator[Session]:
        with self.session_factory() as session:
            try:
                yield session
                session.commit()
            except Exception:
                session.rollback()
                raise

    def register_user(
        self, *, email: str, username: str, full_name: str | None, password: str
    ) -> UserRecord:
        user = tables.User(
            id=str(uuid.uuid4()),
            email=email,
            username=username,
            full_name=full_name,
            password_hash=hash_password(password),
            role="engineer",
            is_active=True,
            created_at=_now(),
            updated_at=_now(),
        )
        try:
            with self._session() as session:
                existing = session.scalar(
                    select(tables.User).where(
                        or_(tables.User.email == email, tables.User.username == username)
                    )
                )
                if existing:
                    raise ValueError("user already exists")
                session.add(user)
        except IntegrityError as exc:
            raise ValueError("user already exists") from exc
        return self._user_record(user)

    def authenticate(self, email_or_username: str, password: str) -> UserRecord | None:
        with self._session() as session:
            user = session.scalar(
                select(tables.User).where(
                    or_(
                        tables.User.email == email_or_username,
                        tables.User.username == email_or_username,
                    )
                )
            )
            if not user or not verify_password(password, user.password_hash):
                return None
            return self._user_record(user)

    def create_session(self, user_id: str) -> tuple[str, SessionRecord]:
        token = issue_session_token()
        created_at = _now()
        session_row = tables.Session(
            id=str(uuid.uuid4()),
            user_id=user_id,
            token_hash=hash_token(token),
            expires_at=default_session_expiry(),
            created_at=created_at,
        )
        with self._session() as session:
            session.add(session_row)
        return token, self._session_record(session_row)

    def get_user_by_session(self, token: str | None) -> UserRecord | None:
        if not token:
            return None
        with self._session() as session:
            session_row = session.scalar(
                select(tables.Session).where(tables.Session.token_hash == hash_token(token))
            )
            if (
                not session_row
                or session_row.revoked_at
                or (_utc(session_row.expires_at) or _now()) < _now()
            ):
                return None
            user = session.get(tables.User, session_row.user_id)
            return self._user_record(user) if user else None

    def revoke_session(self, token: str | None) -> None:
        if not token:
            return
        with self._session() as session:
            session_row = session.scalar(
                select(tables.Session).where(tables.Session.token_hash == hash_token(token))
            )
            if session_row:
                session_row.revoked_at = _now()

    def save_credential(
        self,
        *,
        user_id: str,
        credential_type: str,
        token: str,
        github_base_url: str,
        expires_at: datetime | None = None,
    ) -> CredentialRecord:
        encrypted = encrypt_token(token, self.settings.credential_encryption_key)
        hint = token_hint(token)
        credential_expires_at = _utc(expires_at)
        with self._session() as session:
            credential = session.scalar(
                select(tables.CopilotCredential)
                .where(
                    tables.CopilotCredential.user_id == user_id,
                    tables.CopilotCredential.credential_type == credential_type,
                    tables.CopilotCredential.revoked_at.is_(None),
                )
                .order_by(tables.CopilotCredential.created_at.desc())
            )
            if credential is None:
                credential = tables.CopilotCredential(
                    id=str(uuid.uuid4()),
                    user_id=user_id,
                    credential_type=credential_type,
                    encrypted_token=encrypted,
                    token_hint=hint,
                    github_base_url=github_base_url,
                    runtime_type="github_copilot",
                    created_at=_now(),
                    updated_at=_now(),
                    expires_at=credential_expires_at,
                )
                session.add(credential)
            else:
                credential.credential_type = credential_type
                credential.encrypted_token = encrypted
                credential.token_hint = hint
                credential.github_base_url = github_base_url
                credential.runtime_type = "github_copilot"
                credential.expires_at = credential_expires_at
                credential.updated_at = _now()
        return self._credential_record(credential)

    def get_credential(self, *, user_id: str, credential_type: str) -> CredentialRecord | None:
        now = _now()
        with self._session() as session:
            credential = session.scalar(
                select(tables.CopilotCredential)
                .where(
                    tables.CopilotCredential.user_id == user_id,
                    tables.CopilotCredential.credential_type == credential_type,
                    tables.CopilotCredential.revoked_at.is_(None),
                    or_(
                        tables.CopilotCredential.expires_at.is_(None),
                        tables.CopilotCredential.expires_at > now,
                    ),
                )
                .order_by(tables.CopilotCredential.created_at.desc())
            )
            return self._credential_record(credential) if credential else None

    def revoke_credentials(
        self, user_id: str, credential_types: set[str] | list[str] | tuple[str, ...] | None = None
    ) -> int:
        credential_type_filter = set(credential_types) if credential_types is not None else None
        with self._session() as session:
            query = select(tables.CopilotCredential).where(
                tables.CopilotCredential.user_id == user_id,
                tables.CopilotCredential.revoked_at.is_(None),
            )
            if credential_type_filter is not None:
                query = query.where(
                    tables.CopilotCredential.credential_type.in_(credential_type_filter)
                )
            credentials = session.scalars(query).all()
            revoked_at = _now()
            for credential in credentials:
                credential.revoked_at = revoked_at
                credential.updated_at = revoked_at
            return len(credentials)

    def has_credential(self, user_id: str) -> bool:
        now = _now()
        with self._session() as session:
            return (
                session.scalar(
                    select(func.count())
                    .select_from(tables.CopilotCredential)
                    .where(
                        tables.CopilotCredential.user_id == user_id,
                        tables.CopilotCredential.credential_type.in_(
                            COPILOT_AUTH_CREDENTIAL_TYPES
                        ),
                        tables.CopilotCredential.revoked_at.is_(None),
                        or_(
                            tables.CopilotCredential.expires_at.is_(None),
                            tables.CopilotCredential.expires_at > now,
                        ),
                    )
                )
                or 0
            ) > 0

    def create_copilot_auth(self, record: CopilotAuthRecord) -> CopilotAuthRecord:
        with self._session() as session:
            session.add(
                tables.CopilotDeviceAuth(
                    auth_id=record.auth_id,
                    user_id=record.user_id,
                    device_code=record.device_code,
                    user_code=record.user_code,
                    verification_uri=record.verification_uri,
                    verification_uri_complete=record.verification_uri_complete,
                    expires_in=record.expires_in,
                    interval=record.interval,
                    poll_count=record.poll_count,
                    github_base_url=record.github_base_url,
                    created_at=_now(),
                    updated_at=_now(),
                )
            )
        return record

    def get_copilot_auth(self, auth_id: str) -> CopilotAuthRecord | None:
        with self._session() as session:
            row = session.get(tables.CopilotDeviceAuth, auth_id)
            return self._copilot_auth_record(row) if row else None

    def update_copilot_auth(self, record: CopilotAuthRecord) -> CopilotAuthRecord:
        with self._session() as session:
            row = session.get(tables.CopilotDeviceAuth, record.auth_id)
            if row is None:
                raise KeyError(record.auth_id)
            row.poll_count = record.poll_count
            row.github_base_url = record.github_base_url
            row.updated_at = record.updated_at
        return record

    def create_case(self, *, user_id: str, data: dict[str, Any]) -> CaseRecord:
        case_id = str(uuid.uuid4())
        with self._session() as session:
            count = session.scalar(select(func.count()).select_from(tables.Case)) or 0
            case = tables.Case(
                id=case_id,
                case_key=f"LOGAN-{_now():%Y%m%d}-{count + 1:04d}",
                created_by=user_id,
                title=data["title"],
                issue_description=data.get("issue_description"),
                product=data.get("product"),
                service=data.get("service"),
                environment=data.get("environment"),
                incident_start=data.get("incident_start"),
                incident_end=data.get("incident_end"),
                timezone=data.get("timezone") or "UTC",
                status="created",
                created_at=_now(),
                updated_at=_now(),
            )
            session.add(case)
            self._add_audit(
                session,
                action="case.create",
                user_id=user_id,
                target_type="case",
                target_id=case_id,
                case_id=case_id,
            )
        return self._case_record(case)

    def get_case(self, case_id: str) -> CaseRecord | None:
        with self._session() as session:
            case = session.get(tables.Case, case_id)
            return self._case_record(case) if case else None

    def list_cases(
        self,
        *,
        status: str | None = None,
        product: str | None = None,
        offset: int = 0,
        limit: int | None = None,
    ) -> tuple[list[CaseRecord], int]:
        with self._session() as session:
            criteria = []
            if status:
                criteria.append(tables.Case.status == status)
            if product:
                criteria.append(tables.Case.product == product)
            total_query = select(func.count()).select_from(tables.Case)
            items_query = select(tables.Case).order_by(tables.Case.created_at, tables.Case.id)
            if criteria:
                total_query = total_query.where(*criteria)
                items_query = items_query.where(*criteria)
            items_query = items_query.offset(offset)
            if limit is not None:
                items_query = items_query.limit(limit)
            total = session.scalar(total_query) or 0
            rows = session.scalars(items_query).all()
            return [self._case_record(row) for row in rows], total

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
        with self._session() as session:
            upload = tables.RawFile(
                id=upload_id,
                case_id=case_id,
                original_filename=filename,
                object_uri=object_uri,
                content_type=content_type,
                size_bytes=size_bytes,
                sha256=None,
                upload_completed=False,
                upload_metadata={},
                file_role="log",
                created_at=_now(),
            )
            session.add(upload)
            case = session.get(tables.Case, case_id)
            if case:
                case.status = "uploading"
                case.updated_at = _now()
        return self._upload_record(upload)

    def get_upload(self, upload_id: str) -> UploadRecord | None:
        with self._session() as session:
            upload = session.get(tables.RawFile, upload_id)
            return self._upload_record(upload) if upload else None

    def update_upload_metadata(
        self, *, upload_id: str, metadata: dict[str, Any]
    ) -> UploadRecord:
        with self._session() as session:
            upload = session.get(tables.RawFile, upload_id)
            if upload is None:
                raise KeyError(upload_id)
            upload.upload_metadata = dict(metadata)
        return self._upload_record(upload)

    def complete_upload(self, *, upload_id: str, sha256: str) -> UploadRecord:
        with self._session() as session:
            upload = session.get(tables.RawFile, upload_id)
            if upload is None:
                raise KeyError(upload_id)
            upload.sha256 = sha256
            upload.upload_completed = True
        return self._upload_record(upload)

    async def start_analysis(
        self,
        *,
        case_id: str,
        user_id: str,
        input_paths: list[str],
        config: dict[str, Any],
        gateway: Any | None = None,
    ) -> AnalysisRunRecord:
        run = self._create_analysis_run(case_id=case_id, user_id=user_id, config=config)
        case = self.get_case(case_id)
        if case is None:
            raise KeyError(case_id)
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

                self._set_analysis_progress(
                    run_id=run.id,
                    progress={"current_step": "workflow_start", "orchestrator": "temporal"},
                )
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
                return self.get_analysis_run(run.id) or run

            def record_progress(event: dict[str, Any]) -> None:
                job_event = self.record_job_event(
                    case_id=case_id,
                    analysis_run_id=run.id,
                    step_name=str(event["step_name"]),
                    event_type=str(event["event_type"]),
                    status=str(event["status"]),
                    attempt=int(event.get("attempt", 1)),
                    idempotency_key=str(event["idempotency_key"]),
                    metadata=event.get("metadata") if isinstance(event.get("metadata"), dict) else {},
                    error_message=event.get("error_message"),
                )
                self._update_analysis_progress(run_id=run.id, event=job_event)

            result = await AnalyzeCasePipeline().run(
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
                progress_callback=record_progress,
            )
            return self._complete_analysis_run(run_id=run.id, result=result, user_id=user_id)
        except Exception as exc:
            self._fail_analysis_run(
                run_id=run.id,
                error_message=sanitize_error_message(exc),
                user_id=user_id,
            )
            raise

    def get_analysis_run(self, run_id: str) -> AnalysisRunRecord | None:
        with self._session() as session:
            run = session.get(tables.AnalysisRun, run_id)
            return self._analysis_run_record(run) if run else None

    def list_analysis_runs(self, case_id: str) -> list[AnalysisRunRecord]:
        with self._session() as session:
            query = (
                select(tables.AnalysisRun)
                .where(tables.AnalysisRun.case_id == case_id)
                .order_by(tables.AnalysisRun.run_number.desc(), tables.AnalysisRun.created_at.desc())
            )
            return [self._analysis_run_record(row) for row in session.scalars(query).all()]

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
        metadata_json = sanitize_job_metadata(metadata)
        sanitized_error = sanitize_error_message(error_message) if error_message else None
        try:
            with self._session() as session:
                existing = session.scalar(
                    select(tables.JobEvent).where(
                        tables.JobEvent.analysis_run_id == analysis_run_id,
                        tables.JobEvent.idempotency_key == idempotency_key,
                        tables.JobEvent.event_type == event_type,
                    )
                )
                if existing is not None:
                    return self._job_event_record(existing)
                event = tables.JobEvent(
                    id=str(uuid.uuid4()),
                    case_id=case_id,
                    analysis_run_id=analysis_run_id,
                    step_name=step_name,
                    event_type=event_type,
                    status=status,
                    attempt=attempt,
                    idempotency_key=idempotency_key,
                    metadata_json=metadata_json,
                    error_message=sanitized_error,
                    created_at=_now(),
                )
                session.add(event)
                session.flush()
                return self._job_event_record(event)
        except IntegrityError:
            with self._session() as session:
                existing = session.scalar(
                    select(tables.JobEvent).where(
                        tables.JobEvent.analysis_run_id == analysis_run_id,
                        tables.JobEvent.idempotency_key == idempotency_key,
                        tables.JobEvent.event_type == event_type,
                    )
                )
                if existing is not None:
                    return self._job_event_record(existing)
            raise

    def apply_analysis_job_event(
        self, *, run_id: str, event: dict[str, Any]
    ) -> JobEventRecord:
        run = self.get_analysis_run(run_id)
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
        self._update_analysis_progress(run_id=run.id, event=job_event)
        return job_event

    def complete_analysis_run(
        self, *, run_id: str, result: AnalysisResult, user_id: str
    ) -> AnalysisRunRecord:
        run = self.get_analysis_run(run_id)
        if run is None:
            raise KeyError(run_id)
        if run.status == "completed" and run.result is not None:
            return run
        return self._complete_analysis_run(run_id=run_id, result=result, user_id=user_id)

    def fail_analysis_run(
        self, *, run_id: str, error_message: str, user_id: str
    ) -> AnalysisRunRecord:
        return self._fail_analysis_run(
            run_id=run_id,
            error_message=sanitize_error_message(error_message),
            user_id=user_id,
        )

    def list_job_events(
        self,
        *,
        case_id: str | None = None,
        analysis_run_id: str | None = None,
        step_name: str | None = None,
    ) -> list[JobEventRecord]:
        with self._session() as session:
            query = select(tables.JobEvent)
            if case_id is not None:
                query = query.where(tables.JobEvent.case_id == case_id)
            if analysis_run_id is not None:
                query = query.where(tables.JobEvent.analysis_run_id == analysis_run_id)
            if step_name is not None:
                query = query.where(tables.JobEvent.step_name == step_name)
            query = query.order_by(tables.JobEvent.created_at, tables.JobEvent.id)
            return [self._job_event_record(row) for row in session.scalars(query).all()]

    def list_analytics_sink_writes(
        self,
        *,
        case_id: str | None = None,
        analysis_run_id: str | None = None,
        sink_name: str | None = None,
    ) -> list[AnalyticsSinkWriteRecord]:
        with self._session() as session:
            query = select(tables.AnalyticsSinkWrite)
            if case_id is not None:
                query = query.where(tables.AnalyticsSinkWrite.case_id == case_id)
            if analysis_run_id is not None:
                query = query.where(
                    tables.AnalyticsSinkWrite.analysis_run_id == analysis_run_id
                )
            if sink_name is not None:
                query = query.where(tables.AnalyticsSinkWrite.sink_name == sink_name)
            query = query.order_by(
                tables.AnalyticsSinkWrite.created_at,
                tables.AnalyticsSinkWrite.id,
            )
            return [
                self._analytics_sink_write_record(row)
                for row in session.scalars(query).all()
            ]

    def _succeeded_analytics_sink_write_exists(
        self,
        *,
        case_id: str,
        run_id: str,
        sink_name: str,
        destination: str,
    ) -> bool:
        with self._session() as session:
            write_id = session.scalar(
                select(tables.AnalyticsSinkWrite.id)
                .where(
                    tables.AnalyticsSinkWrite.case_id == case_id,
                    tables.AnalyticsSinkWrite.analysis_run_id == run_id,
                    tables.AnalyticsSinkWrite.sink_name == sink_name,
                    tables.AnalyticsSinkWrite.destination == destination,
                    tables.AnalyticsSinkWrite.status == "succeeded",
                )
                .limit(1)
            )
            return bool(write_id)

    def _record_analytics_query_failure(
        self,
        *,
        case_id: str,
        run_id: str,
        report_name: str,
        sink_name: str,
        error: AnalyticsQueryError,
    ) -> None:
        sanitized_error = sanitize_error_message(sanitize_analytics_query_error(error))
        self.record_audit(
            action="analytics_query.failed",
            target_type="analysis_run",
            target_id=run_id,
            case_id=case_id,
            metadata={
                "analysis_run_id": run_id,
                "case_id": case_id,
                "error": sanitized_error,
                "report": report_name,
                "sink_name": sink_name,
            },
        )

    def _external_analytics_query_client(self) -> Any:
        if self.analytics_query_client is None:
            self.analytics_query_client = AnalyticsQueryClient.from_settings(self.settings)
        return self.analytics_query_client

    def _try_external_temporal_report(
        self,
        *,
        case_id: str,
        run_id: str,
        group_by: str,
    ) -> dict[str, object] | None:
        if not self.settings.external_analytics_queries_enabled:
            return None
        if not self.settings.clickhouse_url:
            return None
        destination = f"{self.settings.clickhouse_database}.window_aggregates"
        if not self._succeeded_analytics_sink_write_exists(
            case_id=case_id,
            run_id=run_id,
            sink_name="clickhouse",
            destination=destination,
        ):
            return None

        try:
            return self._external_analytics_query_client().query_temporal(
                case_id=case_id,
                run_id=run_id,
                group_by=group_by,
            )
        except AnalyticsQueryError as exc:
            self._record_analytics_query_failure(
                case_id=case_id,
                run_id=run_id,
                report_name="temporal",
                sink_name="clickhouse",
                error=exc,
            )
            return None

    def _try_external_logs_report(
        self,
        *,
        case_id: str,
        run_id: str,
        window_start: datetime | None,
        window_end: datetime | None,
        q: str | None,
        service: str | None,
        limit: int,
        offset: int,
    ) -> dict[str, object] | None:
        if not self.settings.external_analytics_queries_enabled:
            return None
        if not self.settings.opensearch_url:
            return None
        destination = f"{opensearch_index_name(case_id, run_id)}/_bulk"
        if not self._succeeded_analytics_sink_write_exists(
            case_id=case_id,
            run_id=run_id,
            sink_name="opensearch",
            destination=destination,
        ):
            return None

        try:
            return self._external_analytics_query_client().query_logs(
                case_id=case_id,
                run_id=run_id,
                window_start=window_start,
                window_end=window_end,
                q=q,
                service=service,
                limit=limit,
                offset=offset,
            )
        except AnalyticsQueryError as exc:
            self._record_analytics_query_failure(
                case_id=case_id,
                run_id=run_id,
                report_name="logs",
                sink_name="opensearch",
                error=exc,
            )
            return None

    def get_analysis_result(self, case_id: str, run_id: str) -> AnalysisResult | None:
        with self._session() as session:
            run = session.get(tables.AnalysisRun, run_id)
            if not run or run.case_id != case_id or not run.result_json:
                return None
            return AnalysisResult.model_validate(run.result_json)

    def get_report_summary(
        self,
        *,
        case_id: str,
        run_id: str,
        golden_signal: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, object] | None:
        with self._session() as session:
            rows = session.execute(
                select(tables.LogTemplate, tables.TemplateAnnotation)
                .join(
                    tables.TemplateAnnotation,
                    tables.TemplateAnnotation.template_id == tables.LogTemplate.id,
                )
                .where(
                    tables.LogTemplate.case_id == case_id,
                    tables.LogTemplate.analysis_run_id == run_id,
                    tables.TemplateAnnotation.analysis_run_id == run_id,
                )
            ).all()
            if not rows:
                return None

            template_ids = [template.id for template, _annotation in rows]
            sample_lines: dict[str, tuple[tables.RepresentativeSample, tables.NormalizedLogLine]] = {}
            if template_ids:
                for sample, line in session.execute(
                    select(tables.RepresentativeSample, tables.NormalizedLogLine)
                    .join(
                        tables.NormalizedLogLine,
                        tables.RepresentativeSample.log_id == tables.NormalizedLogLine.id,
                    )
                    .where(tables.RepresentativeSample.template_id.in_(template_ids))
                    .order_by(
                        tables.RepresentativeSample.template_id,
                        tables.RepresentativeSample.sample_rank,
                        tables.RepresentativeSample.id,
                    )
                ).all():
                    sample_lines.setdefault(sample.template_id, (sample, line))

            representative_ids = {
                template.representative_log_id
                for template, _annotation in rows
                if template.representative_log_id
            }
            representative_lines = (
                {
                    line.id: line
                    for line in session.scalars(
                        select(tables.NormalizedLogLine).where(
                            tables.NormalizedLogLine.id.in_(representative_ids)
                        )
                    ).all()
                }
                if representative_ids
                else {}
            )

            items: list[dict[str, object]] = []
            for template, annotation in rows:
                if golden_signal and annotation.golden_signal != golden_signal:
                    continue
                if not golden_signal and annotation.golden_signal not in OFFENDING_SIGNALS:
                    continue

                sample_with_line = sample_lines.get(template.id)
                sample = sample_with_line[0] if sample_with_line else None
                sample_line = sample_with_line[1] if sample_with_line else None
                representative_line = representative_lines.get(template.representative_log_id or "")
                representative_log_id = (
                    sample.log_id if sample else template.representative_log_id
                )
                representative_message = (
                    sample_line.redacted_message
                    if sample_line
                    else representative_line.redacted_message
                    if representative_line
                    else template.template_text
                )
                items.append(
                    {
                        "template_id": template.id,
                        "representative_log_id": representative_log_id,
                        "template_text": template.template_text,
                        "representative_message": representative_message,
                        "golden_signal": annotation.golden_signal,
                        "fault_categories": _str_list(annotation.fault_categories),
                        "entities": _entities(annotation.entities),
                        "occurrence_count": template.occurrence_count,
                        "first_seen": _iso(template.first_seen),
                        "last_seen": _iso(template.last_seen),
                        "files": _str_list(template.files),
                        "services": _str_list(template.services),
                        "severity_score": annotation.severity_score,
                        "confidence": annotation.confidence,
                    }
                )

            items.sort(key=lambda item: (-float(item["severity_score"]), item["first_seen"] or ""))
            raw_count = (
                session.scalar(
                    select(func.count())
                    .select_from(tables.RawLogLine)
                    .where(
                        tables.RawLogLine.case_id == case_id,
                        tables.RawLogLine.analysis_run_id == run_id,
                    )
                )
                or 0
            )
            total = len(items)
            safe_offset = max(0, offset)
            safe_limit = max(0, limit)
            return {
                "items": items[safe_offset : safe_offset + safe_limit],
                "total": total,
                "reduction": {
                    "raw_log_lines": raw_count,
                    "offending_templates": total,
                    "estimated_review_reduction": 1 - (total / raw_count) if raw_count else 0,
                },
            }

    def get_report_temporal(
        self,
        *,
        case_id: str,
        run_id: str,
        group_by: str = "golden_signal",
    ) -> dict[str, object] | None:
        external_report = self._try_external_temporal_report(
            case_id=case_id,
            run_id=run_id,
            group_by=group_by,
        )
        if external_report is not None:
            return external_report

        with self._session() as session:
            rows = session.scalars(
                select(tables.TimeWindowSignal)
                .where(
                    tables.TimeWindowSignal.case_id == case_id,
                    tables.TimeWindowSignal.analysis_run_id == run_id,
                )
                .order_by(
                    tables.TimeWindowSignal.window_start,
                    tables.TimeWindowSignal.golden_signal,
                    tables.TimeWindowSignal.service,
                    tables.TimeWindowSignal.template_id,
                )
            ).all()
            if not rows:
                return None

            grouped: dict[str, dict[str, int]] = {}
            for row in rows:
                if group_by == "service":
                    name = row.service or "unknown"
                elif group_by == "fault_category":
                    name = row.fault_category or "unknown"
                elif group_by == "template":
                    name = row.template_id or "unknown"
                else:
                    name = row.golden_signal
                points = grouped.setdefault(name, {})
                window_start = _iso(row.window_start) or ""
                points[window_start] = points.get(window_start, 0) + row.count

            return {
                "window_size_seconds": rows[0].window_size_seconds,
                "series": [
                    {
                        "name": name,
                        "points": [
                            {"window_start": window_start, "count": count}
                            for window_start, count in sorted(points.items())
                        ],
                    }
                    for name, points in sorted(grouped.items())
                ],
            }

    def get_report_logs(
        self,
        *,
        case_id: str,
        run_id: str,
        window_start: datetime | None = None,
        window_end: datetime | None = None,
        q: str | None = None,
        service: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> dict[str, object] | None:
        external_report = self._try_external_logs_report(
            case_id=case_id,
            run_id=run_id,
            window_start=window_start,
            window_end=window_end,
            q=q,
            service=service,
            limit=limit,
            offset=offset,
        )
        if external_report is not None:
            return external_report

        with self._session() as session:
            has_rows = (
                session.scalar(
                    select(func.count())
                    .select_from(tables.NormalizedLogLine)
                    .where(
                        tables.NormalizedLogLine.case_id == case_id,
                        tables.NormalizedLogLine.analysis_run_id == run_id,
                    )
                )
                or 0
            )
            if not has_rows:
                return None

            query = (
                select(
                    tables.NormalizedLogLine,
                    tables.RawLogLine,
                    tables.RawFile,
                    tables.LogTemplate,
                    tables.TemplateAnnotation,
                )
                .join(
                    tables.RawLogLine,
                    tables.NormalizedLogLine.raw_log_id == tables.RawLogLine.id,
                )
                .join(tables.RawFile, tables.RawLogLine.file_id == tables.RawFile.id)
                .outerjoin(
                    tables.LogTemplate,
                    tables.NormalizedLogLine.template_id == tables.LogTemplate.id,
                )
                .outerjoin(
                    tables.TemplateAnnotation,
                    tables.TemplateAnnotation.template_id == tables.NormalizedLogLine.template_id,
                )
                .where(
                    tables.NormalizedLogLine.case_id == case_id,
                    tables.NormalizedLogLine.analysis_run_id == run_id,
                )
                .order_by(
                    tables.NormalizedLogLine.timestamp.is_(None),
                    tables.NormalizedLogLine.timestamp,
                    tables.RawFile.original_filename,
                    tables.RawLogLine.line_number,
                    tables.NormalizedLogLine.id,
                )
            )
            if window_start:
                query = query.where(tables.NormalizedLogLine.timestamp >= window_start)
            if window_end:
                query = query.where(tables.NormalizedLogLine.timestamp <= window_end)
            if service:
                query = query.where(tables.NormalizedLogLine.service == service)

            rows = list(session.execute(query).all())
            if q:
                lowered = q.lower()

                def matches(row: Any) -> bool:
                    line, _raw_line, _raw_file, template, annotation = row
                    template_text = template.template_text if template else ""
                    entities = annotation.entities if annotation else {}
                    return (
                        lowered in line.redacted_message.lower()
                        or lowered in template_text.lower()
                        or any(lowered in value.lower() for value in _entity_values(entities))
                    )

                rows = [row for row in rows if matches(row)]

            service_counts: dict[str, int] = {}
            signal_counts: dict[str, int] = {}
            category_counts: dict[str, int] = {}
            for line, _raw_line, _raw_file, _template, annotation in rows:
                service_key = line.service or "unknown"
                signal_key = annotation.golden_signal if annotation else "unknown"
                service_counts[service_key] = service_counts.get(service_key, 0) + 1
                signal_counts[signal_key] = signal_counts.get(signal_key, 0) + 1
                for category in _str_list(annotation.fault_categories if annotation else []):
                    category_counts[category] = category_counts.get(category, 0) + 1

            safe_offset = max(0, offset)
            safe_limit = max(0, limit)
            paged_rows = rows[safe_offset : safe_offset + safe_limit]
            return {
                "items": [
                    {
                        "log_id": line.id,
                        "timestamp": _iso(line.timestamp),
                        "level": line.level,
                        "service": line.service,
                        "file_path": raw_file.original_filename,
                        "line_number": raw_line.line_number,
                        "line_numbers": _line_numbers(
                            line.parsed_fields,
                            raw_line.line_number,
                        ),
                        "message": line.redacted_message,
                        "template_id": line.template_id,
                        "template_text": template.template_text if template else None,
                        "golden_signal": annotation.golden_signal if annotation else "unknown",
                        "fault_categories": _str_list(
                            annotation.fault_categories if annotation else []
                        ),
                        "entities": _entities(annotation.entities if annotation else {}),
                    }
                    for line, raw_line, raw_file, template, annotation in paged_rows
                ],
                "total": len(rows),
                "facets": {
                    "service": [
                        {"value": value, "count": count}
                        for value, count in sorted(service_counts.items())
                    ],
                    "golden_signal": [
                        {"value": value, "count": count}
                        for value, count in sorted(signal_counts.items())
                    ],
                    "fault_category": [
                        {"value": value, "count": count}
                        for value, count in sorted(category_counts.items())
                    ],
                },
            }

    def get_report_causal_graph(
        self,
        *,
        case_id: str,
        run_id: str,
        max_nodes: int = 100,
        min_confidence: float = 0.0,
    ) -> dict[str, object] | None:
        with self._session() as session:
            node_rows = session.execute(
                select(tables.CausalNode, tables.LogTemplate, tables.TemplateAnnotation)
                .join(tables.LogTemplate, tables.CausalNode.template_id == tables.LogTemplate.id)
                .outerjoin(
                    tables.TemplateAnnotation,
                    tables.TemplateAnnotation.template_id == tables.CausalNode.template_id,
                )
                .where(
                    tables.CausalNode.case_id == case_id,
                    tables.CausalNode.analysis_run_id == run_id,
                )
                .order_by(
                    tables.CausalNode.first_seen.is_(None),
                    tables.CausalNode.first_seen,
                    tables.LogTemplate.template_text,
                    tables.CausalNode.id,
                )
            ).all()
            if not node_rows:
                return None

            evidence_refs = self._evidence_refs_by_template(
                session=session,
                case_id=case_id,
                run_id=run_id,
                template_ids=[node.template_id for node, _template, _annotation in node_rows],
            )
            nodes = [
                {
                    "id": node.id,
                    "label": _template_label(template.template_text),
                    "template_id": node.template_id,
                    "golden_signal": node.golden_signal
                    or (annotation.golden_signal if annotation else "unknown"),
                    "fault_categories": _str_list(
                        node.fault_categories
                        or (annotation.fault_categories if annotation else [])
                    ),
                    "occurrence_count": node.occurrence_count,
                    "first_seen": _iso(node.first_seen),
                    "last_seen": _iso(node.last_seen),
                    "rank_score": node.rank_score,
                    "pagerank_score": node.pagerank_score,
                    "confidence": annotation.confidence if annotation else 0.0,
                    "evidence_refs": evidence_refs.get(node.template_id, []),
                }
                for node, template, annotation in node_rows
            ]
            safe_max_nodes = max(0, max_nodes)
            returned_nodes = nodes[:safe_max_nodes]
            node_id_by_template = {
                str(node["template_id"]): str(node["id"]) for node in returned_nodes
            }

            edge_rows = session.scalars(
                select(tables.CausalEdge)
                .where(
                    tables.CausalEdge.case_id == case_id,
                    tables.CausalEdge.analysis_run_id == run_id,
                    tables.CausalEdge.confidence >= min_confidence,
                )
                .order_by(
                    tables.CausalEdge.confidence.desc(),
                    tables.CausalEdge.lag_seconds,
                    tables.CausalEdge.id,
                )
            ).all()
            edges = []
            for edge in edge_rows:
                source = node_id_by_template.get(edge.source_template_id)
                target = node_id_by_template.get(edge.target_template_id)
                if not source or not target:
                    continue
                edges.append(
                    {
                        "id": edge.id,
                        "source": source,
                        "target": target,
                        "source_template_id": edge.source_template_id,
                        "target_template_id": edge.target_template_id,
                        "edge_type": edge.edge_type,
                        "method": edge.method,
                        "lag_seconds": edge.lag_seconds,
                        "support_windows": edge.support_windows,
                        "confidence": edge.confidence,
                        "p_value_adj": edge.p_value_adj,
                        "lift": edge.lift,
                        "temporal_precedence_score": edge.temporal_precedence_score,
                        "correlation_score": edge.correlation_score,
                        "evidence": edge.evidence or {},
                        "needs_validation": True,
                    }
                )

            ranked_nodes = sorted(nodes, key=lambda node: float(node["rank_score"]), reverse=True)
            return {
                "nodes": returned_nodes,
                "edges": edges,
                "root_cause_candidates": [
                    {
                        "template_id": node["template_id"],
                        "rank": index + 1,
                        "score": node["rank_score"],
                        "reason": (
                            "High PageRank/early occurrence/outgoing candidate edges; "
                            "needs validation."
                        ),
                    }
                    for index, node in enumerate(ranked_nodes[:5])
                ],
            }

    def get_report_causal_summary(
        self, *, case_id: str, run_id: str
    ) -> dict[str, object] | None:
        with self._session() as session:
            row = session.scalar(
                select(tables.CausalSummary)
                .where(
                    tables.CausalSummary.case_id == case_id,
                    tables.CausalSummary.analysis_run_id == run_id,
                )
                .order_by(tables.CausalSummary.created_at.desc(), tables.CausalSummary.id)
            )
            if not row:
                return None
            return {
                "summary_markdown": row.summary_markdown,
                "customer_update_markdown": row.customer_update_markdown,
                "next_actions": list(row.next_actions_json or []),
                "evidence_refs": list(row.evidence_refs_json or []),
                "confidence": row.confidence,
                "edited": bool(row.edited_by or row.edited_at),
            }

    def _evidence_refs_by_template(
        self,
        *,
        session: Session,
        case_id: str,
        run_id: str,
        template_ids: list[str],
    ) -> dict[str, list[dict[str, object]]]:
        if not template_ids:
            return {}

        refs: dict[str, list[dict[str, object]]] = {}
        sample_rows = session.execute(
            select(
                tables.RepresentativeSample.template_id,
                tables.NormalizedLogLine,
                tables.RawLogLine,
                tables.RawFile,
            )
            .join(
                tables.NormalizedLogLine,
                tables.RepresentativeSample.log_id == tables.NormalizedLogLine.id,
            )
            .join(tables.RawLogLine, tables.NormalizedLogLine.raw_log_id == tables.RawLogLine.id)
            .join(tables.RawFile, tables.RawLogLine.file_id == tables.RawFile.id)
            .where(tables.RepresentativeSample.template_id.in_(template_ids))
            .order_by(
                tables.RepresentativeSample.template_id,
                tables.RepresentativeSample.sample_rank,
                tables.RepresentativeSample.id,
            )
        ).all()
        for template_id, line, raw_line, raw_file in sample_rows:
            refs.setdefault(
                template_id,
                [
                    _evidence_ref_payload(
                        case_id=case_id,
                        run_id=run_id,
                        template_id=template_id,
                        line=line,
                        raw_line=raw_line,
                        raw_file=raw_file,
                    )
                ],
            )

        missing_template_ids = [template_id for template_id in template_ids if template_id not in refs]
        if missing_template_ids:
            fallback_rows = session.execute(
                select(tables.NormalizedLogLine, tables.RawLogLine, tables.RawFile)
                .join(
                    tables.RawLogLine,
                    tables.NormalizedLogLine.raw_log_id == tables.RawLogLine.id,
                )
                .join(tables.RawFile, tables.RawLogLine.file_id == tables.RawFile.id)
                .where(tables.NormalizedLogLine.template_id.in_(missing_template_ids))
                .order_by(
                    tables.NormalizedLogLine.template_id,
                    tables.NormalizedLogLine.timestamp.is_(None),
                    tables.NormalizedLogLine.timestamp,
                    tables.RawFile.original_filename,
                    tables.RawLogLine.line_number,
                    tables.NormalizedLogLine.id,
                )
            ).all()
            for line, raw_line, raw_file in fallback_rows:
                if not line.template_id or line.template_id in refs:
                    continue
                refs[line.template_id] = [
                    _evidence_ref_payload(
                        case_id=case_id,
                        run_id=run_id,
                        template_id=line.template_id,
                        line=line,
                        raw_line=raw_line,
                        raw_file=raw_file,
                    )
                ]
        return refs

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
        with self._session() as session:
            export = session.get(tables.Export, export_id)
            if export is None:
                export = tables.Export(
                    id=export_id,
                    case_id=case_id,
                    analysis_run_id=analysis_run_id,
                    export_type=export_type,
                    object_uri=object_uri,
                    created_by=user_id,
                    created_at=_now(),
                )
                session.add(export)
                self._add_audit(
                    session,
                    action="export.create",
                    user_id=user_id,
                    target_type="export",
                    target_id=export_id,
                    case_id=case_id,
                    metadata={"analysis_run_id": analysis_run_id, "export_type": export_type},
                )
        return self._export_record(export)

    def get_export(self, export_id: str) -> ExportRecord | None:
        with self._session() as session:
            export = session.get(tables.Export, export_id)
            return self._export_record(export) if export else None

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
        with self._session() as session:
            feedback = tables.Feedback(
                id=uuid.uuid4().hex,
                case_id=case_id,
                analysis_run_id=analysis_run_id,
                user_id=user_id,
                target_type=target_type,
                target_id=target_id,
                feedback_type=feedback_type,
                rating=rating,
                comment=comment,
                corrected_value=corrected_value or {},
                created_at=_now(),
            )
            session.add(feedback)
            self._add_audit(
                session,
                action="feedback.submit",
                user_id=user_id,
                target_type=target_type,
                target_id=target_id,
                case_id=case_id,
                metadata={"analysis_run_id": analysis_run_id, "feedback_type": feedback_type},
            )
        return self._feedback_record(feedback)

    def get_feedback(self, feedback_id: str) -> FeedbackRecord | None:
        with self._session() as session:
            feedback = session.get(tables.Feedback, feedback_id)
            return self._feedback_record(feedback) if feedback else None

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
        with self._session() as session:
            audit = self._add_audit(
                session,
                action=action,
                user_id=user_id,
                target_type=target_type,
                target_id=target_id,
                case_id=case_id,
                metadata=metadata,
                ip_address=ip_address,
                user_agent=user_agent,
            )
        return self._audit_record(audit)

    def list_audit_logs(
        self, *, case_id: str | None = None, action: str | None = None
    ) -> list[AuditLogRecord]:
        with self._session() as session:
            query = select(tables.AuditLog).order_by(tables.AuditLog.created_at, tables.AuditLog.id)
            if case_id:
                query = query.where(tables.AuditLog.case_id == case_id)
            if action:
                query = query.where(tables.AuditLog.action == action)
            return [self._audit_record(row) for row in session.scalars(query).all()]

    def _create_analysis_run(
        self, *, case_id: str, user_id: str, config: dict[str, Any]
    ) -> AnalysisRunRecord:
        with self._session() as session:
            case = session.get(tables.Case, case_id)
            if case is None:
                raise KeyError(case_id)
            run_number = (
                session.scalar(
                    select(func.count())
                    .select_from(tables.AnalysisRun)
                    .where(tables.AnalysisRun.case_id == case_id)
                )
                or 0
            ) + 1
            run = tables.AnalysisRun(
                id=str(uuid.uuid4()),
                case_id=case_id,
                run_number=run_number,
                status="processing",
                config_json=config,
                model_provider=self.settings.llm_provider,
                model_name=config.get("model", {}).get("model", self.settings.copilot_model),
                model_reasoning_effort=config.get("model", {}).get(
                    "reasoning_effort", self.settings.copilot_reasoning_effort
                ),
                prompt_version="annotation_v1",
                drain_config_json={},
                causal_config_json={},
                progress_json={},
                started_at=_now(),
                created_by=user_id,
                created_at=_now(),
            )
            session.add(run)
            case.status = "processing"
            case.updated_at = _now()
            self._add_audit(
                session,
                action="analysis.start",
                user_id=user_id,
                target_type="analysis_run",
                target_id=run.id,
                case_id=case_id,
            )
        return self._analysis_run_record(run)

    def _update_analysis_progress(self, *, run_id: str, event: JobEventRecord) -> None:
        with self._session() as session:
            run = session.get(tables.AnalysisRun, run_id)
            if run is None:
                raise KeyError(run_id)
            run.progress_json = apply_job_event_progress(run.progress_json, event)

    def _set_analysis_progress(self, *, run_id: str, progress: dict[str, Any]) -> None:
        with self._session() as session:
            run = session.get(tables.AnalysisRun, run_id)
            if run is None:
                raise KeyError(run_id)
            run.progress_json = progress

    def _complete_analysis_run(
        self, *, run_id: str, result: AnalysisResult, user_id: str
    ) -> AnalysisRunRecord:
        result_json = result.model_dump(mode="json")
        result_json["model_inputs"] = []
        with self._session() as session:
            run = session.get(tables.AnalysisRun, run_id)
            if run is None:
                raise KeyError(run_id)
            run.error_message = None
            run.progress_json = result.progress
            run.result_json = result_json
            self._fan_out_analysis_result(session=session, run=run, result=result)

        self._publish_analytics_sinks(
            run_id=run_id,
            result=result,
            user_id=user_id,
        )

        with self._session() as session:
            run = session.get(tables.AnalysisRun, run_id)
            if run is None:
                raise KeyError(run_id)
            case = session.get(tables.Case, run.case_id)
            run.status = "completed"
            run.completed_at = _now()
            run.error_message = None
            run.progress_json = result.progress
            if case:
                case.status = "ready"
                case.updated_at = _now()
            self._add_audit(
                session,
                action="analysis.complete",
                user_id=user_id,
                target_type="analysis_run",
                target_id=run.id,
                case_id=run.case_id,
                metadata={"progress": result.progress},
            )
        return self._analysis_run_record(run)

    def _publish_analytics_sinks(
        self,
        *,
        run_id: str,
        result: AnalysisResult,
        user_id: str,
    ) -> None:
        if not self.settings.analytics_sinks_enabled:
            return
        if not (self.settings.clickhouse_url or self.settings.opensearch_url):
            return

        publisher = self.analytics_sink_publisher or AnalyticsSinkPublisher.from_settings(
            self.settings
        )
        if hasattr(publisher, "publish_operations"):
            operations = list(publisher.publish_operations(result))
        else:
            operations = [self._legacy_analytics_sink_operation(publisher, result)]
        if not operations:
            return

        failure_mode = self.settings.analytics_sink_failure_mode.lower()
        metadata: dict[str, int] = {
            "clickhouse_enriched_log_rows": 0,
            "clickhouse_window_rows": 0,
            "opensearch_documents": 0,
            "succeeded_writes": 0,
            "failed_writes": 0,
            "skipped_writes": 0,
        }

        for operation in operations:
            record, skipped = self._prepare_analytics_sink_write(operation)
            if skipped:
                metadata["skipped_writes"] += 1
                continue
            try:
                operation.execute()
            except AnalyticsSinkError as exc:
                sanitized_error = sanitize_error_message(exc)
                self._mark_analytics_sink_write_failed(
                    write_id=record.id,
                    error_message=sanitized_error,
                )
                metadata["failed_writes"] += 1
                self.record_audit(
                    action="analytics_sink.publish_failed",
                    user_id=user_id,
                    target_type="analysis_run",
                    target_id=run_id,
                    case_id=operation.case_id,
                    metadata={
                        "destination": operation.destination,
                        "error": sanitized_error,
                        "failure_mode": failure_mode,
                        "idempotency_key": operation.idempotency_key,
                        "sink_name": operation.sink_name,
                    },
                )
                if failure_mode == "fail":
                    raise
                continue

            self._mark_analytics_sink_write_succeeded(
                write_id=record.id,
                row_count=operation.row_count,
            )
            metadata["succeeded_writes"] += 1
            self._add_analytics_sink_count(metadata, operation)

        self.record_audit(
            action="analytics_sink.publish",
            user_id=user_id,
            target_type="analysis_run",
            target_id=run_id,
            case_id=result.case_id,
            metadata=metadata,
        )

    def _legacy_analytics_sink_operation(
        self, publisher: Any, result: AnalysisResult
    ) -> AnalyticsSinkWriteOperation:
        sink_name = "clickhouse" if self.settings.clickhouse_url else "opensearch"
        destinations: list[str] = []
        if self.settings.clickhouse_url:
            destinations.append(f"{self.settings.clickhouse_database}.*")
        if self.settings.opensearch_url:
            destinations.append("opensearch/_bulk")
        destination = "+".join(destinations) or "external"
        payload_hash = _hash_json(
            {
                "normalized_logs": len(result.normalized_logs),
                "temporal_windows": len(result.temporal),
                "sink_name": sink_name,
                "destination": destination,
            }
        )
        idempotency_key = _hash_json(
            {
                "analysis_run_id": result.analysis_run_id,
                "case_id": result.case_id,
                "destination": destination,
                "payload_hash": payload_hash,
                "sink_name": sink_name,
            },
            prefix="analytics-sink:",
        )

        def publish_legacy() -> None:
            publisher.publish(result)

        return AnalyticsSinkWriteOperation(
            case_id=result.case_id,
            analysis_run_id=result.analysis_run_id,
            sink_name=sink_name,
            destination=destination,
            idempotency_key=idempotency_key,
            payload_hash=payload_hash,
            row_count=0,
            _publish=publish_legacy,
        )

    def _prepare_analytics_sink_write(
        self, operation: AnalyticsSinkWriteOperation
    ) -> tuple[AnalyticsSinkWriteRecord, bool]:
        now = _now()
        with self._session() as session:
            row = session.scalar(
                select(tables.AnalyticsSinkWrite).where(
                    tables.AnalyticsSinkWrite.idempotency_key == operation.idempotency_key
                )
            )
            if row is not None and row.status in {"succeeded", "skipped"}:
                return self._analytics_sink_write_record(row), True
            if row is None:
                row = tables.AnalyticsSinkWrite(
                    id=str(uuid.uuid4()),
                    case_id=operation.case_id,
                    analysis_run_id=operation.analysis_run_id,
                    sink_name=operation.sink_name,
                    destination=operation.destination,
                    idempotency_key=operation.idempotency_key,
                    payload_hash=operation.payload_hash,
                    status="pending",
                    attempt_count=0,
                    row_count=operation.row_count,
                    created_at=now,
                    updated_at=now,
                )
                session.add(row)
            else:
                row.sink_name = operation.sink_name
                row.destination = operation.destination
                row.payload_hash = operation.payload_hash
                row.row_count = operation.row_count

            row.status = "running"
            row.attempt_count = int(row.attempt_count or 0) + 1
            row.last_error = None
            row.last_attempt_at = now
            row.next_retry_at = None
            row.updated_at = now
            session.flush()
            return self._analytics_sink_write_record(row), False

    def _mark_analytics_sink_write_succeeded(self, *, write_id: str, row_count: int) -> None:
        now = _now()
        with self._session() as session:
            row = session.get(tables.AnalyticsSinkWrite, write_id)
            if row is None:
                raise KeyError(write_id)
            row.status = "succeeded"
            row.row_count = row_count
            row.last_error = None
            row.next_retry_at = None
            row.updated_at = now

    def _mark_analytics_sink_write_failed(
        self, *, write_id: str, error_message: str
    ) -> None:
        now = _now()
        with self._session() as session:
            row = session.get(tables.AnalyticsSinkWrite, write_id)
            if row is None:
                raise KeyError(write_id)
            row.status = "failed"
            row.last_error = sanitize_error_message(error_message)
            row.next_retry_at = now
            row.updated_at = now

    def _add_analytics_sink_count(
        self, metadata: dict[str, int], operation: AnalyticsSinkWriteOperation
    ) -> None:
        if operation.sink_name == "clickhouse":
            if operation.destination.endswith(".enriched_log_lines"):
                metadata["clickhouse_enriched_log_rows"] += operation.row_count
            elif operation.destination.endswith(".window_aggregates"):
                metadata["clickhouse_window_rows"] += operation.row_count
        elif operation.sink_name == "opensearch":
            metadata["opensearch_documents"] += operation.row_count

    def _fan_out_analysis_result(
        self, *, session: Session, run: tables.AnalysisRun, result: AnalysisResult
    ) -> None:
        self._delete_analysis_fanout(session=session, run_id=run.id)
        case_id = run.case_id
        created_at = _now()

        # Worker file IDs are deterministic from source paths, so raw_files IDs must be run scoped.
        file_ids = {
            file.file_id: str(uuid.uuid5(uuid.NAMESPACE_URL, f"{run.id}:{file.file_id}"))
            for file in result.files
        }
        raw_log_ids = {
            entry.log_id: _worker_uuid(entry.log_id, f"{run.id}:raw_log:{index}:{entry.log_id}")
            for index, entry in enumerate(result.raw_entries)
        }
        raw_log_redacted_messages = {
            line.raw_log_id: line.redacted_message for line in result.normalized_logs
        }
        normalized_log_ids = {
            line.log_id: _worker_uuid(line.log_id, f"{run.id}:normalized_log:{index}:{line.log_id}")
            for index, line in enumerate(result.normalized_logs)
        }
        template_ids = {
            template.template_id: _worker_uuid(
                template.template_id, f"{run.id}:template:{index}:{template.template_id}"
            )
            for index, template in enumerate(result.templates)
        }

        def required(mapping: dict[str, str], worker_id: str, label: str) -> str:
            try:
                return mapping[worker_id]
            except KeyError as exc:
                raise ValueError(f"analysis result references unknown {label}: {worker_id}") from exc

        def optional_template_id(worker_id: str | None) -> str | None:
            if not worker_id:
                return None
            return required(template_ids, worker_id, "template_id")

        def optional_normalized_log_id(worker_id: str | None) -> str | None:
            if not worker_id:
                return None
            return normalized_log_ids.get(worker_id) or _uuid_or_none(worker_id)

        session.add_all(
            tables.RawFile(
                id=file_ids[file.file_id],
                case_id=case_id,
                analysis_run_id=run.id,
                original_filename=file.original_filename,
                object_uri=file.object_uri,
                content_type=None,
                size_bytes=file.size_bytes,
                sha256=file.sha256,
                upload_completed=True,
                detected_format=file.detected_format,
                file_role="log",
                created_at=created_at,
            )
            for file in result.files
        )
        session.flush()

        session.add_all(
            tables.RawLogLine(
                id=raw_log_ids[entry.log_id],
                case_id=case_id,
                analysis_run_id=run.id,
                file_id=required(file_ids, entry.file_id, "file_id"),
                line_number=entry.line_number,
                raw_text=entry.raw_message,
                raw_text_redacted=raw_log_redacted_messages.get(entry.log_id),
                sha256=entry.sha256,
                created_at=created_at,
            )
            for entry in result.raw_entries
        )
        session.flush()

        session.add_all(
            tables.LogTemplate(
                id=template_ids[template.template_id],
                case_id=case_id,
                analysis_run_id=run.id,
                template_key=template.template_key,
                template_text=template.template_text,
                normalized_template_text=template.normalized_template_text,
                representative_log_id=optional_normalized_log_id(template.representative_log_id),
                occurrence_count=template.occurrence_count,
                first_seen=template.first_seen,
                last_seen=template.last_seen,
                services=template.services,
                files=template.files,
                sample_values=template.sample_values,
                drain_cluster_id=template.drain_cluster_id,
                created_at=created_at,
            )
            for template in result.templates
        )
        session.flush()

        session.add_all(
            tables.NormalizedLogLine(
                id=normalized_log_ids[line.log_id],
                raw_log_id=required(raw_log_ids, line.raw_log_id, "raw_log_id"),
                case_id=case_id,
                analysis_run_id=run.id,
                timestamp=line.timestamp,
                timestamp_quality=line.timestamp_quality,
                level=line.level,
                service=line.service,
                message=line.message,
                normalized_message=line.normalized_message,
                redacted_message=line.redacted_message,
                parsed_fields=line.parsed_fields,
                parser_name=line.parser_name,
                parser_confidence=line.parser_confidence,
                template_id=optional_template_id(line.template_id),
                created_at=created_at,
            )
            for line in result.normalized_logs
        )
        session.flush()

        session.add_all(
            tables.RepresentativeSample(
                id=_worker_uuid(sample.sample_id, f"{run.id}:sample:{index}:{sample.sample_id}"),
                template_id=required(template_ids, sample.template_id, "sample.template_id"),
                log_id=required(normalized_log_ids, sample.log_id, "sample.log_id"),
                sample_reason=sample.sample_reason,
                sample_rank=sample.sample_rank,
                created_at=created_at,
            )
            for index, sample in enumerate(result.samples)
        )
        session.flush()

        session.add_all(
            tables.TemplateAnnotation(
                id=_worker_uuid(
                    annotation.annotation_id,
                    f"{run.id}:annotation:{index}:{annotation.annotation_id}",
                ),
                template_id=required(
                    template_ids, annotation.template_id, "annotation.template_id"
                ),
                analysis_run_id=run.id,
                golden_signal=annotation.golden_signal,
                fault_categories=annotation.fault_categories,
                entities=annotation.entities,
                severity_score=annotation.severity_score,
                confidence=annotation.confidence,
                rationale=annotation.rationale,
                model_provider=annotation.model_provider,
                model_name=annotation.model_name,
                prompt_version=annotation.prompt_version,
                raw_model_response=annotation.raw_model_response,
                created_at=created_at,
            )
            for index, annotation in enumerate(result.annotations)
        )
        session.flush()

        session.add_all(
            tables.TimeWindowSignal(
                id=str(
                    uuid.uuid5(
                        uuid.NAMESPACE_URL,
                        (
                            f"{run.id}:time_window:{index}:"
                            f"{aggregate.window_start.isoformat()}:"
                            f"{aggregate.window_end.isoformat()}:"
                            f"{aggregate.template_id}:{aggregate.service}:"
                            f"{aggregate.golden_signal}:{aggregate.fault_category}"
                        ),
                    )
                ),
                case_id=case_id,
                analysis_run_id=run.id,
                window_start=aggregate.window_start,
                window_end=aggregate.window_end,
                window_size_seconds=aggregate.window_size_seconds,
                template_id=optional_template_id(aggregate.template_id),
                service=aggregate.service,
                golden_signal=aggregate.golden_signal,
                fault_category=aggregate.fault_category,
                count=aggregate.count,
                created_at=created_at,
            )
            for index, aggregate in enumerate(result.temporal)
        )
        session.flush()

        session.add_all(
            tables.CausalNode(
                id=_worker_uuid(node.id, f"{run.id}:causal_node:{index}:{node.id}"),
                case_id=case_id,
                analysis_run_id=run.id,
                template_id=required(template_ids, node.template_id, "causal_node.template_id"),
                node_type="template",
                rank_score=node.rank_score,
                pagerank_score=node.pagerank_score,
                golden_signal=node.golden_signal,
                fault_categories=node.fault_categories,
                first_seen=node.first_seen,
                last_seen=node.last_seen,
                occurrence_count=node.occurrence_count,
                created_at=created_at,
            )
            for index, node in enumerate(result.causal_graph.nodes)
        )
        session.flush()

        session.add_all(
            tables.CausalEdge(
                id=_worker_uuid(edge.id, f"{run.id}:causal_edge:{index}:{edge.id}"),
                case_id=case_id,
                analysis_run_id=run.id,
                source_template_id=required(
                    template_ids, edge.source_template_id, "causal_edge.source_template_id"
                ),
                target_template_id=required(
                    template_ids, edge.target_template_id, "causal_edge.target_template_id"
                ),
                edge_type=edge.edge_type,
                method=edge.method,
                lag_seconds=edge.lag_seconds,
                support_windows=edge.support_windows,
                confidence=edge.confidence,
                p_value_adj=edge.p_value_adj,
                lift=edge.lift,
                temporal_precedence_score=edge.temporal_precedence_score,
                correlation_score=edge.correlation_score,
                evidence=edge.evidence,
                created_at=created_at,
            )
            for index, edge in enumerate(result.causal_graph.edges)
        )
        session.flush()

        summary = result.causal_summary
        session.add(
            tables.CausalSummary(
                id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"{run.id}:causal_summary")),
                case_id=case_id,
                analysis_run_id=run.id,
                summary_markdown=summary.summary_markdown,
                customer_update_markdown=summary.customer_update_markdown,
                next_actions_json=summary.next_actions,
                evidence_refs_json=[
                    evidence_ref.model_dump(mode="json")
                    for evidence_ref in summary.evidence_refs
                ],
                confidence=summary.confidence,
                model_provider=run.model_provider,
                model_name=run.model_name,
                prompt_version=run.prompt_version,
                raw_model_response={},
                created_at=created_at,
            )
        )
        session.flush()

    def _delete_analysis_fanout(self, *, session: Session, run_id: str) -> None:
        template_ids = select(tables.LogTemplate.id).where(
            tables.LogTemplate.analysis_run_id == run_id
        )
        for table in (
            tables.CausalSummary,
            tables.CausalEdge,
            tables.CausalNode,
            tables.TimeWindowSignal,
            tables.TemplateAnnotation,
        ):
            session.execute(delete(table).where(table.analysis_run_id == run_id))
        session.execute(
            delete(tables.RepresentativeSample).where(
                tables.RepresentativeSample.template_id.in_(template_ids)
            )
        )
        for table in (
            tables.NormalizedLogLine,
            tables.LogTemplate,
            tables.RawLogLine,
            tables.RawFile,
        ):
            session.execute(delete(table).where(table.analysis_run_id == run_id))
        session.flush()

    def _fail_analysis_run(
        self, *, run_id: str, error_message: str, user_id: str
    ) -> AnalysisRunRecord:
        error_message = sanitize_error_message(error_message)
        with self._session() as session:
            run = session.get(tables.AnalysisRun, run_id)
            if run is None:
                raise KeyError(run_id)
            case = session.get(tables.Case, run.case_id)
            run.status = "failed"
            run.failed_at = _now()
            run.error_message = error_message
            progress = dict(run.progress_json or {})
            progress["error_message"] = error_message
            progress.setdefault("current_step", "failed")
            run.progress_json = progress
            if case:
                case.status = "failed"
                case.updated_at = _now()
            self._add_audit(
                session,
                action="analysis.fail",
                user_id=user_id,
                target_type="analysis_run",
                target_id=run.id,
                case_id=run.case_id,
                metadata={"error_message": error_message},
            )
        return self._analysis_run_record(run)

    def _add_audit(
        self,
        session: Session,
        *,
        action: str,
        user_id: str | None = None,
        target_type: str | None = None,
        target_id: str | None = None,
        case_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> tables.AuditLog:
        audit = tables.AuditLog(
            id=str(uuid.uuid4()),
            action=action,
            user_id=user_id,
            target_type=target_type,
            target_id=target_id,
            case_id=case_id,
            metadata_json=metadata or {},
            ip_address=ip_address,
            user_agent=user_agent,
            created_at=_now(),
        )
        session.add(audit)
        return audit

    def _user_record(self, row: tables.User) -> UserRecord:
        return UserRecord(
            id=row.id,
            email=row.email,
            username=row.username,
            full_name=row.full_name,
            password_hash=row.password_hash,
            role=row.role,
            is_active=row.is_active,
            created_at=_utc(row.created_at) or _now(),
        )

    def _session_record(self, row: tables.Session) -> SessionRecord:
        return SessionRecord(
            id=row.id,
            user_id=row.user_id,
            token_hash=row.token_hash,
            expires_at=_utc(row.expires_at) or _now(),
            created_at=_utc(row.created_at) or _now(),
            revoked_at=_utc(row.revoked_at),
        )

    def _credential_record(self, row: tables.CopilotCredential) -> CredentialRecord:
        return CredentialRecord(
            id=row.id,
            user_id=row.user_id,
            credential_type=row.credential_type,
            encrypted_token=row.encrypted_token,
            token_hint=row.token_hint or "",
            github_base_url=row.github_base_url,
            runtime_type=row.runtime_type,
            created_at=_utc(row.created_at) or _now(),
            expires_at=_utc(row.expires_at),
            revoked_at=_utc(row.revoked_at),
        )

    def _copilot_auth_record(self, row: tables.CopilotDeviceAuth) -> CopilotAuthRecord:
        return CopilotAuthRecord(
            auth_id=row.auth_id,
            user_id=row.user_id,
            device_code=row.device_code,
            user_code=row.user_code,
            verification_uri=row.verification_uri,
            verification_uri_complete=row.verification_uri_complete,
            expires_in=row.expires_in,
            interval=row.interval,
            poll_count=row.poll_count,
            github_base_url=row.github_base_url,
            created_at=_utc(row.created_at) or _now(),
            updated_at=_utc(row.updated_at) or _now(),
        )

    def _case_record(self, row: tables.Case) -> CaseRecord:
        return CaseRecord(
            id=row.id,
            case_key=row.case_key,
            title=row.title,
            issue_description=row.issue_description,
            product=row.product,
            service=row.service,
            environment=row.environment,
            incident_start=_utc(row.incident_start),
            incident_end=_utc(row.incident_end),
            timezone=row.timezone,
            status=row.status,
            created_by=row.created_by,
            created_at=_utc(row.created_at) or _now(),
        )

    def _upload_record(self, row: tables.RawFile) -> UploadRecord:
        return UploadRecord(
            id=row.id,
            case_id=row.case_id,
            filename=row.original_filename,
            content_type=row.content_type,
            size_bytes=row.size_bytes,
            object_uri=row.object_uri,
            sha256=row.sha256,
            completed=row.upload_completed,
            upload_metadata=dict(row.upload_metadata or {}),
            created_at=_utc(row.created_at) or _now(),
        )

    def _analysis_run_record(self, row: tables.AnalysisRun) -> AnalysisRunRecord:
        result = AnalysisResult.model_validate(row.result_json) if row.result_json else None
        return AnalysisRunRecord(
            id=row.id,
            case_id=row.case_id,
            run_number=row.run_number,
            status=row.status,
            config=row.config_json or {},
            model_provider=row.model_provider,
            model_name=row.model_name,
            model_reasoning_effort=row.model_reasoning_effort,
            prompt_version=row.prompt_version,
            created_by=row.created_by,
            started_at=_utc(row.started_at),
            completed_at=_utc(row.completed_at),
            error_message=row.error_message,
            result=result,
            progress=row.progress_json or (result.progress if result else {}),
        )

    def _job_event_record(self, row: tables.JobEvent) -> JobEventRecord:
        return JobEventRecord(
            id=row.id,
            case_id=row.case_id,
            analysis_run_id=row.analysis_run_id,
            step_name=row.step_name,
            event_type=row.event_type,
            status=row.status,
            attempt=row.attempt,
            idempotency_key=row.idempotency_key,
            metadata=row.metadata_json or {},
            error_message=row.error_message,
            created_at=_utc(row.created_at) or _now(),
        )

    def _analytics_sink_write_record(
        self, row: tables.AnalyticsSinkWrite
    ) -> AnalyticsSinkWriteRecord:
        return AnalyticsSinkWriteRecord(
            id=row.id,
            case_id=row.case_id,
            analysis_run_id=row.analysis_run_id,
            sink_name=row.sink_name,
            destination=row.destination,
            idempotency_key=row.idempotency_key,
            payload_hash=row.payload_hash,
            status=row.status,
            attempt_count=row.attempt_count,
            row_count=row.row_count,
            last_error=row.last_error,
            last_attempt_at=_utc(row.last_attempt_at),
            next_retry_at=_utc(row.next_retry_at),
            created_at=_utc(row.created_at) or _now(),
            updated_at=_utc(row.updated_at) or _now(),
        )

    def _export_record(self, row: tables.Export) -> ExportRecord:
        return ExportRecord(
            id=row.id,
            case_id=row.case_id,
            analysis_run_id=row.analysis_run_id,
            export_type=row.export_type,
            object_uri=row.object_uri,
            created_by=row.created_by,
            created_at=_utc(row.created_at) or _now(),
        )

    def _feedback_record(self, row: tables.Feedback) -> FeedbackRecord:
        return FeedbackRecord(
            id=row.id,
            case_id=row.case_id,
            analysis_run_id=row.analysis_run_id,
            user_id=row.user_id,
            target_type=row.target_type,
            target_id=row.target_id,
            feedback_type=row.feedback_type,
            rating=row.rating,
            comment=row.comment,
            corrected_value=row.corrected_value or None,
            created_at=_utc(row.created_at) or _now(),
        )

    def _audit_record(self, row: tables.AuditLog) -> AuditLogRecord:
        return AuditLogRecord(
            id=row.id,
            action=row.action,
            user_id=row.user_id,
            target_type=row.target_type,
            target_id=row.target_id,
            case_id=row.case_id,
            metadata=row.metadata_json or {},
            ip_address=row.ip_address,
            user_agent=row.user_agent,
            created_at=_utc(row.created_at) or _now(),
        )
