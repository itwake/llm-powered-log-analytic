from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta, timezone
from typing import Any


# One combined pattern covers the observed timestamp shapes:
#   2026-06-22T07:37:41.437Z        (ISO, optional offset)
#   [2026-06-22 07:37:41,437]       (space-separated, comma millis)
#   2026-06-16|19:31:12,703|        (pipe-delimited date|time)
#   |ERROR|2023-09-18|17:31:26,352| (level-first pipe format: same date|time shape)
# The date/time separator is captured so all variants share one manual int parse,
# which is far cheaper than strptime.
TS_RE = re.compile(
    r"(\d{4})-(\d{2})-(\d{2})[T |](\d{2}):(\d{2}):(\d{2})"
    r"(?:[.,](\d{1,6}))?"
    r"(?:(Z)|([+-]\d{2}):?(\d{2}))?"
)
SYSLOG_RE = re.compile(
    r"^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{1,2})\s+(\d{2}:\d{2}:\d{2})"
)
LEVEL_RE = re.compile(r"\b(TRACE|DEBUG|INFO|WARN|WARNING|ERROR|FATAL|CRITICAL)\b", re.IGNORECASE)
# Service extraction, in priority order:
#   [Service Name:UPDTANNC]                      -> UPDTANNC
#   |COMP_COMMON_IN|746280|                      -> COMP_COMMON_IN (component field)
#   com.tcs.ncs.stp.delegates.NtfctnUpdtAnncSTP  -> NtfctnUpdtAnncSTP (logger class)
#   payment-service / api-gateway                -> conventional service names
SERVICE_NAME_RE = re.compile(r"Service Name\s*:\s*([A-Za-z0-9_-]+)")
PIPE_COMPONENT_RE = re.compile(r"\|([A-Z][A-Z0-9_]{2,40})\|\d+\|")
JAVA_CLASS_RE = re.compile(r"\b(?:[a-z][a-z0-9_]*\.){2,}([A-Z][A-Za-z0-9_$]+)")
SERVICE_RE = re.compile(r"\b([A-Za-z][A-Za-z0-9_-]*(?:-service|gateway|api|worker|auth|payment))\b")
REQUEST_RE = re.compile(r"\brequest_id=([A-Za-z0-9._:-]+)\b")
TRACE_RE = re.compile(r"\btrace_id=([A-Za-z0-9._:-]+)\b")
THREAD_RE = re.compile(r"\bthread(?:_id)?=([A-Za-z0-9._:-]+)\b")

# Timestamps live near the start of a line in every supported format; scanning a
# bounded prefix keeps multi-hundred-KiB merged entries (stack traces, object
# dumps) from turning timestamp parsing into a full-text scan.
TIMESTAMP_SCAN_CHARS = 256

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


def _timestamp_from_match(match: re.Match[str]) -> datetime | None:
    try:
        micros = int((match.group(7) or "0").ljust(6, "0")[:6])
        if match.group(9) is not None:
            tz: timezone = timezone(
                timedelta(
                    hours=int(match.group(9)),
                    minutes=int(match.group(10)) * (1 if match.group(9).startswith("+") else -1),
                )
            )
        else:
            tz = UTC
        return datetime(
            int(match.group(1)),
            int(match.group(2)),
            int(match.group(3)),
            int(match.group(4)),
            int(match.group(5)),
            int(match.group(6)),
            micros,
            tzinfo=tz,
        ).astimezone(UTC)
    except ValueError:
        return None


def parse_timestamp(text: str, *, reference_year: int = 2026) -> tuple[datetime | None, str]:
    head = text[:TIMESTAMP_SCAN_CHARS]
    stripped = head.lstrip()
    if stripped.startswith("{"):
        try:
            payload = json.loads(text.strip())
        except json.JSONDecodeError:
            payload = {}
        for key in ("timestamp", "time", "ts"):
            if key in payload:
                return parse_timestamp(str(payload[key]), reference_year=reference_year)

    match = TS_RE.search(head)
    if match:
        parsed = _timestamp_from_match(match)
        return (parsed, "parsed") if parsed else (None, "invalid")

    syslog = SYSLOG_RE.search(head)
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


def extract_service(text: str) -> str | None:
    named = SERVICE_NAME_RE.search(text)
    if named:
        return named.group(1)
    component = PIPE_COMPONENT_RE.search(text)
    if component:
        return component.group(1)
    java_class = JAVA_CLASS_RE.search(text)
    if java_class:
        return java_class.group(1)
    conventional = SERVICE_RE.search(text)
    if conventional:
        return conventional.group(1)
    return None


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

    # Structured metadata lives near the entry head; bounding these scans keeps
    # multi-hundred-KiB merged entries (stack traces, object dumps) cheap.
    head = text[:TIMESTAMP_SCAN_CHARS]
    scan = text[:4096]
    level_match = LEVEL_RE.search(head) or LEVEL_RE.search(scan)
    if level_match:
        level = level_match.group(1).upper()
        parsed["level"] = "WARN" if level == "WARNING" else level

    service = extract_service(scan)
    if service:
        parsed["service"] = service

    if "request_id=" in scan:
        match = REQUEST_RE.search(scan)
        if match:
            parsed["request_id"] = match.group(1)
    if "trace_id=" in scan:
        match = TRACE_RE.search(scan)
        if match:
            parsed["trace_id"] = match.group(1)
    if "thread_id=" in scan or "thread=" in scan:
        match = THREAD_RE.search(scan)
        if match:
            parsed["thread_id"] = match.group(1)

    parsed["message"] = message
    return parsed
