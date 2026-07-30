from __future__ import annotations

import argparse
import asyncio
import ctypes
import json
import os
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from httpx import ASGITransport, AsyncClient

from app.config import Settings
from app.main import create_app
from app.models import tables
from app.services.analysis_result_artifacts import (
    RESULT_ARTIFACT_ENCODING,
    RESULT_LOG_CHUNK_SIZE,
    RESULT_MANIFEST_FORMAT,
    RESULT_MANIFEST_VERSION,
    write_artifact,
)
from app.sqlalchemy_store import SQLAlchemyStore


def _working_set_bytes() -> tuple[int | None, int | None]:
    if os.name != "nt":
        return None, None

    class ProcessMemoryCounters(ctypes.Structure):
        _fields_ = [
            ("cb", ctypes.c_ulong),
            ("PageFaultCount", ctypes.c_ulong),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
        ]

    counters = ProcessMemoryCounters()
    counters.cb = ctypes.sizeof(counters)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    kernel32.GetCurrentProcess.restype = ctypes.c_void_p
    psapi.GetProcessMemoryInfo.argtypes = [
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_ulong,
    ]
    psapi.GetProcessMemoryInfo.restype = ctypes.c_int
    process = kernel32.GetCurrentProcess()
    succeeded = psapi.GetProcessMemoryInfo(
        process,
        ctypes.byref(counters),
        counters.cb,
    )
    if not succeeded:
        return None, None
    return int(counters.WorkingSetSize), int(counters.PeakWorkingSetSize)


def _json_bytes(value: Any) -> bytes:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _section_payloads(
    *,
    case_id: str,
    run_id: str,
    record_count: int,
) -> dict[str, bytes]:
    evidence_ref = {
        "case_id": case_id,
        "analysis_run_id": run_id,
        "template_id": "template-error",
        "log_id": "log-0",
        "file_path": "synthetic.log",
        "line_number": 1,
        "timestamp": "2026-01-01T00:00:00Z",
    }
    template = {
        "template_id": "template-error",
        "template_key": "error-request",
        "template_text": "ERROR api request <*> failed",
        "normalized_template_text": "error api request <*> failed",
        "representative_log_id": "log-0",
        "occurrence_count": record_count,
        "first_seen": "2026-01-01T00:00:00Z",
        "last_seen": "2026-01-01T00:00:00Z",
        "services": ["api"],
        "files": ["synthetic.log"],
        "sample_values": {},
        "cluster_id": None,
    }
    annotation = {
        "annotation_id": "annotation-error",
        "template_id": "template-error",
        "analysis_run_id": run_id,
        "golden_signal": "error",
        "fault_categories": ["application"],
        "entities": {},
        "severity_score": 0.9,
        "confidence": 0.95,
        "rationale": "Synthetic benchmark annotation.",
    }
    summary = {
        "case_id": case_id,
        "analysis_run_id": run_id,
        "files": [],
        "templates": [template],
        "samples": [],
        "annotations": [annotation],
        "log_facets": {
            "service": {"api": record_count},
            "golden_signal": {"error": record_count},
            "fault_category": {"application": record_count},
        },
        "progress": {"raw_lines": record_count},
    }
    temporal = [
        {
            "window_start": "2026-01-01T00:00:00Z",
            "window_end": "2026-01-01T00:01:00Z",
            "window_size_seconds": 60,
            "template_id": "template-error",
            "service": "api",
            "golden_signal": "error",
            "fault_category": "application",
            "count": record_count,
        }
    ]
    causal_graph = {
        "nodes": [
            {
                "id": "node-error",
                "label": "ERROR api request failed",
                "template_id": "template-error",
                "golden_signal": "error",
                "fault_categories": ["application"],
                "occurrence_count": record_count,
                "first_seen": "2026-01-01T00:00:00Z",
                "last_seen": "2026-01-01T00:00:00Z",
                "rank_score": 0.9,
                "confidence": 0.95,
                "evidence_refs": [evidence_ref],
            }
        ],
        "edges": [],
        "root_cause_candidates": [
            {
                "template_id": "template-error",
                "rank": 1,
                "score": 0.9,
                "reason": "Synthetic benchmark candidate.",
            }
        ],
    }
    causal_summary = {
        "summary_markdown": "Synthetic benchmark incident summary.",
        "customer_update_markdown": "Synthetic benchmark customer update.",
        "next_actions": [
            {
                "action": "Inspect the synthetic error template.",
                "reason": "It is the highest-ranked causal candidate.",
            }
        ],
        "evidence_refs": [evidence_ref],
        "evidence_claims": [
            {
                "claim": "The synthetic error template is present in the run.",
                "evidence_refs": [evidence_ref],
            }
        ],
        "uncertainties": ["Synthetic data."],
        "details": {},
        "confidence": 0.5,
    }
    return {
        "summary": _json_bytes(summary),
        "temporal": _json_bytes(temporal),
        "causal_graph": _json_bytes(causal_graph),
        "causal_summary": _json_bytes(causal_summary),
    }


def _log_rows(
    *,
    case_id: str,
    run_id: str,
    start: int,
    count: int,
) -> list[dict[str, Any]]:
    return [
        {
            "log_id": f"log-{index}",
            "raw_log_id": f"raw-{index}",
            "case_id": case_id,
            "analysis_run_id": run_id,
            "file_id": "synthetic-file",
            "file_path": "synthetic.log",
            "line_number": index + 1,
            "line_numbers": [index + 1],
            "timestamp": "2026-01-01T00:00:00Z",
            "timestamp_quality": "parsed",
            "level": "ERROR",
            "service": "api",
            "redacted_message": f"request {index} failed password=<SECRET>",
            "parser_name": "benchmark",
            "parser_confidence": 1.0,
            "ingestion_order": index,
            "template_id": "template-error",
            "golden_signal": "error",
            "fault_categories": ["application"],
            "entities": {},
            "severity_score": 0.9,
            "confidence": 0.95,
        }
        for index in range(start, start + count)
    ]


def _build_manifest(
    *,
    root: Path,
    case_id: str,
    run_id: str,
    record_count: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    result_directory = root / "cases" / case_id / "analysis-runs" / run_id / "result"
    sections = {
        name: write_artifact(result_directory / f"{name}.json.zlib", raw)
        for name, raw in _section_payloads(
            case_id=case_id,
            run_id=run_id,
            record_count=record_count,
        ).items()
    }
    chunks = []
    started = time.perf_counter()
    for chunk_index, start in enumerate(range(0, record_count, RESULT_LOG_CHUNK_SIZE)):
        count = min(RESULT_LOG_CHUNK_SIZE, record_count - start)
        raw = _json_bytes(
            _log_rows(
                case_id=case_id,
                run_id=run_id,
                start=start,
                count=count,
            )
        )
        entry = write_artifact(
            result_directory / "logs" / f"{chunk_index:06d}.json.zlib",
            raw,
        )
        chunks.append(
            {
                **entry,
                "start_offset": start,
                "record_count": count,
            }
        )
        if (chunk_index + 1) % 20 == 0:
            print(
                f"generated {start + count:,}/{record_count:,} rows",
                flush=True,
            )
    manifest = {
        "format": RESULT_MANIFEST_FORMAT,
        "version": RESULT_MANIFEST_VERSION,
        "case_id": case_id,
        "analysis_run_id": run_id,
        "sections": sections,
        "logs": {
            "total": record_count,
            "chunk_size": RESULT_LOG_CHUNK_SIZE,
            "facets": {
                "service": {"api": record_count},
                "golden_signal": {"error": record_count},
                "fault_category": {"application": record_count},
            },
            "chunks": chunks,
        },
    }
    entries = [*sections.values(), *chunks]
    metrics = {
        "generation_seconds": round(time.perf_counter() - started, 3),
        "chunk_count": len(chunks),
        "compressed_bytes": sum(int(entry["size_bytes"]) for entry in entries),
        "uncompressed_bytes": sum(
            int(entry["uncompressed_size_bytes"]) for entry in entries
        ),
        "encoding": RESULT_ARTIFACT_ENCODING,
    }
    return manifest, metrics


_REQUIRED_LOG_KEYS = {
    "log_id",
    "timestamp",
    "level",
    "service",
    "file_path",
    "line_number",
    "line_numbers",
    "message",
    "template_id",
    "template_text",
    "golden_signal",
    "fault_categories",
    "entities",
}


def _validate_response_bodies(
    bodies: dict[str, dict[str, Any]],
    *,
    case_id: str,
    run_id: str,
    record_count: int,
) -> tuple[dict[str, Any], dict[str, bool], list[str]]:
    run = bodies["run"]
    summary = bodies["summary"]
    timeline = bodies["timeline"]
    logs_first = bodies["logs_first_page"]
    logs_last = bodies["logs_last_page"]
    graph = bodies["graph"]
    rca = bodies["rca"]

    summary_items = list(summary.get("items") or [])
    timeline_series = list(timeline.get("series") or [])
    timeline_points = [
        point
        for series in timeline_series
        for point in list(series.get("points") or [])
    ]
    first_items = list(logs_first.get("items") or [])
    last_items = list(logs_last.get("items") or [])
    graph_nodes = list(graph.get("nodes") or [])
    graph_edges = list(graph.get("edges") or [])
    graph_candidates = list(graph.get("root_cause_candidates") or [])
    next_actions = list(rca.get("next_actions") or [])
    evidence_refs = list(rca.get("evidence_refs") or [])

    summary_template_ids = {item.get("template_id") for item in summary_items}
    graph_node_ids = {node.get("id") for node in graph_nodes}
    graph_template_ids = {node.get("template_id") for node in graph_nodes}
    first_log_ids = {item.get("log_id") for item in first_items}
    last_log_ids = {item.get("log_id") for item in last_items}
    all_log_items = [*first_items, *last_items]

    expected_last_first_line = max(record_count - 199, 1)
    page_boundaries_match = bool(first_items and last_items)
    if page_boundaries_match:
        page_boundaries_match = (
            first_items[0].get("line_number") == 1
            and last_items[0].get("line_number") == expected_last_first_line
        )
    if record_count >= 400:
        page_boundaries_match = page_boundaries_match and first_log_ids.isdisjoint(
            last_log_ids
        )

    checks = {
        "run_completed": (
            run.get("status") == "completed"
            and run.get("current_step") == "completed"
            and run.get("error_message") is None
        ),
        "run_progress_matches_record_count": (
            run.get("progress", {}).get("raw_lines") == record_count
            and run.get("progress", {}).get("normalized_lines") == record_count
        ),
        "summary_total_matches_items": summary.get("total") == len(summary_items),
        "summary_contains_templates": bool(summary_items and summary_template_ids),
        "summary_reduction_matches_record_count": (
            summary.get("reduction", {}).get("raw_log_lines") == record_count
        ),
        "timeline_contains_positive_counts": (
            bool(timeline_points)
            and all(
                isinstance(point.get("count"), int) and point["count"] > 0
                for point in timeline_points
            )
        ),
        "timeline_count_matches_record_count": (
            sum(int(point.get("count") or 0) for point in timeline_points)
            == record_count
        ),
        "logs_totals_match_record_count": (
            logs_first.get("total") == record_count
            and logs_last.get("total") == record_count
        ),
        "logs_pages_have_expected_size": (
            len(first_items) == min(record_count, 200)
            and len(last_items) == min(record_count, 200)
        ),
        "logs_pages_have_required_fields": all(
            _REQUIRED_LOG_KEYS <= set(item) for item in all_log_items
        ),
        "logs_pages_have_unique_ids": (
            len(first_log_ids) == len(first_items)
            and len(last_log_ids) == len(last_items)
        ),
        "logs_page_boundaries_match_offsets": page_boundaries_match,
        "logs_messages_are_redacted": all(
            isinstance(item.get("message"), str)
            and "<SECRET>" in item["message"]
            for item in all_log_items
        ),
        "logs_templates_exist_in_summary": all(
            item.get("template_id") in summary_template_ids for item in all_log_items
        ),
        "graph_contains_nodes_and_candidates": bool(
            graph_nodes and graph_candidates
        ),
        "graph_edges_reference_returned_nodes": all(
            edge.get("source") in graph_node_ids
            and edge.get("target") in graph_node_ids
            for edge in graph_edges
        ),
        "graph_candidates_reference_returned_templates": all(
            candidate.get("template_id") in graph_template_ids
            for candidate in graph_candidates
        ),
        "graph_templates_exist_in_summary": graph_template_ids <= summary_template_ids,
        "rca_contains_summary_and_customer_update": bool(
            str(rca.get("summary_markdown") or "").strip()
            and str(rca.get("customer_update_markdown") or "").strip()
        ),
        "rca_contains_next_actions": bool(next_actions),
        "rca_contains_evidence": bool(evidence_refs),
        "rca_evidence_references_this_run": all(
            evidence.get("case_id") == case_id
            and evidence.get("analysis_run_id") == run_id
            for evidence in evidence_refs
        ),
        "rca_evidence_references_known_templates": all(
            evidence.get("template_id") is None
            or evidence.get("template_id") in graph_template_ids
            for evidence in evidence_refs
        ),
        "rca_evidence_references_returned_logs": all(
            evidence.get("log_id") in first_log_ids | last_log_ids
            for evidence in evidence_refs
        ),
        "rca_confidence_is_bounded": (
            isinstance(rca.get("confidence"), (int, float))
            and 0 <= rca["confidence"] <= 1
        ),
    }
    failed_checks = [name for name, passed in checks.items() if not passed]
    metrics = {
        "run_status": run.get("status"),
        "run_current_step": run.get("current_step"),
        "summary_total": summary.get("total"),
        "summary_raw_log_lines": summary.get("reduction", {}).get("raw_log_lines"),
        "timeline_series": len(timeline_series),
        "timeline_points": len(timeline_points),
        "timeline_total_count": sum(
            int(point.get("count") or 0) for point in timeline_points
        ),
        "logs_first_total": logs_first.get("total"),
        "logs_first_items": len(first_items),
        "logs_last_total": logs_last.get("total"),
        "logs_last_items": len(last_items),
        "graph_nodes": len(graph_nodes),
        "graph_edges": len(graph_edges),
        "graph_candidates": len(graph_candidates),
        "rca_next_actions": len(next_actions),
        "rca_evidence_refs": len(evidence_refs),
        "rca_confidence": rca.get("confidence"),
    }
    return metrics, checks, failed_checks


async def _benchmark(record_count: int) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(
        prefix="logan-report-benchmark-",
        ignore_cleanup_errors=True,
    ) as temporary:
        root = Path(temporary)
        settings = Settings(
            database_path=str(root / "logan.db"),
            local_object_store_dir=str(root / "object-store"),
        )
        store = SQLAlchemyStore(
            app_settings=settings,
            database_path=settings.database_path,
            create_schema=True,
        )
        user = store.register_user(
            email="benchmark@example.com",
            username="benchmark",
            full_name="Report Benchmark",
        )
        token, _ = store.create_session(user.id)
        case = store.create_case(user_id=user.id, data={"title": "Report benchmark"})
        run = store.create_analysis_run(case_id=case.id, user_id=user.id)
        manifest, artifact_metrics = _build_manifest(
            root=Path(settings.local_object_store_dir),
            case_id=case.id,
            run_id=run.id,
            record_count=record_count,
        )
        with store._session() as session:
            run_row = session.get(tables.AnalysisRun, run.id)
            run_row.status = "completed"
            run_row.result_json = manifest
            run_row.progress_json = {
                "current_step": "completed",
                "raw_lines": record_count,
                "normalized_lines": record_count,
            }
            run_row.completed_at = datetime.now(UTC)
            case_row = session.get(tables.Case, case.id)
            case_row.status = "completed"

        app = create_app(store=store)
        endpoints = {
            "run": f"/api/cases/{case.id}/analysis-runs/{run.id}",
            "summary": f"/api/cases/{case.id}/analysis-runs/{run.id}/summary",
            "timeline": f"/api/cases/{case.id}/analysis-runs/{run.id}/temporal",
            "logs_first_page": (
                f"/api/cases/{case.id}/analysis-runs/{run.id}/logs?offset=0&limit=200"
            ),
            "logs_last_page": (
                f"/api/cases/{case.id}/analysis-runs/{run.id}/logs"
                f"?offset={record_count - 200}&limit=200"
            ),
            "graph": f"/api/cases/{case.id}/analysis-runs/{run.id}/causal-graph",
            "rca": f"/api/cases/{case.id}/analysis-runs/{run.id}/causal-summary",
        }
        timings: dict[str, Any] = {}
        bodies: dict[str, dict[str, Any]] = {}
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://benchmark",
            cookies={"logan_session": token},
        ) as client:
            for name, path in endpoints.items():
                working_set_before, _ = _working_set_bytes()
                started = time.perf_counter()
                response = await client.get(path)
                elapsed = time.perf_counter() - started
                working_set_after, process_peak = _working_set_bytes()
                response.raise_for_status()
                body = response.json()
                if not isinstance(body, dict):
                    raise ValueError(f"{name} response body must be an object")
                bodies[name] = body
                timings[name] = {
                    "seconds": round(elapsed, 4),
                    "response_bytes": len(response.content),
                    "working_set_before": working_set_before,
                    "working_set_after": working_set_after,
                    "process_peak_working_set": process_peak,
                    "returned_items": (
                        len(body.get("items", [])) if isinstance(body, dict) else None
                    ),
                    "reported_total": (
                        body.get("total") if isinstance(body, dict) else None
                    ),
                }
        body_metrics, body_checks, failed_body_checks = _validate_response_bodies(
            bodies,
            case_id=case.id,
            run_id=run.id,
            record_count=record_count,
        )
        store.engine.dispose()
        return {
            "records": record_count,
            "artifact_metrics": artifact_metrics,
            "endpoints": timings,
            "body_metrics": body_metrics,
            "body_checks": body_checks,
            "failed_body_checks": failed_body_checks,
        }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Benchmark report APIs against a chunked synthetic result.",
    )
    parser.add_argument("--records", type=int, default=2_000_000)
    args = parser.parse_args()
    if args.records < 200:
        parser.error("--records must be at least 200")
    result = asyncio.run(_benchmark(args.records))
    print(json.dumps(result, indent=2), flush=True)
    if result["failed_body_checks"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
