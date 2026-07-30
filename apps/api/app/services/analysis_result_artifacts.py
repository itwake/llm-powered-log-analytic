from __future__ import annotations

import hashlib
import uuid
import zlib
from collections.abc import Iterator
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
RESULT_LOG_CHUNK_SIZE = 10_000

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
        Path(settings.local_object_store_dir)
        / "cases"
        / safe_filename(case_id)
        / "analysis-runs"
        / safe_filename(analysis_run_id)
        / "result"
    )


def write_artifact(path: Path, raw: bytes) -> dict[str, Any]:
    compressed = zlib.compress(raw, level=1)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.part")
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
            chunks.append(
                {
                    **entry,
                    "start_offset": start,
                    "record_count": len(rows),
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


def read_log_chunk(
    entry: dict[str, Any],
    *,
    settings: Settings,
) -> list[NormalizedLogLine]:
    raw = read_artifact(entry, settings=settings)
    return _LOGS_ADAPTER.validate_json(raw)


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
