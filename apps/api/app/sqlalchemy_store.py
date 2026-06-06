from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator

from logan_workers.models import AnalysisResult
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
from app.services.object_store import is_local_backend, local_upload_object_uri, safe_filename
from app.store import (
    AnalysisRunRecord,
    AuditLogRecord,
    CaseRecord,
    CopilotAuthRecord,
    CredentialRecord,
    ExportRecord,
    FeedbackRecord,
    SessionRecord,
    UploadRecord,
    UserRecord,
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
    ) -> None:
        self.settings = app_settings
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
    ) -> CredentialRecord:
        encrypted = encrypt_token(token, self.settings.credential_encryption_key)
        hint = token_hint(token)
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
                )
                session.add(credential)
            else:
                credential.credential_type = credential_type
                credential.encrypted_token = encrypted
                credential.token_hint = hint
                credential.github_base_url = github_base_url
                credential.runtime_type = "github_copilot"
                credential.updated_at = _now()
        return self._credential_record(credential)

    def get_credential(self, *, user_id: str, credential_type: str) -> CredentialRecord | None:
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
            return self._credential_record(credential) if credential else None

    def has_credential(self, user_id: str) -> bool:
        with self._session() as session:
            return (
                session.scalar(
                    select(func.count())
                    .select_from(tables.CopilotCredential)
                    .where(
                        tables.CopilotCredential.user_id == user_id,
                        tables.CopilotCredential.revoked_at.is_(None),
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
        object_uri = (
            local_upload_object_uri(
                case_id=case_id,
                file_id=upload_id,
                filename=stored_filename,
                app_settings=self.settings,
            )
            if is_local_backend(self.settings)
            else f"memory://uploads/{case_id}/{upload_id}/{stored_filename}"
        )
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
            )
            return self._complete_analysis_run(run_id=run.id, result=result, user_id=user_id)
        except Exception as exc:
            self._fail_analysis_run(run_id=run.id, error_message=str(exc), user_id=user_id)
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

    def get_analysis_result(self, case_id: str, run_id: str) -> AnalysisResult | None:
        with self._session() as session:
            run = session.get(tables.AnalysisRun, run_id)
            if not run or run.case_id != case_id or not run.result_json:
                return None
            return AnalysisResult.model_validate(run.result_json)

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

    def _complete_analysis_run(
        self, *, run_id: str, result: AnalysisResult, user_id: str
    ) -> AnalysisRunRecord:
        result_json = result.model_dump(mode="json")
        result_json["model_inputs"] = []
        with self._session() as session:
            run = session.get(tables.AnalysisRun, run_id)
            if run is None:
                raise KeyError(run_id)
            case = session.get(tables.Case, run.case_id)
            run.status = "completed"
            run.completed_at = _now()
            run.error_message = None
            run.progress_json = result.progress
            run.result_json = result_json
            self._fan_out_analysis_result(session=session, run=run, result=result)
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
        with self._session() as session:
            run = session.get(tables.AnalysisRun, run_id)
            if run is None:
                raise KeyError(run_id)
            case = session.get(tables.Case, run.case_id)
            run.status = "failed"
            run.failed_at = _now()
            run.error_message = error_message
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
