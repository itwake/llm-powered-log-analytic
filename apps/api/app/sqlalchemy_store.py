from __future__ import annotations

import asyncio
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator

from logan_analysis.models import AnalysisResult
from logan_analysis.pipeline import AnalyzeCasePipeline
from sqlalchemy import URL, create_engine, event, func, or_, select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import Settings, settings
from app.core.security import default_session_expiry, hash_token, issue_session_token
from app.db import Base
from app.models import tables
from app.services.object_store import local_upload_object_uri, safe_filename
from app.records import (
    TERMINAL_ANALYSIS_RUN_STATUSES,
    AnalysisRunCancelled,
    AnalysisRunRecord,
    CaseRecord,
    SessionRecord,
    UploadRecord,
    UserRecord,
    sanitize_error_message,
)


def _now() -> datetime:
    return datetime.now(UTC)


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _sqlite_url(database_path: str) -> URL:
    if database_path == ":memory:":
        return URL.create("sqlite+pysqlite", database=":memory:")
    path = Path(database_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    return URL.create("sqlite+pysqlite", database=str(path))


def _enable_sqlite_foreign_keys(dbapi_connection: Any, _: Any) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


class SQLAlchemyStore:
    def __init__(
        self,
        *,
        app_settings: Settings = settings,
        database_path: str,
        engine: Engine | None = None,
        create_schema: bool = True,
    ) -> None:
        self.settings = app_settings
        self.database_path = database_path
        engine_options: dict[str, Any] = {
            "future": True,
            "connect_args": {"check_same_thread": False},
        }
        if database_path == ":memory:":
            engine_options["poolclass"] = StaticPool
        self.engine = engine or create_engine(_sqlite_url(database_path), **engine_options)
        if not event.contains(self.engine, "connect", _enable_sqlite_foreign_keys):
            event.listen(self.engine, "connect", _enable_sqlite_foreign_keys)
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
        self,
        *,
        email: str,
        username: str,
        full_name: str | None,
        external_id: str | None = None,
    ) -> UserRecord:
        normalized_email = email.strip().lower()
        normalized_username = username.strip()
        if not normalized_email or not normalized_username:
            raise ValueError("email and username are required")
        row = tables.User(
            id=str(uuid.uuid4()),
            email=normalized_email,
            username=normalized_username,
            full_name=full_name.strip() if full_name else None,
            external_id=external_id,
            created_at=_now(),
            updated_at=_now(),
        )
        try:
            with self._session() as session:
                existing = session.scalar(
                    select(tables.User).where(
                        or_(
                            tables.User.email == normalized_email,
                            tables.User.username == normalized_username,
                            (
                                tables.User.external_id == external_id
                                if external_id
                                else tables.User.id == ""
                            ),
                        )
                    )
                )
                if existing:
                    raise ValueError("user already exists")
                session.add(row)
        except IntegrityError as exc:
            raise ValueError("user already exists") from exc
        return self._user_record(row)

    def get_user(self, user_id: str) -> UserRecord | None:
        with self._session() as session:
            row = session.get(tables.User, user_id)
            return self._user_record(row) if row else None

    def get_user_by_email(self, email: str) -> UserRecord | None:
        with self._session() as session:
            row = session.scalar(
                select(tables.User).where(tables.User.email == email.strip().lower())
            )
            return self._user_record(row) if row else None

    def get_user_by_username(self, username: str) -> UserRecord | None:
        with self._session() as session:
            row = session.scalar(
                select(tables.User).where(tables.User.username == username.strip())
            )
            return self._user_record(row) if row else None

    def get_user_by_external_id(self, external_id: str) -> UserRecord | None:
        with self._session() as session:
            row = session.scalar(
                select(tables.User).where(tables.User.external_id == external_id)
            )
            return self._user_record(row) if row else None

    def update_user_profile(
        self,
        *,
        user_id: str,
        email: str | None = None,
        username: str | None = None,
        full_name: str | None = None,
        external_id: str | None = None,
        **_: Any,
    ) -> UserRecord:
        try:
            with self._session() as session:
                row = session.get(tables.User, user_id)
                if row is None:
                    raise KeyError(user_id)
                if email is not None:
                    row.email = email.strip().lower()
                if username is not None:
                    row.username = username.strip()
                if full_name is not None:
                    row.full_name = full_name.strip() or None
                if external_id is not None:
                    row.external_id = external_id
                row.updated_at = _now()
                session.flush()
                return self._user_record(row)
        except IntegrityError as exc:
            raise ValueError("user already exists") from exc

    def create_session(self, user_id: str) -> tuple[str, SessionRecord]:
        token = issue_session_token()
        row = tables.Session(
            id=str(uuid.uuid4()),
            user_id=user_id,
            token_hash=hash_token(token),
            expires_at=default_session_expiry(),
            created_at=_now(),
        )
        with self._session() as session:
            if session.get(tables.User, user_id) is None:
                raise KeyError(user_id)
            session.add(row)
        return token, self._session_record(row)

    def get_user_by_session(self, token: str | None) -> UserRecord | None:
        if not token:
            return None
        with self._session() as session:
            session_row = session.scalar(
                select(tables.Session).where(tables.Session.token_hash == hash_token(token))
            )
            if (
                session_row is None
                or session_row.revoked_at is not None
                or (_utc(session_row.expires_at) or _now()) <= _now()
            ):
                return None
            user = session.get(tables.User, session_row.user_id)
            if user is None:
                return None
            return self._user_record(user)

    def revoke_session(self, token: str | None) -> None:
        if not token:
            return
        with self._session() as session:
            row = session.scalar(
                select(tables.Session).where(tables.Session.token_hash == hash_token(token))
            )
            if row is not None:
                row.revoked_at = _now()

    def create_case(self, *, user_id: str, data: dict[str, Any]) -> CaseRecord:
        now = _now()
        case_id = str(uuid.uuid4())
        row = tables.Case(
            id=case_id,
            case_key=f"CASE-{case_id[:8].upper()}",
            title=str(data["title"]).strip(),
            issue_description=data.get("issue_description"),
            product=data.get("product"),
            service=data.get("service"),
            environment=data.get("environment"),
            incident_start=data.get("incident_start"),
            incident_end=data.get("incident_end"),
            timezone=data.get("timezone") or "UTC",
            status="created",
            created_by=user_id,
            created_at=now,
            updated_at=now,
        )
        with self._session() as session:
            session.add(row)
        return self._case_record(row)

    def get_case(self, case_id: str) -> CaseRecord | None:
        with self._session() as session:
            row = session.get(tables.Case, case_id)
            if row is None or row.deleted_at is not None:
                return None
            return self._case_record(row)

    def list_cases_for_user(
        self,
        user: UserRecord,
        *,
        status: str | None = None,
        product: str | None = None,
        offset: int = 0,
        limit: int = 25,
    ) -> tuple[list[CaseRecord], int]:
        criteria = [
            tables.Case.created_by == user.id,
            tables.Case.deleted_at.is_(None),
        ]
        if status:
            criteria.append(tables.Case.status == status)
        if product:
            criteria.append(tables.Case.product == product)
        with self._session() as session:
            total = session.scalar(
                select(func.count()).select_from(tables.Case).where(*criteria)
            ) or 0
            rows = session.scalars(
                select(tables.Case)
                .where(*criteria)
                .order_by(tables.Case.updated_at.desc(), tables.Case.id)
                .offset(offset)
                .limit(limit)
            ).all()
            return [self._case_record(row) for row in rows], int(total)

    def update_case(
        self,
        *,
        case_id: str,
        data: dict[str, Any],
        user_id: str,
    ) -> CaseRecord:
        with self._session() as session:
            row = session.get(tables.Case, case_id)
            if row is None or row.deleted_at is not None or row.created_by != user_id:
                raise KeyError(case_id)
            for field_name in (
                "title",
                "issue_description",
                "product",
                "service",
                "environment",
                "incident_start",
                "incident_end",
                "timezone",
            ):
                if field_name in data:
                    setattr(row, field_name, data[field_name])
            row.updated_at = _now()
            session.flush()
            return self._case_record(row)

    def delete_case(self, *, case_id: str, user_id: str) -> bool:
        with self._session() as session:
            row = session.get(tables.Case, case_id)
            if row is None or row.deleted_at is not None or row.created_by != user_id:
                return False
            row.deleted_at = _now()
            row.updated_at = _now()
            return True

    def create_upload(
        self,
        *,
        case_id: str,
        filename: str,
        content_type: str | None,
        size_bytes: int,
    ) -> UploadRecord:
        upload_id = str(uuid.uuid4())
        row = tables.RawFile(
            id=upload_id,
            case_id=case_id,
            original_filename=filename,
            object_uri=local_upload_object_uri(
                case_id=case_id,
                file_id=upload_id,
                filename=safe_filename(filename),
                app_settings=self.settings,
            ),
            content_type=content_type,
            size_bytes=size_bytes,
            upload_completed=False,
            created_at=_now(),
        )
        with self._session() as session:
            case = session.get(tables.Case, case_id)
            if case is None or case.deleted_at is not None:
                raise KeyError(case_id)
            session.add(row)
            case.status = "uploading"
            case.updated_at = _now()
        return self._upload_record(row)

    def get_upload(self, upload_id: str) -> UploadRecord | None:
        with self._session() as session:
            row = session.get(tables.RawFile, upload_id)
            return self._upload_record(row) if row else None

    def complete_upload(self, *, upload_id: str, sha256: str) -> UploadRecord:
        with self._session() as session:
            row = session.get(tables.RawFile, upload_id)
            if row is None:
                raise KeyError(upload_id)
            row.sha256 = sha256
            row.upload_completed = True
            session.flush()
            return self._upload_record(row)

    def create_analysis_run(
        self,
        *,
        case_id: str,
        user_id: str,
    ) -> AnalysisRunRecord:
        with self._session() as session:
            case = session.get(tables.Case, case_id)
            if case is None or case.deleted_at is not None or case.created_by != user_id:
                raise KeyError(case_id)
            run_number = int(
                session.scalar(
                    select(func.coalesce(func.max(tables.AnalysisRun.run_number), 0)).where(
                        tables.AnalysisRun.case_id == case_id
                    )
                )
                or 0
            ) + 1
            row = tables.AnalysisRun(
                id=str(uuid.uuid4()),
                case_id=case_id,
                run_number=run_number,
                status="queued",
                model_provider=self.settings.normalized_llm_provider,
                model_name=(
                    self.settings.ai_platform_model
                    if self.settings.normalized_llm_provider == "ai_platform"
                    else "none"
                ),
                progress_json={"current_step": "queued", "steps": {}},
                created_by=user_id,
                created_at=_now(),
            )
            session.add(row)
            case.status = "analyzing"
            case.updated_at = _now()
            session.flush()
            return self._analysis_run_record(row)

    async def run_analysis(
        self,
        *,
        run_id: str,
        user_id: str,
        file_paths: list[str],
        gateway: Any | None = None,
    ) -> AnalysisRunRecord:
        if not file_paths:
            raise ValueError("at least one completed upload is required")
        run = self.get_analysis_run(run_id)
        if run is None or run.created_by != user_id:
            raise KeyError(run_id)
        case = self.get_case(run.case_id)
        if case is None:
            raise KeyError(run.case_id)

        with self._session() as session:
            row = session.get(tables.AnalysisRun, run_id)
            if row is None:
                raise KeyError(run_id)
            if row.status == "cancelled":
                return self._analysis_run_record(row)
            row.status = "processing"
            row.started_at = _now()

        def record_progress(progress: dict[str, Any]) -> None:
            current = self.get_analysis_run(run_id)
            if current is None or current.status == "cancelled":
                raise AnalysisRunCancelled("analysis run was cancelled")
            self.update_analysis_progress(run_id=run_id, progress=progress)

        try:
            result = await AnalyzeCasePipeline().run(
                case_id=case.id,
                analysis_run_id=run_id,
                paths=file_paths,
                case_context={
                    "title": case.title,
                    "issue_description": case.issue_description,
                    "product": case.product,
                    "service": case.service,
                    "environment": case.environment,
                    "model": run.model_name,
                    "reasoning_effort": self.settings.ai_platform_reasoning_effort,
                },
                gateway=gateway,
                progress_callback=record_progress,
            )
        except (AnalysisRunCancelled, asyncio.CancelledError):
            return self.cancel_analysis_run(run_id=run_id, user_id=user_id)
        except Exception as exc:
            with self._session() as session:
                row = session.get(tables.AnalysisRun, run_id)
                if row is not None and row.status != "cancelled":
                    row.status = "failed"
                    row.completed_at = _now()
                    row.error_message = sanitize_error_message(exc)
                    case_row = session.get(tables.Case, row.case_id)
                    if case_row is not None:
                        case_row.status = "failed"
                        case_row.updated_at = _now()
            raise

        with self._session() as session:
            row = session.get(tables.AnalysisRun, run_id)
            if row is None:
                raise KeyError(run_id)
            if row.status == "cancelled":
                return self._analysis_run_record(row)
            completed_at = _now()
            row.status = "completed"
            row.result_json = result.model_dump(mode="json")
            row.progress_json = dict(result.progress)
            row.completed_at = completed_at
            row.error_message = None
            case_row = session.get(tables.Case, row.case_id)
            if case_row is not None:
                case_row.status = "completed"
                case_row.updated_at = completed_at
            session.flush()
            return self._analysis_run_record(row)

    def get_analysis_run(self, run_id: str) -> AnalysisRunRecord | None:
        with self._session() as session:
            row = session.get(tables.AnalysisRun, run_id)
            return self._analysis_run_record(row) if row else None

    def list_analysis_runs(self, case_id: str) -> list[AnalysisRunRecord]:
        with self._session() as session:
            rows = session.scalars(
                select(tables.AnalysisRun)
                .where(tables.AnalysisRun.case_id == case_id)
                .order_by(tables.AnalysisRun.run_number.desc())
            ).all()
            return [self._analysis_run_record(row) for row in rows]

    def cancel_analysis_run(self, *, run_id: str, user_id: str) -> AnalysisRunRecord:
        with self._session() as session:
            row = session.get(tables.AnalysisRun, run_id)
            if row is None or row.created_by != user_id:
                raise KeyError(run_id)
            if row.status in TERMINAL_ANALYSIS_RUN_STATUSES:
                return self._analysis_run_record(row)
            now = _now()
            progress = dict(row.progress_json or {})
            progress["current_step"] = "cancelled"
            progress["cancelled_at"] = now.isoformat()
            row.status = "cancelled"
            row.progress_json = progress
            row.completed_at = now
            row.error_message = None
            case = session.get(tables.Case, row.case_id)
            if case is not None:
                case.status = "cancelled"
                case.updated_at = now
            session.flush()
            return self._analysis_run_record(row)

    def update_analysis_progress(self, *, run_id: str, progress: dict[str, Any]) -> None:
        clean_progress = dict(progress)
        if clean_progress.get("error_message"):
            clean_progress["error_message"] = sanitize_error_message(
                str(clean_progress["error_message"])
            )
        steps = {
            str(name): dict(value)
            for name, value in dict(clean_progress.get("steps") or {}).items()
            if isinstance(value, dict)
        }
        for step in steps.values():
            if step.get("error_message"):
                step["error_message"] = sanitize_error_message(str(step["error_message"]))
        clean_progress["steps"] = steps
        with self._session() as session:
            run = session.get(tables.AnalysisRun, run_id)
            if run is not None:
                run.progress_json = clean_progress

    def get_analysis_result(self, case_id: str, run_id: str) -> AnalysisResult | None:
        with self._session() as session:
            row = session.get(tables.AnalysisRun, run_id)
            if row is None or row.case_id != case_id or row.result_json is None:
                return None
            return AnalysisResult.model_validate(row.result_json)

    def _user_record(self, row: tables.User) -> UserRecord:
        return UserRecord(
            id=row.id,
            email=row.email,
            username=row.username,
            full_name=row.full_name,
            external_id=row.external_id,
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
            model_provider=row.model_provider,
            model_name=row.model_name,
            created_by=row.created_by,
            started_at=_utc(row.started_at),
            completed_at=_utc(row.completed_at),
            error_message=row.error_message,
            result=result,
            progress=dict(row.progress_json or {}),
        )
