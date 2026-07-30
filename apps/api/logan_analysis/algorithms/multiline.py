from __future__ import annotations

import re

from logan_analysis.models import LogEntry, RawPhysicalLine


HEADER_RE = re.compile(
    r"^(?:"
    r"\[?\d{4}-\d{2}-\d{2}[T |]\d{2}:\d{2}:\d{2}"
    r"|\|[A-Z]+\|\d{4}-\d{2}-\d{2}\|\d{2}:\d{2}:\d{2}"
    r"|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}"
    r'|\s*\{.*"(?:timestamp|time|ts)"\s*:'
    r")"
)

STACK_CONTINUATION_RE = re.compile(
    r"^\s+(?:at\s+|File\s+\"|\.{3}|\w+\.\w+\(|Caused by:|goroutine\s+|from\s+)|^\s*\^\s*$"
)
PANIC_RE = re.compile(r"^(panic:|Traceback \(most recent call last\):|Error: )")

# Continuation lines (stack traces, wrapped payloads, framework object dumps) can run
# long, but an entry must stay bounded so a pathological file cannot collapse into a
# single log line or exhaust memory on merged messages.
MAX_CONTINUATION_LINES = 2000
MAX_ENTRY_CHARS = 512 * 1024

_LOG_ENTRY_FIELDS = set(LogEntry.model_fields)


def has_log_header(line: str) -> bool:
    return HEADER_RE.match(line) is not None


def is_continuation(line: str, has_previous: bool) -> bool:
    if not has_previous:
        return False
    if has_log_header(line):
        return False
    return True


def merge_physical_lines(lines: list[RawPhysicalLine]) -> list[LogEntry]:
    entries: list[LogEntry] = []
    current: dict[str, object] | None = None
    current_headed = False
    current_chars = 0

    def flush() -> None:
        nonlocal current
        if not current:
            return
        line_numbers = current["line_numbers"]
        raw_line_ids = current["raw_line_ids"]
        entry = object.__new__(LogEntry)
        object.__setattr__(
            entry,
            "__dict__",
            {
                "log_id": raw_line_ids[0],  # type: ignore[index]
                "file_id": current["file_id"],
                "file_path": current["file_path"],
                "line_number": line_numbers[0],  # type: ignore[index]
                "line_numbers": line_numbers,
                "raw_message": "\n".join(current["messages"]),  # type: ignore[index,arg-type]
                "raw_line_ids": raw_line_ids,
                "sha256": "",
                "ingestion_order": current["ingestion_order"],
            },
        )
        object.__setattr__(entry, "__pydantic_fields_set__", _LOG_ENTRY_FIELDS)
        object.__setattr__(entry, "__pydantic_extra__", None)
        object.__setattr__(entry, "__pydantic_private__", None)
        entries.append(entry)
        current = None

    for raw_line in lines:
        text = raw_line.raw_text
        if not text.strip():
            # Blank lines inside an ongoing multi-line block (object dumps) are kept;
            # stray blanks between entries are dropped instead of becoming entries.
            if (
                current is not None
                and current_headed
                and len(current["line_numbers"]) > 1  # type: ignore[index,arg-type]
                and len(current["line_numbers"]) < MAX_CONTINUATION_LINES  # type: ignore[index,arg-type]
                and current_chars + 1 < MAX_ENTRY_CHARS
            ):
                current["messages"].append(text)  # type: ignore[index,union-attr]
                current["line_numbers"].append(raw_line.line_number)  # type: ignore[index,union-attr]
                current["raw_line_ids"].append(raw_line.raw_line_id)  # type: ignore[index,union-attr]
                current_chars += len(text) + 1
            continue
        headed = has_log_header(text)
        # A headerless line continues the previous entry when that entry started with
        # a real log header (stack traces, exception headers, object dumps). In files
        # with no headers at all, every line stays its own entry, so a plain-text file
        # cannot collapse into one giant record.
        merge_into_current = (
            current is not None
            and not headed
            and (
                current_headed
                or STACK_CONTINUATION_RE.search(text)
                or PANIC_RE.search(text)
            )
            and len(current["line_numbers"]) < MAX_CONTINUATION_LINES  # type: ignore[index,arg-type]
            and current_chars + len(text) < MAX_ENTRY_CHARS
        )
        if merge_into_current:
            current["messages"].append(text)  # type: ignore[index,union-attr]
            current["line_numbers"].append(raw_line.line_number)  # type: ignore[index,union-attr]
            current["raw_line_ids"].append(raw_line.raw_line_id)  # type: ignore[index,union-attr]
            current_chars += len(text) + 1
            continue

        flush()
        current = {
            "file_id": raw_line.file_id,
            "file_path": raw_line.file_path,
            "line_numbers": [raw_line.line_number],
            "messages": [text],
            "raw_line_ids": [raw_line.raw_line_id],
            "ingestion_order": raw_line.ingestion_order,
        }
        current_headed = headed
        current_chars = len(text)
    flush()
    return entries
