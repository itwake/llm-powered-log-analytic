from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypeAlias

from logan_analysis.models import AnalysisResult

from app.config import Settings, settings

TERMINAL_ANALYSIS_RUN_STATUSES = {"completed", "failed", "cancelled"}
CANCELLABLE_ANALYSIS_RUN_STATUSES = {"queued", "processing", "running"}
EPHEMERAL_SQLITE_DATABASE_URL = "sqlite+pysqlite:///:memory:"

MetadataStore: TypeAlias = Any


class AnalysisRunCancelled(RuntimeError):
    pass


@dataclass
class UserRecord:
    id: str
    email: str
    username: str
    full_name: str | None
    external_id: str | None
    is_active: bool
    created_at: datetime


@dataclass
class SessionRecord:
    id: str
    user_id: str
    token_hash: str
    expires_at: datetime
    created_at: datetime
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
    timezone: str
    status: str
    created_by: str
    created_at: datetime


@dataclass
class UploadRecord:
    id: str
    case_id: str
    filename: str
    content_type: str | None
    size_bytes: int
    object_uri: str
    sha256: str | None
    completed: bool
    created_at: datetime


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
    prompt_version: str
    created_by: str
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
    metadata: dict[str, Any]
    error_message: str | None
    created_at: datetime


def sanitize_error_message(error: BaseException | str) -> str:
    message = str(error).strip() or "analysis failed"
    message = re.sub(r"(?i)(password|token|secret|authorization)=?[^,\s]*", r"\1=[redacted]", message)
    home = str(Path.home())
    if home:
        message = message.replace(home, "<home>")
    return message[:1000]


def sanitize_job_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    if not metadata:
        return {}
    return {
        str(key): value
        for key, value in metadata.items()
        if str(key).lower() not in {"password", "token", "secret", "authorization"}
    }


def merge_event_progress(progress: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
    merged = dict(progress)
    steps = dict(merged.get("steps") or {})
    step_name = str(event["step_name"])
    step = dict(steps.get(step_name) or {})
    event_type = str(event["event_type"])
    step["status"] = str(event["status"])
    step["attempt"] = int(event.get("attempt") or 1)
    step[f"{event_type}_at"] = str(event.get("created_at") or datetime.now(UTC).isoformat())
    metadata = sanitize_job_metadata(event.get("metadata"))
    if metadata:
        step["metadata"] = metadata
        merged.update(metadata)
    if event.get("error_message"):
        step["error_message"] = sanitize_error_message(str(event["error_message"]))
    steps[step_name] = step
    merged["steps"] = steps
    merged["current_step"] = step_name
    return merged


def create_ephemeral_store(app_settings: Settings = settings) -> MetadataStore:
    from app.sqlalchemy_store import SQLAlchemyStore

    return SQLAlchemyStore(
        app_settings=app_settings,
        database_url=EPHEMERAL_SQLITE_DATABASE_URL,
    )


def create_store(app_settings: Settings = settings) -> MetadataStore:
    from app.sqlalchemy_store import SQLAlchemyStore

    return SQLAlchemyStore(
        app_settings=app_settings,
        database_url=app_settings.database_url,
    )
