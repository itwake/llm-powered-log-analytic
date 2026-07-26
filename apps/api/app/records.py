from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from logan_analysis.models import AnalysisResult

TERMINAL_ANALYSIS_RUN_STATUSES = {"completed", "failed", "cancelled"}
CANCELLABLE_ANALYSIS_RUN_STATUSES = {"queued", "processing", "running"}


class AnalysisRunCancelled(RuntimeError):
    pass


@dataclass
class UserRecord:
    id: str
    email: str
    username: str
    full_name: str | None
    external_id: str | None
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
    model_provider: str
    model_name: str
    created_by: str
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error_message: str | None = None
    result: AnalysisResult | None = None
    progress: dict[str, Any] = field(default_factory=dict)


def sanitize_error_message(error: BaseException | str, *, max_length: int = 1000) -> str:
    message = str(error).strip() or "analysis failed"
    message = re.sub(r"(?i)(password|token|secret|authorization)=?[^,\s]*", r"\1=[redacted]", message)
    home = str(Path.home())
    if home:
        message = message.replace(home, "<home>")
    return message[:max_length]
