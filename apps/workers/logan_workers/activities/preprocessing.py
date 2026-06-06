from __future__ import annotations

from datetime import datetime

from logan_workers.algorithms.multiline import merge_physical_lines
from logan_workers.algorithms.parsers import normalize_message, parse_log_message, parse_timestamp
from logan_workers.algorithms.redactors import Redactor
from logan_workers.models import IngestedFile, LogEntry, NormalizedLogLine


def merge_entries(files: list[IngestedFile]) -> list[LogEntry]:
    entries: list[LogEntry] = []
    for file in files:
        entries.extend(merge_physical_lines(file.lines))
    return sorted(entries, key=lambda entry: entry.ingestion_order)


def preprocess_entries(
    *,
    case_id: str,
    analysis_run_id: str,
    entries: list[LogEntry],
    redaction_mode: str = "mask",
) -> list[NormalizedLogLine]:
    redactor = Redactor(mode=redaction_mode)
    normalized: list[NormalizedLogLine] = []
    previous_timestamp: datetime | None = None
    for entry in entries:
        timestamp, timestamp_quality = parse_timestamp(entry.raw_message)
        if timestamp is None and previous_timestamp is not None:
            timestamp = previous_timestamp
            timestamp_quality = "inferred_from_previous"
        if timestamp:
            previous_timestamp = timestamp

        parsed = parse_log_message(entry.raw_message)
        redacted = redactor.redact(str(parsed.get("message") or entry.raw_message))
        parsed_fields = {
            key: value
            for key, value in parsed.items()
            if key not in {"message", "level", "service"}
        }
        parsed_fields["redaction_counts"] = redacted.replacements
        if len(entry.line_numbers) > 1:
            parsed_fields["stack_trace_lines"] = entry.line_numbers
        normalized.append(
            NormalizedLogLine(
                log_id=entry.log_id,
                raw_log_id=entry.log_id,
                case_id=case_id,
                analysis_run_id=analysis_run_id,
                file_id=entry.file_id,
                file_path=entry.file_path,
                line_number=entry.line_number,
                line_numbers=entry.line_numbers,
                timestamp=timestamp,
                timestamp_quality=timestamp_quality,
                level=parsed.get("level"),
                service=parsed.get("service"),
                message=str(parsed.get("message") or entry.raw_message),
                normalized_message=normalize_message(redacted.text),
                redacted_message=redacted.text,
                parsed_fields=parsed_fields,
                parser_confidence=0.9 if timestamp else 0.4,
                ingestion_order=entry.ingestion_order,
            )
        )
    return sorted(
        normalized,
        key=lambda line: (line.timestamp is None, line.timestamp, line.ingestion_order),
    )
