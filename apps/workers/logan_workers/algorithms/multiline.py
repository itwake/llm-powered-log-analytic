from __future__ import annotations

import hashlib
import re
import uuid

from logan_workers.models import LogEntry, RawPhysicalLine


HEADER_PATTERNS = [
    re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}"),
    re.compile(r"^\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}"),
    re.compile(r"^\[\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}"),
    re.compile(r"^(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}"),
    re.compile(r'^\s*\{.*"(?:timestamp|time|ts)"\s*:'),
]

STACK_CONTINUATION_RE = re.compile(
    r"^\s+(?:at\s+|File\s+\"|\.{3}|\w+\.\w+\(|Caused by:|goroutine\s+|from\s+)|^\s*\^\s*$"
)
PANIC_RE = re.compile(r"^(panic:|Traceback \(most recent call last\):|Error: )")


def has_log_header(line: str) -> bool:
    return any(pattern.search(line) for pattern in HEADER_PATTERNS)


def is_continuation(line: str, has_previous: bool) -> bool:
    if not has_previous:
        return False
    if has_log_header(line):
        return False
    if STACK_CONTINUATION_RE.search(line) or PANIC_RE.search(line):
        return True
    return True


def merge_physical_lines(lines: list[RawPhysicalLine]) -> list[LogEntry]:
    entries: list[LogEntry] = []
    current: dict[str, object] | None = None

    def flush() -> None:
        nonlocal current
        if not current:
            return
        raw_message = "\n".join(current["messages"])  # type: ignore[index]
        digest = hashlib.sha256(raw_message.encode()).hexdigest()
        entries.append(
            LogEntry(
                log_id=str(uuid.uuid4()),
                file_id=str(current["file_id"]),
                file_path=str(current["file_path"]),
                line_number=int(current["line_numbers"][0]),  # type: ignore[index]
                line_numbers=list(current["line_numbers"]),  # type: ignore[arg-type]
                raw_message=raw_message,
                raw_line_ids=list(current["raw_line_ids"]),  # type: ignore[arg-type]
                sha256=digest,
                ingestion_order=int(current["ingestion_order"]),
            )
        )
        current = None

    for raw_line in lines:
        if current and is_continuation(raw_line.raw_text, has_previous=True):
            current["messages"].append(raw_line.raw_text)  # type: ignore[index,union-attr]
            current["line_numbers"].append(raw_line.line_number)  # type: ignore[index,union-attr]
            current["raw_line_ids"].append(raw_line.raw_line_id)  # type: ignore[index,union-attr]
            continue

        flush()
        current = {
            "file_id": raw_line.file_id,
            "file_path": raw_line.file_path,
            "line_numbers": [raw_line.line_number],
            "messages": [raw_line.raw_text],
            "raw_line_ids": [raw_line.raw_line_id],
            "ingestion_order": raw_line.ingestion_order,
        }
    flush()
    return entries
