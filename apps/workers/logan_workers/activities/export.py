from __future__ import annotations

import html
import json
import uuid

from logan_workers.models import AnalysisResult, ExportArtifact


def export_analysis(result: AnalysisResult, export_type: str) -> ExportArtifact:
    export_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{result.analysis_run_id}:{export_type}"))
    if export_type == "markdown":
        content = result.causal_summary.summary_markdown
    elif export_type == "html":
        content = (
            "<!doctype html><html><head><meta charset=\"utf-8\"><title>LogAn Export</title></head>"
            "<body><main><pre>"
            + html.escape(result.causal_summary.summary_markdown)
            + "</pre></main></body></html>"
        )
    elif export_type == "json":
        content = json.dumps(
            {
                "case_id": result.case_id,
                "analysis_run_id": result.analysis_run_id,
                "summary": result.causal_summary.model_dump(mode="json"),
                "causal_graph": result.causal_graph.model_dump(mode="json"),
                "data_summary": [
                    template.model_dump(mode="json")
                    for template in result.templates
                    if any(
                        log.template_id == template.template_id
                        and log.golden_signal
                        in {"error", "availability", "latency", "saturation", "traffic"}
                        for log in result.normalized_logs
                    )
                ],
            },
            indent=2,
            sort_keys=True,
        )
    else:
        raise ValueError(f"unsupported export type: {export_type}")
    return ExportArtifact(
        export_id=export_id,
        export_type=export_type,  # type: ignore[arg-type]
        content=content,
        object_uri=f"memory://exports/{result.analysis_run_id}/{export_id}.{export_type}",
    )
