from __future__ import annotations

from typing import Any

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
    ) -> AnalysisResult:
        config = config or {}
        case_context = {
            "case_id": case_id,
            "analysis_run_id": analysis_run_id,
            **(case_context or {}),
        }
        files = ingest_paths(paths)
        raw_entries = merge_entries(files)
        normalized = preprocess_entries(
            case_id=case_id,
            analysis_run_id=analysis_run_id,
            entries=raw_entries,
            redaction_mode=config.get("redaction", {}).get("mode", "mask"),
        )
        normalized, templates = run_drain_templating(
            case_id=case_id,
            analysis_run_id=analysis_run_id,
            logs=normalized,
        )
        samples = select_samples(normalized, templates)
        annotations, model_inputs = await annotate_templates(
            analysis_run_id=analysis_run_id,
            templates=templates,
            samples=samples,
            case_context=case_context,
            gateway=gateway,
        )
        enriched = broadcast_annotations(normalized, annotations)
        temporal = build_time_window_aggregates(
            enriched,
            window_size_seconds=config.get("default_window_size_seconds"),
        )
        causal_graph = infer_causal_graph(
            case_id=case_id,
            analysis_run_id=analysis_run_id,
            templates=templates,
            logs=enriched,
            max_lag_seconds=config.get("causal", {}).get("max_lag_seconds", 600),
        )
        causal_summary = render_causal_summary(
            causal_graph=causal_graph,
            templates=templates,
            logs=enriched,
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
                "files_total": len(files),
                "files_processed": len(files),
                "raw_lines": sum(len(file.lines) for file in files),
                "normalized_lines": len(enriched),
                "templates": len(templates),
                "representative_samples": len(samples),
                "annotated_templates": len(annotations),
            },
        )
        exports = {
            export_type: export_analysis(placeholder, export_type)
            for export_type in ("markdown", "html", "json")
        }
        return placeholder.model_copy(update={"exports": exports})
