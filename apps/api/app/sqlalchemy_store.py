from __future__ import annotations

import asyncio
import base64
import hashlib
import uuid
import zlib
from collections import Counter
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock, Timer
from typing import Any, Iterator

from logan_analysis.models import (
    AnalysisReportSummary,
    AnalysisResult,
    CausalGraph,
    CausalSummary,
    NormalizedLogLine,
    WindowAggregate,
)
from logan_analysis.pipeline import AnalyzeCasePipeline
from sqlalchemy import URL, create_engine, event, func, or_, select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, defer, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import Settings, settings
from app.core.security import default_session_expiry, hash_token, issue_session_token
from app.db import Base
from app.models import tables
from app.services.analysis_result_artifacts import (
    delete_analysis_result_artifacts,
    is_analysis_result_manifest,
    iter_log_chunks,
    read_causal_graph,
    read_causal_summary,
    read_full_analysis_result,
    read_log_chunk,
    read_report_summary,
    read_temporal,
    write_analysis_result_manifest,
)
from app.services.object_store import local_upload_object_uri, safe_filename
from app.records import (
    TERMINAL_ANALYSIS_RUN_STATUSES,
    AnalysisLogPageRecord,
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


_RESULT_FORMAT = "logan.analysis-result"
_RESULT_ENCODING = "zlib+base64"
_RESULT_VERSION = 1
_RESULT_CACHE_TTL_SECONDS = 5 * 60
_PERSISTED_RESULT_EXCLUDE = {
    "files": {"__all__": {"lines"}},
    "raw_entries": True,
    "normalized_logs": {
        "__all__": {
            "message",
            "normalized_message",
            "parsed_fields",
            "template_text",
        }
    },
}


def _encode_analysis_result(result: AnalysisResult) -> dict[str, Any]:
    raw = result.model_dump_json(exclude=_PERSISTED_RESULT_EXCLUDE).encode("utf-8")
    compressed = zlib.compress(raw, level=1)
    return {
        "format": _RESULT_FORMAT,
        "version": _RESULT_VERSION,
        "encoding": _RESULT_ENCODING,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "payload": base64.b64encode(compressed).decode("ascii"),
    }


def _decode_analysis_result(payload: dict[str, Any]) -> AnalysisResult:
    if payload.get("format") != _RESULT_FORMAT:
        return AnalysisResult.model_validate(payload)
    try:
        if payload.get("version") != _RESULT_VERSION:
            raise ValueError("unsupported analysis result version")
        if payload.get("encoding") != _RESULT_ENCODING:
            raise ValueError("unsupported analysis result encoding")
        compressed = base64.b64decode(str(payload["payload"]), validate=True)
        raw = zlib.decompress(compressed)
        if hashlib.sha256(raw).hexdigest() != payload.get("sha256"):
            raise ValueError("analysis result checksum mismatch")
        return AnalysisResult.model_validate_json(raw)
    except Exception as exc:
        raise ValueError("stored analysis result is invalid") from exc


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
        create_schema: bool = False,
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
        self._database_lock = RLock()
        if create_schema:
            Base.metadata.create_all(self.engine)
        self._analysis_result_cache: tuple[str, AnalysisResult] | None = None
        self._analysis_result_cache_generation = 0
        self._analysis_result_cache_lock = RLock()
        self._analysis_result_cache_timer: Timer | None = None

    @contextmanager
    def _session(self) -> Iterator[Session]:
        with self._database_lock:
            with self.session_factory() as session:
                try:
                    yield session
                    session.commit()
                except Exception:
                    session.rollback()
                    raise

    def _expire_analysis_result_cache(self, generation: int) -> None:
        with self._analysis_result_cache_lock:
            if generation != self._analysis_result_cache_generation:
                return
            self._analysis_result_cache = None
            self._analysis_result_cache_timer = None

    def _cache_analysis_result(self, result: AnalysisResult) -> None:
        with self._analysis_result_cache_lock:
            self._analysis_result_cache_generation += 1
            generation = self._analysis_result_cache_generation
            if self._analysis_result_cache_timer is not None:
                self._analysis_result_cache_timer.cancel()
            self._analysis_result_cache = (result.analysis_run_id, result)
            timer = Timer(
                _RESULT_CACHE_TTL_SECONDS,
                self._expire_analysis_result_cache,
                args=(generation,),
            )
            timer.daemon = True
            self._analysis_result_cache_timer = timer
            timer.start()

    def _clear_analysis_result_cache(self) -> None:
        with self._analysis_result_cache_lock:
            self._analysis_result_cache_generation += 1
            if self._analysis_result_cache_timer is not None:
                self._analysis_result_cache_timer.cancel()
            self._analysis_result_cache = None
            self._analysis_result_cache_timer = None

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

        async def record_progress(progress: dict[str, Any]) -> None:
            current = await asyncio.to_thread(self.get_analysis_run, run_id)
            if current is None or current.status == "cancelled":
                raise AnalysisRunCancelled("analysis run was cancelled")
            await asyncio.to_thread(
                self.update_analysis_progress,
                run_id=run_id,
                progress=progress,
            )

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
                max_input_bytes=self.settings.max_upload_bytes,
            )
            finalizing_progress = {
                **result.progress,
                "current_step": "finalizing",
                "finalizing_started_at": _now().isoformat(),
            }
            await asyncio.to_thread(
                self.update_analysis_progress,
                run_id=run_id,
                progress=finalizing_progress,
            )
            return await asyncio.to_thread(
                self._complete_analysis_run,
                run_id=run_id,
                result=result,
            )
        except (AnalysisRunCancelled, asyncio.CancelledError):
            return self.cancel_analysis_run(run_id=run_id, user_id=user_id)
        except Exception as exc:
            try:
                await asyncio.to_thread(
                    self._fail_analysis_run,
                    run_id=run_id,
                    error=exc,
                )
            except Exception:
                pass
            raise

    def _complete_analysis_run(
        self,
        *,
        run_id: str,
        result: AnalysisResult,
    ) -> AnalysisRunRecord:
        encoded_result = write_analysis_result_manifest(result, settings=self.settings)
        keep_artifacts = False
        try:
            with self._session() as session:
                row = session.get(tables.AnalysisRun, run_id)
                if row is None:
                    raise KeyError(run_id)
                if row.status == "cancelled":
                    completed_record = self._analysis_run_record(row)
                else:
                    completed_at = _now()
                    row.status = "completed"
                    row.result_json = encoded_result
                    row.progress_json = {
                        **result.progress,
                        "current_step": "completed",
                        "completed_at": completed_at.isoformat(),
                    }
                    row.completed_at = completed_at
                    row.error_message = None
                    case_row = session.get(tables.Case, row.case_id)
                    if case_row is not None:
                        case_row.status = "completed"
                        case_row.updated_at = completed_at
                    session.flush()
                    completed_record = self._analysis_run_record(row)
                    keep_artifacts = True
        except Exception:
            delete_analysis_result_artifacts(encoded_result, settings=self.settings)
            raise
        if not keep_artifacts:
            delete_analysis_result_artifacts(encoded_result, settings=self.settings)
        return completed_record

    def _fail_analysis_run(
        self,
        *,
        run_id: str,
        error: BaseException | str,
    ) -> None:
        with self._session() as session:
            row = session.get(
                tables.AnalysisRun,
                run_id,
                options=(defer(tables.AnalysisRun.result_json),),
            )
            if row is None or row.status == "cancelled":
                return
            failed_at = _now()
            error_message = sanitize_error_message(error)
            progress = dict(row.progress_json or {})
            progress["current_step"] = "failed"
            progress["failed_at"] = failed_at.isoformat()
            progress["error_message"] = error_message
            row.status = "failed"
            row.progress_json = progress
            row.completed_at = failed_at
            row.error_message = error_message
            case_row = session.get(tables.Case, row.case_id)
            if case_row is not None:
                case_row.status = "failed"
                case_row.updated_at = failed_at

    def get_analysis_run(self, run_id: str) -> AnalysisRunRecord | None:
        with self._session() as session:
            row = session.get(
                tables.AnalysisRun,
                run_id,
                options=(defer(tables.AnalysisRun.result_json),),
            )
            return self._analysis_run_record(row) if row else None

    def list_analysis_runs(self, case_id: str) -> list[AnalysisRunRecord]:
        with self._session() as session:
            rows = session.scalars(
                select(tables.AnalysisRun)
                .options(defer(tables.AnalysisRun.result_json))
                .where(tables.AnalysisRun.case_id == case_id)
                .order_by(tables.AnalysisRun.run_number.desc())
            ).all()
            return [self._analysis_run_record(row) for row in rows]

    def cancel_analysis_run(self, *, run_id: str, user_id: str) -> AnalysisRunRecord:
        with self._session() as session:
            row = session.get(
                tables.AnalysisRun,
                run_id,
                options=(defer(tables.AnalysisRun.result_json),),
            )
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
            run = session.get(
                tables.AnalysisRun,
                run_id,
                options=(defer(tables.AnalysisRun.result_json),),
            )
            if run is not None and run.status not in TERMINAL_ANALYSIS_RUN_STATUSES:
                run.progress_json = clean_progress

    def get_analysis_result(self, case_id: str, run_id: str) -> AnalysisResult | None:
        with self._analysis_result_cache_lock:
            cached = self._analysis_result_cache
            if cached is not None and cached[0] == run_id:
                result = cached[1]
                if result.case_id != case_id:
                    return None
                self._cache_analysis_result(result)
                return result
        payload = self._get_analysis_result_payload(case_id, run_id)
        if payload is None:
            return None
        if is_analysis_result_manifest(payload):
            return read_full_analysis_result(payload, settings=self.settings)
        result = _decode_analysis_result(payload)
        self._cache_analysis_result(result)
        return result

    def _get_analysis_result_payload(
        self,
        case_id: str,
        run_id: str,
    ) -> dict[str, Any] | None:
        with self._session() as session:
            row = session.execute(
                select(
                    tables.AnalysisRun.case_id,
                    tables.AnalysisRun.result_json,
                ).where(tables.AnalysisRun.id == run_id)
            ).one_or_none()
            if row is None or row.case_id != case_id or row.result_json is None:
                return None
            return dict(row.result_json)

    def get_analysis_report_summary(
        self,
        case_id: str,
        run_id: str,
    ) -> AnalysisReportSummary | None:
        payload = self._get_analysis_result_payload(case_id, run_id)
        if payload is None:
            return None
        if is_analysis_result_manifest(payload):
            return read_report_summary(payload, settings=self.settings)
        result = self.get_analysis_result(case_id, run_id)
        if result is None:
            return None
        return AnalysisReportSummary(
            case_id=result.case_id,
            analysis_run_id=result.analysis_run_id,
            files=result.files,
            templates=result.templates,
            samples=result.samples,
            annotations=result.annotations,
            log_facets=result.log_facets,
            progress=result.progress,
        )

    def get_analysis_temporal(
        self,
        case_id: str,
        run_id: str,
    ) -> list[WindowAggregate] | None:
        payload = self._get_analysis_result_payload(case_id, run_id)
        if payload is None:
            return None
        if is_analysis_result_manifest(payload):
            return read_temporal(payload, settings=self.settings)
        result = self.get_analysis_result(case_id, run_id)
        return result.temporal if result is not None else None

    def get_analysis_causal_graph(
        self,
        case_id: str,
        run_id: str,
    ) -> CausalGraph | None:
        payload = self._get_analysis_result_payload(case_id, run_id)
        if payload is None:
            return None
        if is_analysis_result_manifest(payload):
            return read_causal_graph(payload, settings=self.settings)
        result = self.get_analysis_result(case_id, run_id)
        return result.causal_graph if result is not None else None

    def get_analysis_causal_summary(
        self,
        case_id: str,
        run_id: str,
    ) -> CausalSummary | None:
        payload = self._get_analysis_result_payload(case_id, run_id)
        if payload is None:
            return None
        if is_analysis_result_manifest(payload):
            return read_causal_summary(payload, settings=self.settings)
        result = self.get_analysis_result(case_id, run_id)
        return result.causal_summary if result is not None else None

    def get_analysis_logs_page(
        self,
        case_id: str,
        run_id: str,
        *,
        window_start: datetime | None = None,
        window_end: datetime | None = None,
        q: str | None = None,
        service: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> AnalysisLogPageRecord | None:
        payload = self._get_analysis_result_payload(case_id, run_id)
        if payload is None:
            return None
        if not is_analysis_result_manifest(payload):
            result = self.get_analysis_result(case_id, run_id)
            if result is None:
                return None
            templates = {
                template.template_id: template.template_text
                for template in result.templates
            }
            rows = [
                line
                for line in result.normalized_logs
                if self._analysis_log_matches(
                    line,
                    template_text_by_id=templates,
                    window_start=window_start,
                    window_end=window_end,
                    q=q,
                    service=service,
                )
            ]
            facets = (
                result.log_facets
                if not any((window_start, window_end, q, service)) and result.log_facets
                else self._analysis_log_facets(rows)
            )
            return AnalysisLogPageRecord(
                rows=rows[offset : offset + limit],
                total=len(rows),
                facets=facets,
                template_text_by_id=templates,
            )

        summary = read_report_summary(payload, settings=self.settings)
        templates = {
            template.template_id: template.template_text for template in summary.templates
        }
        logs_manifest = payload.get("logs", {})
        if not any((window_start, window_end, q, service)):
            page_end = offset + limit
            page_rows: list[NormalizedLogLine] = []
            for entry in logs_manifest.get("chunks", []):
                chunk_start = int(entry.get("start_offset") or 0)
                chunk_end = chunk_start + int(entry.get("record_count") or 0)
                if chunk_end <= offset or chunk_start >= page_end:
                    continue
                chunk = read_log_chunk(entry, settings=self.settings)
                local_start = max(offset - chunk_start, 0)
                local_end = min(page_end - chunk_start, len(chunk))
                page_rows.extend(chunk[local_start:local_end])
            return AnalysisLogPageRecord(
                rows=page_rows,
                total=int(logs_manifest.get("total") or 0),
                facets={
                    str(name): {str(key): int(value) for key, value in values.items()}
                    for name, values in dict(logs_manifest.get("facets") or {}).items()
                    if isinstance(values, dict)
                },
                template_text_by_id=templates,
            )

        page_rows = []
        total = 0
        service_counts: Counter[str] = Counter()
        signal_counts: Counter[str] = Counter()
        fault_counts: Counter[str] = Counter()
        for _, chunk in iter_log_chunks(payload, settings=self.settings):
            for line in chunk:
                if not self._analysis_log_matches(
                    line,
                    template_text_by_id=templates,
                    window_start=window_start,
                    window_end=window_end,
                    q=q,
                    service=service,
                ):
                    continue
                if offset <= total < offset + limit:
                    page_rows.append(line)
                total += 1
                service_counts[line.service or "unknown"] += 1
                signal_counts[line.golden_signal] += 1
                fault_counts.update(line.fault_categories)
        return AnalysisLogPageRecord(
            rows=page_rows,
            total=total,
            facets={
                "service": dict(service_counts),
                "golden_signal": dict(signal_counts),
                "fault_category": dict(fault_counts),
            },
            template_text_by_id=templates,
        )

    @staticmethod
    def _analysis_log_matches(
        line: NormalizedLogLine,
        *,
        template_text_by_id: dict[str, str],
        window_start: datetime | None,
        window_end: datetime | None,
        q: str | None,
        service: str | None,
    ) -> bool:
        if window_start and (line.timestamp is None or line.timestamp < window_start):
            return False
        if window_end and (line.timestamp is None or line.timestamp > window_end):
            return False
        if service and line.service != service:
            return False
        if q:
            lowered = q.lower()
            if (
                lowered not in line.redacted_message.lower()
                and lowered
                not in template_text_by_id.get(line.template_id or "", "").lower()
                and not any(
                    lowered in value.lower()
                    for values in line.entities.values()
                    for value in values
                )
            ):
                return False
        return True

    @staticmethod
    def _analysis_log_facets(
        rows: list[NormalizedLogLine],
    ) -> dict[str, dict[str, int]]:
        return {
            "service": dict(Counter(line.service or "unknown" for line in rows)),
            "golden_signal": dict(Counter(line.golden_signal for line in rows)),
            "fault_category": dict(
                Counter(category for line in rows for category in line.fault_categories)
            ),
        }

    def fail_interrupted_analysis_runs(self) -> int:
        with self._session() as session:
            rows = session.scalars(
                select(tables.AnalysisRun)
                .options(defer(tables.AnalysisRun.result_json))
                .where(tables.AnalysisRun.status.in_({"queued", "processing"}))
            ).all()
            if not rows:
                return 0
            failed_at = _now()
            error_message = "analysis was interrupted by an API restart"
            for row in rows:
                progress = dict(row.progress_json or {})
                progress["current_step"] = "failed"
                progress["failed_at"] = failed_at.isoformat()
                progress["error_message"] = error_message
                row.status = "failed"
                row.progress_json = progress
                row.completed_at = failed_at
                row.error_message = error_message
                case_row = session.get(tables.Case, row.case_id)
                if case_row is not None:
                    case_row.status = "failed"
                    case_row.updated_at = failed_at
            return len(rows)

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
            result=None,
            progress=dict(row.progress_json or {}),
        )
