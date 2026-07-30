from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from logan_analysis.algorithms.redactors import redact_text
from logan_analysis.models import AnalysisResult, NormalizedLogLine

TERMINAL_ANALYSIS_RUN_STATUSES = {"completed", "failed", "cancelled"}
_SENSITIVE_ERROR_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"(?i)(authorization\s*[:=]\s*bearer\s+)[^\s,;]+"),
        r"\1[redacted]",
    ),
    (re.compile(r"(?i)(bearer\s+)[^\s,;]+"), r"\1[redacted]"),
    (
        re.compile(
            r"(?i)\b(token|api[_-]?key|password|passwd|secret|credential|"
            r"source[_-]?token)\s*[:=]\s*[^,\s;]+"
        ),
        r"\1=[redacted]",
    ),
    (
        re.compile(
            r"\b(?:github_pat_[A-Za-z0-9_]+|gh[opsru]_[A-Za-z0-9_]+|"
            r"sk-[A-Za-z0-9_-]{10,}|"
            r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+)\b"
        ),
        "[redacted-token]",
    ),
    (
        re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://[^/\s:@]+:)[^@\s/]+(@)"),
        r"\1[redacted]\2",
    ),
)
_WINDOWS_PATH_RE = re.compile(r"(?i)(?:\b[A-Z]:[\\/]|\\\\)[^,\s;]+")
_POSIX_PATH_RE = re.compile(r"(?<![A-Za-z0-9:/])/(?:[^,\s;]+)")
_SAFE_ERROR_DIAGNOSTIC_KEYS = (
    "artifact",
    "operation",
    "attempt",
    "parent_exists",
    "parent_is_directory",
    "missing_parent_depth",
    "path_is_absolute",
    "temporary_path_length",
    "absolute_temporary_path_length",
    "cwd_is_directory",
)
_SAFE_ERROR_DIAGNOSTIC_VALUE_RE = re.compile(r"^[A-Za-z0-9._-]+$")


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


@dataclass
class AnalysisLogPageRecord:
    rows: list[NormalizedLogLine]
    total: int
    facets: dict[str, dict[str, int]]
    template_text_by_id: dict[str, str]


def sanitize_error_message(error: BaseException | str, *, max_length: int = 1000) -> str:
    message = str(error).strip() or "analysis failed"
    home = str(Path.home())
    if home:
        message = message.replace(home, "<path>")
    message = redact_text(message)
    for pattern, replacement in _SENSITIVE_ERROR_PATTERNS:
        message = pattern.sub(replacement, message)
    message = _WINDOWS_PATH_RE.sub("<path>", message)
    message = _POSIX_PATH_RE.sub("<path>", message)
    return message[:max_length]


def safe_error_diagnostics(error: BaseException) -> dict[str, str | int | bool]:
    values = getattr(error, "_logan_safe_diagnostics", None)
    if not isinstance(values, dict):
        return {}
    diagnostics: dict[str, str | int | bool] = {}
    for key in _SAFE_ERROR_DIAGNOSTIC_KEYS:
        value = values.get(key)
        if isinstance(value, bool):
            diagnostics[key] = value
        elif isinstance(value, int):
            diagnostics[key] = value
        elif (
            isinstance(value, str)
            and len(value) <= 80
            and _SAFE_ERROR_DIAGNOSTIC_VALUE_RE.fullmatch(value)
        ):
            diagnostics[key] = value
    return diagnostics
