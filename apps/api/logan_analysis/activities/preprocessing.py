from __future__ import annotations

import os
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime
from typing import Any

from logan_analysis.algorithms.multiline import merge_physical_lines
from logan_analysis.algorithms.parsers import normalize_message, parse_log_message, parse_timestamp
from logan_analysis.algorithms.redactors import Redactor
from logan_analysis.algorithms.template_extractor import TemplateExtractor
from logan_analysis.models import IngestedFile, LogEntry, NormalizedLogLine

# Preprocessing is pure-CPU regex work, so multi-million-line runs are spread
# over worker processes. Below this entry count the pool spawn cost outweighs
# the win and everything runs inline.
PARALLEL_THRESHOLD_ENTRIES = 50_000
CHUNK_SIZE = 20_000
MAX_WORKERS = 8

_NORMALIZED_LINE_FIELDS = set(NormalizedLogLine.model_fields)


def _fast_normalized_line(values: dict[str, Any]) -> NormalizedLogLine:
    """Build a NormalizedLogLine without per-field validation or copying.

    `model_construct` spends ~60us per instance looping fields; at millions of
    lines that alone costs minutes. All values here are produced internally with
    the correct types, so the instance is assembled directly. The slot layout is
    asserted by tests/analysis/test_boundaries.py.
    """
    line = object.__new__(NormalizedLogLine)
    object.__setattr__(line, "__dict__", values)
    object.__setattr__(line, "__pydantic_fields_set__", _NORMALIZED_LINE_FIELDS)
    object.__setattr__(line, "__pydantic_extra__", None)
    object.__setattr__(line, "__pydantic_private__", None)
    return line


def merge_entries(files: list[IngestedFile]) -> list[LogEntry]:
    entries: list[LogEntry] = []
    for file in files:
        entries.extend(merge_physical_lines(file.lines))
    return sorted(entries, key=lambda entry: entry.ingestion_order)


def _preprocess_chunk(
    raw_messages: list[str],
) -> tuple[
    list[datetime | None],
    list[str],
    list[str | None],
    list[str | None],
    list[str],
    list[dict[str, Any] | None],
    list[int],
    list[str],
]:
    """Worker payload: raw messages in, columnar per-line results out.

    Runs in a separate process; only plain values cross the boundary. Template
    texts are deduplicated per chunk and referenced by index so the response
    stays small.
    """
    redactor = Redactor()
    extractor = TemplateExtractor()
    timestamps: list[datetime | None] = []
    qualities: list[str] = []
    levels: list[str | None] = []
    services: list[str | None] = []
    messages: list[str] = []
    extra_fields: list[dict[str, Any] | None] = []
    template_indexes: list[int] = []
    template_texts: list[str] = []
    template_index_by_text: dict[str, int] = {}

    for raw_message in raw_messages:
        timestamp, quality = parse_timestamp(raw_message)
        parsed = parse_log_message(raw_message)
        redacted = redactor.redact(str(parsed.get("message") or raw_message))
        fields: dict[str, Any] = {
            key: value
            for key, value in parsed.items()
            if key not in {"json", "message", "level", "service"}
        }
        if redacted.replacements:
            fields["redaction_counts"] = redacted.replacements

        head, newline, _ = redacted.text.partition("\n")
        normalized = normalize_message(head if newline else redacted.text)
        template_text = extractor.to_template(normalized)
        template_index = template_index_by_text.get(template_text)
        if template_index is None:
            template_index = len(template_texts)
            template_index_by_text[template_text] = template_index
            template_texts.append(template_text)

        timestamps.append(timestamp)
        qualities.append(quality)
        levels.append(parsed.get("level"))
        services.append(parsed.get("service"))
        messages.append(redacted.text)
        extra_fields.append(fields or None)
        template_indexes.append(template_index)

    return (
        timestamps,
        qualities,
        levels,
        services,
        messages,
        extra_fields,
        template_indexes,
        template_texts,
    )


def _worker_count(entry_count: int) -> int:
    cores = os.cpu_count() or 2
    by_size = -(-entry_count // CHUNK_SIZE)
    return max(1, min(MAX_WORKERS, cores - 1, by_size))


def preprocess_entries(
    *,
    case_id: str,
    analysis_run_id: str,
    entries: list[LogEntry],
) -> list[NormalizedLogLine]:
    chunks = [
        entries[start : start + CHUNK_SIZE]
        for start in range(0, len(entries), CHUNK_SIZE)
    ]
    payloads = [[entry.raw_message for entry in chunk] for chunk in chunks]

    if len(entries) >= PARALLEL_THRESHOLD_ENTRIES:
        workers = _worker_count(len(entries))
        with ProcessPoolExecutor(max_workers=workers) as pool:
            results = list(pool.map(_preprocess_chunk, payloads))
    else:
        results = [_preprocess_chunk(payload) for payload in payloads]

    normalized: list[NormalizedLogLine] = []
    previous_timestamp: datetime | None = None
    for chunk, result in zip(chunks, results):
        (
            timestamps,
            qualities,
            levels,
            services,
            messages,
            extra_fields,
            template_indexes,
            template_texts,
        ) = result
        for position, entry in enumerate(chunk):
            timestamp = timestamps[position]
            quality = qualities[position]
            if timestamp is None and previous_timestamp is not None:
                timestamp = previous_timestamp
                quality = "inferred_from_previous"
            if timestamp is not None:
                previous_timestamp = timestamp

            fields = extra_fields[position] or {}
            if len(entry.line_numbers) > 1:
                fields = dict(fields)
                fields["stack_trace_lines"] = entry.line_numbers
            message = messages[position]
            normalized.append(
                _fast_normalized_line(
                    {
                        "log_id": entry.log_id,
                        "raw_log_id": entry.log_id,
                        "case_id": case_id,
                        "analysis_run_id": analysis_run_id,
                        "file_id": entry.file_id,
                        "file_path": entry.file_path,
                        "line_number": entry.line_number,
                        "line_numbers": entry.line_numbers,
                        "timestamp": timestamp,
                        "timestamp_quality": quality,
                        "level": levels[position],
                        "service": services[position],
                        "message": message,
                        # Only consumed as template input, which the worker has
                        # already produced; left empty to save time and memory.
                        "normalized_message": "",
                        "redacted_message": message,
                        "parsed_fields": fields,
                        "parser_name": "logan_regex_v1",
                        "parser_confidence": 0.9 if timestamp else 0.4,
                        "ingestion_order": entry.ingestion_order,
                        "template_id": None,
                        "template_text": template_texts[template_indexes[position]],
                        "golden_signal": "unknown",
                        "fault_categories": [],
                        "entities": {},
                        "severity_score": 0.0,
                        "confidence": 0.0,
                    }
                )
            )
        # The raw entry text is no longer needed once its normalized line exists;
        # dropping it early halves peak memory on large runs.
        for entry in chunk:
            entry.__dict__["raw_message"] = ""

    return sorted(
        normalized,
        key=lambda line: (line.timestamp is None, line.timestamp, line.ingestion_order),
    )
