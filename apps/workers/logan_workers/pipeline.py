from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from typing import Any

from app.observability import (
    record_pipeline_run_completed,
    record_pipeline_run_failed,
    record_pipeline_run_started,
    record_pipeline_step_completed,
    record_pipeline_step_failed,
    record_pipeline_step_started,
)
from logan_workers.activities.broadcasting import broadcast_annotations
from logan_workers.activities.causal import infer_causal_graph
from logan_workers.activities.export import export_analysis
from logan_workers.activities.inference import MockCopilotAnnotationGateway, annotate_templates
from logan_workers.activities.ingestion import ingest_paths
from logan_workers.activities.preprocessing import merge_entries, preprocess_entries
from logan_workers.activities.sampling import select_samples
from logan_workers.activities.summary import render_causal_summary
from logan_workers.activities.temporal_aggregation import build_time_window_aggregates
from logan_workers.activities.templating import run_drain_templating
from logan_workers.models import AnalysisResult


ProgressCallback = Callable[[dict[str, Any]], Awaitable[None] | None]


def _event_status(event_type: str) -> str:
    if event_type == "started":
        return "processing"
    if event_type == "failed":
        return "failed"
    return "completed"


def _merge_progress(progress: dict[str, Any], event: dict[str, Any]) -> None:
    step_name = str(event["step_name"])
    event_type = str(event["event_type"])
    metadata = event.get("metadata") if isinstance(event.get("metadata"), dict) else {}
    steps = progress.setdefault("steps", {})
    step = dict(steps.get(step_name, {}))
    step["status"] = event["status"]
    step["attempt"] = event["attempt"]
    step[f"{event_type}_at"] = event["created_at"]
    if metadata:
        step["metadata"] = metadata
        progress.update(metadata)
        if "files" in metadata:
            progress["files_total"] = metadata["files"]
            progress["files_processed"] = metadata["files"]
        if "samples" in metadata:
            progress["representative_samples"] = metadata["samples"]
        if "annotations" in metadata:
            progress["annotated_templates"] = metadata["annotations"]
    if event.get("error_message"):
        step["error_message"] = event["error_message"]
        progress["error_message"] = event["error_message"]
    steps[step_name] = step
    progress["current_step"] = (
        "completed"
        if step_name == "export_artifacts" and event_type == "completed"
        else step_name
    )


class AnalyzeCasePipeline:
    async def run(
        self,
        *,
        case_id: str,
        analysis_run_id: str,
        paths: list[str],
        case_context: dict[str, Any] | None = None,
        config: dict[str, Any] | None = None,
        gateway: MockCopilotAnnotationGateway | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> AnalysisResult:
        record_pipeline_run_started()
        try:
            result = await self._run_core(
                case_id=case_id,
                analysis_run_id=analysis_run_id,
                paths=paths,
                case_context=case_context,
                config=config,
                gateway=gateway,
                progress_callback=progress_callback,
            )
        except Exception:
            record_pipeline_run_failed()
            raise
        record_pipeline_run_completed()
        return result

    async def _run_core(
        self,
        *,
        case_id: str,
        analysis_run_id: str,
        paths: list[str],
        case_context: dict[str, Any] | None = None,
        config: dict[str, Any] | None = None,
        gateway: MockCopilotAnnotationGateway | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> AnalysisResult:
        config = config or {}
        case_context = {
            "case_id": case_id,
            "analysis_run_id": analysis_run_id,
            **(case_context or {}),
        }
        gateway = gateway or MockCopilotAnnotationGateway()
        progress: dict[str, Any] = {"current_step": "queued", "steps": {}}

        async def emit(
            *,
            step_name: str,
            event_type: str,
            metadata: dict[str, Any] | None = None,
            error_message: str | None = None,
            attempt: int = 1,
        ) -> None:
            from datetime import UTC, datetime

            event = {
                "case_id": case_id,
                "analysis_run_id": analysis_run_id,
                "step_name": step_name,
                "event_type": event_type,
                "status": _event_status(event_type),
                "attempt": attempt,
                "idempotency_key": f"{step_name}:attempt:{attempt}",
                "metadata": metadata or {},
                "error_message": error_message,
                "created_at": datetime.now(UTC).isoformat(),
            }
            _merge_progress(progress, event)
            if progress_callback is None:
                return
            callback_result = progress_callback(event)
            if isinstance(callback_result, Awaitable):
                await callback_result

        async def run_step(
            step_name: str,
            action: Callable[[], Any] | Callable[[], Awaitable[Any]],
            metadata: Callable[[Any], dict[str, Any]],
        ) -> Any:
            record_pipeline_step_started(step_name)
            step_started_at = time.perf_counter()
            await emit(step_name=step_name, event_type="started")
            try:
                value = action()
                if isinstance(value, Awaitable):
                    value = await value
            except Exception as exc:
                record_pipeline_step_failed(
                    step_name,
                    time.perf_counter() - step_started_at,
                )
                await emit(
                    step_name=step_name,
                    event_type="failed",
                    error_message=str(exc),
                )
                raise
            await emit(
                step_name=step_name,
                event_type="completed",
                metadata=metadata(value),
            )
            record_pipeline_step_completed(
                step_name,
                time.perf_counter() - step_started_at,
            )
            return value

        files = await run_step(
            "ingest_paths",
            lambda: ingest_paths(paths),
            lambda value: {
                "files": len(value),
                "raw_lines": sum(len(file.lines) for file in value),
            },
        )
        raw_entries = await run_step(
            "merge_entries",
            lambda: merge_entries(files),
            lambda value: {"raw_entries": len(value), "raw_lines": len(value)},
        )
        normalized = await run_step(
            "preprocess_redact",
            lambda: preprocess_entries(
                case_id=case_id,
                analysis_run_id=analysis_run_id,
                entries=raw_entries,
                redaction_mode=config.get("redaction", {}).get("mode", "mask"),
            ),
            lambda value: {"normalized_lines": len(value)},
        )
        normalized, templates = await run_step(
            "drain_templating",
            lambda: run_drain_templating(
                case_id=case_id,
                analysis_run_id=analysis_run_id,
                logs=normalized,
            ),
            lambda value: {"normalized_lines": len(value[0]), "templates": len(value[1])},
        )
        samples = await run_step(
            "representative_sampling",
            lambda: select_samples(normalized, templates),
            lambda value: {"samples": len(value)},
        )
        annotations, model_inputs = await run_step(
            "copilot_annotation",
            lambda: annotate_templates(
                analysis_run_id=analysis_run_id,
                templates=templates,
                samples=samples,
                case_context=case_context,
                gateway=gateway,
            ),
            lambda value: {"annotations": len(value[0])},
        )
        enriched = await run_step(
            "broadcast_annotations",
            lambda: broadcast_annotations(normalized, annotations),
            lambda value: {"annotated_lines": len(value)},
        )
        temporal = await run_step(
            "temporal_aggregation",
            lambda: build_time_window_aggregates(
                enriched,
                window_size_seconds=config.get("default_window_size_seconds"),
            ),
            lambda value: {"windows": len(value)},
        )
        causal_graph = await run_step(
            "causal_graph",
            lambda: infer_causal_graph(
                case_id=case_id,
                analysis_run_id=analysis_run_id,
                templates=templates,
                logs=enriched,
                max_lag_seconds=config.get("causal", {}).get("max_lag_seconds", 600),
                time_bin_seconds=config.get("causal", {}).get("time_bin_seconds", 60),
                methods=config.get("causal", {}).get("methods"),
                granger_max_lag_bins=config.get("causal", {}).get("granger_max_lag_bins"),
            ),
            lambda value: {"nodes": len(value.nodes), "edges": len(value.edges)},
        )
        causal_summary = await run_step(
            "causal_summary",
            lambda: render_causal_summary(
                causal_graph=causal_graph,
                templates=templates,
                logs=enriched,
                case_context=case_context,
                gateway=gateway,
            ),
            lambda value: {
                "next_actions": len(value.next_actions),
                "evidence_refs": len(value.evidence_refs),
                "summary_source": value.details.get("source"),
            },
        )
        placeholder = AnalysisResult(
            case_id=case_id,
            analysis_run_id=analysis_run_id,
            files=files,
            raw_entries=raw_entries,
            normalized_logs=enriched,
            templates=templates,
            samples=samples,
            annotations=annotations,
            temporal=temporal,
            causal_graph=causal_graph,
            causal_summary=causal_summary,
            exports={},
            model_inputs=model_inputs,
            progress={
                **progress,
                "files_total": len(files),
                "files_processed": len(files),
                "raw_lines": sum(len(file.lines) for file in files),
                "normalized_lines": len(enriched),
                "templates": len(templates),
                "representative_samples": len(samples),
                "annotated_templates": len(annotations),
                "windows": len(temporal),
                "nodes": len(causal_graph.nodes),
                "edges": len(causal_graph.edges),
            },
        )
        exports = await run_step(
            "export_artifacts",
            lambda: {
                export_type: export_analysis(placeholder, export_type)
                for export_type in ("markdown", "html", "json")
            },
            lambda value: {"exports": len(value), "export_types": sorted(value)},
        )
        final_progress = {
            **placeholder.progress,
            **progress,
            "files_total": len(files),
            "files_processed": len(files),
            "raw_lines": sum(len(file.lines) for file in files),
            "normalized_lines": len(enriched),
            "templates": len(templates),
            "representative_samples": len(samples),
            "annotated_templates": len(annotations),
            "windows": len(temporal),
            "nodes": len(causal_graph.nodes),
            "edges": len(causal_graph.edges),
            "exports": len(exports),
        }
        return placeholder.model_copy(update={"exports": exports, "progress": final_progress})
