from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Any


ISO_RE = re.compile(r"\[?(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z?)\]?")
SPACE_MS_RE = re.compile(r"(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})(?:[,.](\d{1,6}))?(?:\s+([+-]\d{4}))?")
SYSLOG_RE = re.compile(
    r"^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{1,2})\s+(\d{2}:\d{2}:\d{2})"
)
LEVEL_RE = re.compile(r"\b(TRACE|DEBUG|INFO|WARN|WARNING|ERROR|FATAL|CRITICAL)\b", re.IGNORECASE)
SERVICE_RE = re.compile(r"\b([A-Za-z][A-Za-z0-9_-]*(?:-service|gateway|api|worker|auth|payment))\b")
REQUEST_RE = re.compile(r"\brequest_id=([A-Za-z0-9._:-]+)\b")
TRACE_RE = re.compile(r"\btrace_id=([A-Za-z0-9._:-]+)\b")
THREAD_RE = re.compile(r"\bthread(?:_id)?=([A-Za-z0-9._:-]+)\b")

MONTHS = {
    "Jan": 1,
    "Feb": 2,
    "Mar": 3,
    "Apr": 4,
    "May": 5,
    "Jun": 6,
    "Jul": 7,
    "Aug": 8,
    "Sep": 9,
    "Oct": 10,
    "Nov": 11,
    "Dec": 12,
}


def parse_timestamp(text: str, *, reference_year: int = 2026) -> tuple[datetime | None, str]:
    stripped = text.strip()
    if stripped.startswith("{"):
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError:
            payload = {}
        for key in ("timestamp", "time", "ts"):
            if key in payload:
                return parse_timestamp(str(payload[key]), reference_year=reference_year)

    iso = ISO_RE.search(text)
    if iso:
        value = iso.group(1).replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(value).astimezone(UTC), "parsed"
        except ValueError:
            return None, "invalid"

    space = SPACE_MS_RE.search(text)
    if space:
        base = space.group(1)
        micros = (space.group(2) or "0").ljust(6, "0")
        offset = space.group(3)
        try:
            if offset:
                dt = datetime.strptime(f"{base}.{micros} {offset}", "%Y-%m-%d %H:%M:%S.%f %z")
            else:
                dt = datetime.strptime(f"{base}.{micros}", "%Y-%m-%d %H:%M:%S.%f").replace(tzinfo=UTC)
            return dt.astimezone(UTC), "parsed"
        except ValueError:
            return None, "invalid"

    syslog = SYSLOG_RE.search(text)
    if syslog:
        try:
            hour, minute, second = [int(part) for part in syslog.group(3).split(":")]
            return (
                datetime(
                    reference_year,
                    MONTHS[syslog.group(1)],
                    int(syslog.group(2)),
                    hour,
                    minute,
                    second,
                    tzinfo=UTC,
                ),
                "parsed",
            )
        except ValueError:
            return None, "invalid"
    return None, "missing"


def normalize_message(text: str) -> str:
    text = text.strip().lower()
    text = re.sub(r"\s+", " ", text)
    return text


def parse_log_message(text: str) -> dict[str, Any]:
    parsed: dict[str, Any] = {}
    stripped = text.strip()
    message = text
    if stripped.startswith("{"):
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError:
            payload = {}
        if payload:
            message = str(payload.get("message") or payload.get("msg") or payload.get("log") or text)
            parsed["json"] = payload

    level_match = LEVEL_RE.search(text)
    if level_match:
        level = level_match.group(1).upper()
        parsed["level"] = "WARN" if level == "WARNING" else level

    service_match = SERVICE_RE.search(text)
    if service_match:
        parsed["service"] = service_match.group(1)

    for key, pattern in (
        ("request_id", REQUEST_RE),
        ("trace_id", TRACE_RE),
        ("thread_id", THREAD_RE),
    ):
        match = pattern.search(text)
        if match:
            parsed[key] = match.group(1)

    parsed["message"] = message
    return parsed
