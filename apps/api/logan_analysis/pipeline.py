from __future__ import annotations

from collections.abc import Awaitable, Callable
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

from logan_analysis.activities.broadcasting import broadcast_annotations
from logan_analysis.activities.causal import infer_causal_graph
from logan_analysis.activities.inference import annotate_templates
from logan_analysis.activities.ingestion import ingest_paths
from logan_analysis.activities.preprocessing import merge_entries, preprocess_entries
from logan_analysis.activities.sampling import select_samples
from logan_analysis.activities.summary import render_causal_summary
from logan_analysis.activities.templating import extract_templates
from logan_analysis.activities.temporal_aggregation import build_time_window_aggregates
from logan_analysis.models import AnalysisResult
from logan_analysis.ports import ModelGateway

ProgressCallback = Callable[[dict[str, Any]], Awaitable[None] | None]
MAX_ANNOTATION_TEMPLATES = 64
MAX_SAMPLE_MESSAGE_CHARS = 1200
MAX_SAMPLES_PER_TEMPLATE = 3


def _update_progress(
    progress: dict[str, Any],
    *,
    step_name: str,
    status: str,
    metadata: dict[str, Any] | None = None,
    error_message: str | None = None,
) -> None:
    details = metadata or {}
    steps = progress.setdefault("steps", {})
    step = dict(steps.get(step_name, {}))
    step["status"] = status
    timestamp_name = "started_at" if status == "processing" else f"{status}_at"
    step[timestamp_name] = datetime.now(UTC).isoformat()
    if details:
        step["details"] = details
        progress.update(details)
    if error_message:
        step["error_message"] = error_message
        progress["error_message"] = error_message
    steps[step_name] = step
    progress["current_step"] = (
        "completed" if step_name == "causal_summary" and status == "completed" else step_name
    )


class AnalyzeCasePipeline:
    async def run(
        self,
        *,
        case_id: str,
        analysis_run_id: str,
        paths: list[str],
        case_context: dict[str, Any] | None = None,
        gateway: ModelGateway | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> AnalysisResult:
        case_context = {
            "case_id": case_id,
            "analysis_run_id": analysis_run_id,
            **(case_context or {}),
        }
        progress: dict[str, Any] = {"current_step": "queued", "steps": {}}
        async def update_step(
            *,
            step_name: str,
            status: str,
            metadata: dict[str, Any] | None = None,
            error_message: str | None = None,
        ) -> None:
            _update_progress(
                progress,
                step_name=step_name,
                status=status,
                metadata=metadata,
                error_message=error_message,
            )
            if progress_callback is None:
                return
            callback_result = progress_callback(deepcopy(progress))
            if isinstance(callback_result, Awaitable):
                await callback_result

        async def run_step(
            step_name: str,
            action: Callable[[], Any] | Callable[[], Awaitable[Any]],
            metadata: Callable[[Any], dict[str, Any]],
        ) -> Any:
            await update_step(step_name=step_name, status="processing")
            try:
                value = action()
                if isinstance(value, Awaitable):
                    value = await value
            except Exception as exc:
                await update_step(
                    step_name=step_name,
                    status="failed",
                    error_message=str(exc),
                )
                raise
            await update_step(
                step_name=step_name,
                status="completed",
                metadata=metadata(value),
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
            ),
            lambda value: {"normalized_lines": len(value)},
        )
        normalized, templates = await run_step(
            "template_extraction",
            lambda: extract_templates(
                case_id=case_id,
                analysis_run_id=analysis_run_id,
                logs=normalized,
            ),
            lambda value: {"normalized_lines": len(value[0]), "templates": len(value[1])},
        )
        samples = await run_step(
            "representative_sampling",
            lambda: select_samples(
                normalized,
                templates,
                max_samples_per_template=MAX_SAMPLES_PER_TEMPLATE,
            ),
            lambda value: {"samples": len(value)},
        )
        if gateway is None:
            annotations = []
            await update_step(
                step_name="ai_platform_annotation",
                status="skipped",
                metadata={
                    "llm_enabled": False,
                    "annotations": 0,
                    "annotation_templates_total": len(templates),
                    "annotation_templates_selected": 0,
                },
            )
        else:
            annotations = await run_step(
                "ai_platform_annotation",
                lambda: annotate_templates(
                    analysis_run_id=analysis_run_id,
                    templates=templates,
                    samples=samples,
                    case_context=case_context,
                    gateway=gateway,
                    max_sample_message_chars=MAX_SAMPLE_MESSAGE_CHARS,
                    max_samples_per_template=MAX_SAMPLES_PER_TEMPLATE,
                    max_templates=MAX_ANNOTATION_TEMPLATES,
                ),
                lambda value: {
                    "llm_enabled": True,
                    "annotations": len(value),
                    "annotation_templates_total": len(templates),
                    "annotation_templates_selected": len(value),
                    "annotation_budget": MAX_ANNOTATION_TEMPLATES,
                },
            )
        enriched = await run_step(
            "broadcast_annotations",
            lambda: broadcast_annotations(normalized, annotations),
            lambda value: {"annotated_lines": len(value)},
        )
        temporal = await run_step(
            "temporal_aggregation",
            lambda: build_time_window_aggregates(enriched),
            lambda value: {"windows": len(value)},
        )
        causal_graph = await run_step(
            "causal_graph",
            lambda: infer_causal_graph(
                case_id=case_id,
                analysis_run_id=analysis_run_id,
                templates=templates,
                logs=enriched,
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
        return AnalysisResult(
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
