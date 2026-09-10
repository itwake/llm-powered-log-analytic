from __future__ import annotations

import hashlib
import uuid
import zlib
from array import array
from bisect import bisect_right
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from logan_analysis.models import (
    AnalysisReportSummary,
    AnalysisResult,
    CausalGraph,
    CausalSummary,
    NormalizedLogLine,
    WindowAggregate,
)
from pydantic import TypeAdapter

from app.config import Settings
from app.services.object_store import file_uri_to_path, path_to_file_uri, safe_filename

RESULT_MANIFEST_FORMAT = "logan.analysis-result-manifest"
RESULT_MANIFEST_VERSION = 2
RESULT_ARTIFACT_ENCODING = "zlib"
# Small chunks keep "decode only the chunks a page needs" cheap even when the
# selected rows are scattered across the whole run.
RESULT_LOG_CHUNK_SIZE = 2_000
# Separates per-row search texts in the search blob so a query can never match
# across a row boundary.
_SEARCH_ROW_SEPARATOR = b"\x1e"

_LOGS_ADAPTER = TypeAdapter(list[NormalizedLogLine])
_TEMPORAL_ADAPTER = TypeAdapter(list[WindowAggregate])
_PERSISTED_LOG_EXCLUDE = {
    "__all__": {
        "message",
        "normalized_message",
        "parsed_fields",
        "template_text",
    }
}


def is_analysis_result_manifest(payload: dict[str, Any]) -> bool:
    return (
        payload.get("format") == RESULT_MANIFEST_FORMAT
        and payload.get("version") == RESULT_MANIFEST_VERSION
    )


def _result_directory(
    *,
    case_id: str,
    analysis_run_id: str,
    settings: Settings,
) -> Path:
    return (
        Path(settings.local_object_store_dir).expanduser().resolve()
        / "cases"
        / safe_filename(case_id)
        / "analysis-runs"
        / safe_filename(analysis_run_id)
        / "result"
    )


def write_artifact(path: Path, raw: bytes) -> dict[str, Any]:
    compressed = zlib.compress(raw, level=1)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Keep the full random suffix without repeating the target name. On
    # Windows, the repeated name can push an otherwise valid result path
    # beyond the legacy 260-character boundary during the temporary write.
    temporary = path.with_name(f".{uuid.uuid4().hex}.part")
    try:
        temporary.write_bytes(compressed)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    return {
        "object_uri": path_to_file_uri(path),
        "encoding": RESULT_ARTIFACT_ENCODING,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "size_bytes": len(compressed),
        "uncompressed_size_bytes": len(raw),
    }


def _summary_projection(result: AnalysisResult) -> AnalysisReportSummary:
    return AnalysisReportSummary(
        case_id=result.case_id,
        analysis_run_id=result.analysis_run_id,
        files=[file.model_copy(update={"lines": []}) for file in result.files],
        templates=result.templates,
        samples=result.samples,
        annotations=result.annotations,
        log_facets=result.log_facets,
        progress=result.progress,
    )


def write_analysis_result_manifest(
    result: AnalysisResult,
    *,
    settings: Settings,
) -> dict[str, Any]:
    result_directory = _result_directory(
        case_id=result.case_id,
        analysis_run_id=result.analysis_run_id,
        settings=settings,
    )
    written_paths: list[Path] = []
    try:
        sections: dict[str, dict[str, Any]] = {}

        def write_section(name: str, raw: bytes) -> None:
            path = result_directory / f"{safe_filename(name)}.json.zlib"
            sections[name] = write_artifact(path, raw)
            written_paths.append(path)

        write_section(
            "summary",
            _summary_projection(result).model_dump_json().encode("utf-8"),
        )
        write_section("temporal", _TEMPORAL_ADAPTER.dump_json(result.temporal))
        write_section(
            "causal_graph",
            result.causal_graph.model_dump_json().encode("utf-8"),
        )
        write_section(
            "causal_summary",
            result.causal_summary.model_dump_json().encode("utf-8"),
        )

        search_index = _build_search_index_payload(result.normalized_logs)
        search_sections: dict[str, Any] = {"values": search_index.pop("values")}
        for name, raw in search_index.items():
            path = result_directory / "search" / f"{safe_filename(name)}.bin.zlib"
            search_sections[name] = write_artifact(path, raw)
            written_paths.append(path)

        chunks: list[dict[str, Any]] = []
        for index, start in enumerate(
            range(0, len(result.normalized_logs), RESULT_LOG_CHUNK_SIZE)
        ):
            rows = result.normalized_logs[start : start + RESULT_LOG_CHUNK_SIZE]
            raw = _LOGS_ADAPTER.dump_json(
                rows,
                exclude=_PERSISTED_LOG_EXCLUDE,
            )
            path = result_directory / "logs" / f"{index:06d}.json.zlib"
            entry = write_artifact(path, raw)
            written_paths.append(path)
            # Rows arrive time-sorted, so each chunk covers a contiguous window;
            # recording it lets filtered reads skip chunks outside the requested
            # range without decompressing them.
            row_times = [row.timestamp for row in rows if row.timestamp is not None]
            chunks.append(
                {
                    **entry,
                    "start_offset": start,
                    "record_count": len(rows),
                    "window_start": min(row_times).isoformat() if row_times else None,
                    "window_end": max(row_times).isoformat() if row_times else None,
                }
            )
        return {
            "format": RESULT_MANIFEST_FORMAT,
            "version": RESULT_MANIFEST_VERSION,
            "case_id": result.case_id,
            "analysis_run_id": result.analysis_run_id,
            "sections": sections,
            "logs": {
                "total": len(result.normalized_logs),
                "chunk_size": RESULT_LOG_CHUNK_SIZE,
                "facets": result.log_facets,
                "chunks": chunks,
                "search_index": search_sections,
            },
        }
    except Exception:
        for path in reversed(written_paths):
            path.unlink(missing_ok=True)
        raise


def _artifact_path(entry: dict[str, Any], settings: Settings) -> Path:
    path = file_uri_to_path(str(entry.get("object_uri") or "")).resolve()
    root = Path(settings.local_object_store_dir).resolve()
    if path != root and root not in path.parents:
        raise ValueError("analysis result artifact is outside the object store")
    return path


def read_artifact(entry: dict[str, Any], *, settings: Settings) -> bytes:
    if entry.get("encoding") != RESULT_ARTIFACT_ENCODING:
        raise ValueError("unsupported analysis result artifact encoding")
    try:
        compressed = _artifact_path(entry, settings).read_bytes()
        if len(compressed) != int(entry.get("size_bytes") or -1):
            raise ValueError("analysis result artifact size mismatch")
        raw = zlib.decompress(compressed)
        if len(raw) != int(entry.get("uncompressed_size_bytes") or -1):
            raise ValueError("analysis result artifact expanded size mismatch")
        if hashlib.sha256(raw).hexdigest() != entry.get("sha256"):
            raise ValueError("analysis result artifact checksum mismatch")
        return raw
    except Exception as exc:
        if isinstance(exc, ValueError):
            raise
        raise ValueError("analysis result artifact is unreadable") from exc


def delete_analysis_result_artifacts(
    manifest: dict[str, Any],
    *,
    settings: Settings,
) -> None:
    entries = [
        *dict(manifest.get("sections") or {}).values(),
        *list(dict(manifest.get("logs") or {}).get("chunks") or []),
    ]
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        try:
            _artifact_path(entry, settings).unlink(missing_ok=True)
        except (OSError, ValueError):
            continue


def read_report_summary(
    manifest: dict[str, Any],
    *,
    settings: Settings,
) -> AnalysisReportSummary:
    raw = read_artifact(manifest["sections"]["summary"], settings=settings)
    return AnalysisReportSummary.model_validate_json(raw)


def read_temporal(
    manifest: dict[str, Any],
    *,
    settings: Settings,
) -> list[WindowAggregate]:
    raw = read_artifact(manifest["sections"]["temporal"], settings=settings)
    return _TEMPORAL_ADAPTER.validate_json(raw)


def read_causal_graph(
    manifest: dict[str, Any],
    *,
    settings: Settings,
) -> CausalGraph:
    raw = read_artifact(manifest["sections"]["causal_graph"], settings=settings)
    return CausalGraph.model_validate_json(raw)


def read_causal_summary(
    manifest: dict[str, Any],
    *,
    settings: Settings,
) -> CausalSummary:
    raw = read_artifact(manifest["sections"]["causal_summary"], settings=settings)
    return CausalSummary.model_validate_json(raw)


def iter_log_chunks(
    manifest: dict[str, Any],
    *,
    settings: Settings,
) -> Iterator[tuple[dict[str, Any], list[NormalizedLogLine]]]:
    for entry in manifest.get("logs", {}).get("chunks", []):
        raw = read_artifact(entry, settings=settings)
        yield entry, _LOGS_ADAPTER.validate_json(raw)


def chunk_overlaps_window(
    entry: dict[str, Any],
    *,
    window_start: datetime | None,
    window_end: datetime | None,
) -> bool:
    """Whether a chunk may contain rows inside the requested time window.

    Chunks without recorded bounds (older manifests, all-timestampless rows)
    are always scanned.
    """
    if window_start is None and window_end is None:
        return True
    chunk_start = entry.get("window_start")
    chunk_end = entry.get("window_end")
    if not chunk_start or not chunk_end:
        return True
    try:
        start = datetime.fromisoformat(chunk_start)
        end = datetime.fromisoformat(chunk_end)
    except ValueError:
        return True
    if window_start is not None and end < window_start:
        return False
    if window_end is not None and start > window_end:
        return False
    return True


def iter_matching_log_chunks(
    manifest: dict[str, Any],
    *,
    settings: Settings,
    window_start: datetime | None = None,
    window_end: datetime | None = None,
    text_needles: list[str] | None = None,
) -> Iterator[tuple[dict[str, Any], list[NormalizedLogLine]]]:
    """Yield decoded chunks that may contain matching rows.

    Time-window pruning uses the per-chunk bounds; text pruning searches the
    decompressed JSON bytes (case-insensitively, any needle matches) before
    paying for pydantic validation, so chunks without any occurrence never get
    validated. Callers searching text that can also match via joined data (for
    example template text, which is not persisted per row) must include the
    corresponding row-level needles such as the template ids.
    """
    needles = [needle.lower().encode("utf-8") for needle in text_needles or []]
    for entry in manifest.get("logs", {}).get("chunks", []):
        if not chunk_overlaps_window(
            entry, window_start=window_start, window_end=window_end
        ):
            continue
        raw = read_artifact(entry, settings=settings)
        if needles:
            lowered = raw.lower()
            if not any(needle in lowered for needle in needles):
                continue
        yield entry, _LOGS_ADAPTER.validate_json(raw)


def read_log_chunk(
    entry: dict[str, Any],
    *,
    settings: Settings,
) -> list[NormalizedLogLine]:
    raw = read_artifact(entry, settings=settings)
    return _LOGS_ADAPTER.validate_json(raw)


def _search_text(line: NormalizedLogLine) -> str:
    entity_values = " ".join(
        value for values in line.entities.values() for value in values
    )
    if entity_values:
        return f"{line.redacted_message}\x1f{entity_values}".lower()
    return line.redacted_message.lower()


def _code_array(values: list[str | None]) -> tuple[bytes, list[str | None]]:
    codes = array("i")
    code_by_value: dict[str | None, int] = {}
    ordered: list[str | None] = []
    for value in values:
        code = code_by_value.get(value)
        if code is None:
            code = len(ordered)
            code_by_value[value] = code
            ordered.append(value)
        codes.append(code)
    return codes.tobytes(), ordered


def _build_search_index_payload(logs: list[NormalizedLogLine]) -> dict[str, Any]:
    """Columnar per-row filter data persisted next to the log chunks.

    Rows arrive time-sorted with timestampless rows last, so the epoch array
    only covers the timestamped prefix and window filters reduce to bisects.
    """
    epochs = array("d")
    for line in logs:
        if line.timestamp is None:
            break
        epochs.append(line.timestamp.timestamp())

    offsets = array("Q", [0])
    blob_parts: list[bytes] = []
    total = 0
    for line in logs:
        encoded = _search_text(line).encode("utf-8", errors="replace")
        blob_parts.append(encoded)
        total += len(encoded) + 1
        offsets.append(total)

    service_codes, service_values = _code_array([line.service for line in logs])
    template_codes, template_values = _code_array([line.template_id for line in logs])
    signal_codes, signal_values = _code_array([line.golden_signal for line in logs])
    fault_codes, fault_values = _code_array(
        ["\x1f".join(line.fault_categories) for line in logs]
    )
    return {
        "blob": _SEARCH_ROW_SEPARATOR.join(blob_parts) + _SEARCH_ROW_SEPARATOR,
        "epochs": epochs.tobytes(),
        "offsets": offsets.tobytes(),
        "service_codes": service_codes,
        "template_codes": template_codes,
        "signal_codes": signal_codes,
        "fault_codes": fault_codes,
        "values": {
            "service": service_values,
            "template": template_values,
            "signal": signal_values,
            "fault": fault_values,
            "row_count": len(logs),
        },
    }


@dataclass
class LogSearchIndex:
    """In-memory filter columns for one run; the search blob stays on disk."""

    row_count: int
    epochs: array
    offsets: array
    service_codes: array
    template_codes: array
    signal_codes: array
    fault_codes: array
    service_values: list[str | None]
    template_values: list[str | None]
    signal_values: list[str | None]
    fault_values: list[str | None]
    blob_entry: dict[str, Any]


def load_search_index(
    manifest: dict[str, Any],
    *,
    settings: Settings,
) -> LogSearchIndex | None:
    sections = manifest.get("logs", {}).get("search_index")
    if not isinstance(sections, dict):
        return None
    values = sections.get("values") or {}

    def read_array(name: str, typecode: str) -> array:
        data = array(typecode)
        data.frombytes(read_artifact(sections[name], settings=settings))
        return data

    try:
        return LogSearchIndex(
            row_count=int(values.get("row_count") or 0),
            epochs=read_array("epochs", "d"),
            offsets=read_array("offsets", "Q"),
            service_codes=read_array("service_codes", "i"),
            template_codes=read_array("template_codes", "i"),
            signal_codes=read_array("signal_codes", "i"),
            fault_codes=read_array("fault_codes", "i"),
            service_values=list(values.get("service") or []),
            template_values=list(values.get("template") or []),
            signal_values=list(values.get("signal") or []),
            fault_values=list(values.get("fault") or []),
            blob_entry=dict(sections["blob"]),
        )
    except (KeyError, ValueError):
        return None


def search_blob_matches(
    index: LogSearchIndex,
    query: str,
    *,
    settings: Settings,
) -> set[int]:
    """Ordinals of rows whose search text contains the query (case-insensitive).

    Decompresses the pre-lowercased blob and scans it with bytes.find; the blob
    is never held beyond the call.
    """
    needle = query.lower().encode("utf-8", errors="replace")
    if not needle:
        return set()
    blob = read_artifact(index.blob_entry, settings=settings)
    matches: set[int] = set()
    offsets = index.offsets
    position = blob.find(needle)
    while position != -1:
        ordinal = bisect_right(offsets, position) - 1
        matches.add(ordinal)
        # Jump to the next row: rescanning inside an already-matched row would
        # produce duplicate ordinals without finding new rows.
        next_row_start = offsets[ordinal + 1] if ordinal + 1 < len(offsets) else len(blob)
        position = blob.find(needle, max(position + 1, next_row_start))
    return matches


def read_rows_by_ordinals(
    manifest: dict[str, Any],
    ordinals: list[int],
    *,
    settings: Settings,
    chunk_cache: dict[int, list[NormalizedLogLine]] | None = None,
) -> list[NormalizedLogLine]:
    """Fetch specific rows by their global position, decoding only the chunks
    that contain them (optionally through a caller-owned cache)."""
    chunks = manifest.get("logs", {}).get("chunks", [])
    chunk_size = int(manifest.get("logs", {}).get("chunk_size") or RESULT_LOG_CHUNK_SIZE)
    rows: list[NormalizedLogLine] = []
    for ordinal in ordinals:
        chunk_index = ordinal // chunk_size
        if chunk_index >= len(chunks):
            continue
        cached = chunk_cache.get(chunk_index) if chunk_cache is not None else None
        if cached is None:
            cached = read_log_chunk(chunks[chunk_index], settings=settings)
            if chunk_cache is not None:
                chunk_cache[chunk_index] = cached
        local = ordinal - chunk_index * chunk_size
        if 0 <= local < len(cached):
            rows.append(cached[local])
    return rows


def read_full_analysis_result(
    manifest: dict[str, Any],
    *,
    settings: Settings,
) -> AnalysisResult:
    summary = read_report_summary(manifest, settings=settings)
    normalized_logs = [
        line
        for _, rows in iter_log_chunks(manifest, settings=settings)
        for line in rows
    ]
    return AnalysisResult(
        case_id=summary.case_id,
        analysis_run_id=summary.analysis_run_id,
        files=summary.files,
        raw_entries=[],
        normalized_logs=normalized_logs,
        templates=summary.templates,
        samples=summary.samples,
        annotations=summary.annotations,
        temporal=read_temporal(manifest, settings=settings),
        causal_graph=read_causal_graph(manifest, settings=settings),
        causal_summary=read_causal_summary(manifest, settings=settings),
        log_facets=summary.log_facets,
        progress=summary.progress,
    )
