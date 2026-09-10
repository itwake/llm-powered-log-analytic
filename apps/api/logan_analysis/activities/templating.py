from __future__ import annotations

from logan_analysis.algorithms.template_extractor import TemplateExtractor
from logan_analysis.models import LogTemplate, NormalizedLogLine


def extract_templates(
    *,
    case_id: str,
    analysis_run_id: str,
    logs: list[NormalizedLogLine],
) -> tuple[list[NormalizedLogLine], list[LogTemplate]]:
    return TemplateExtractor().cluster(
        case_id=case_id,
        analysis_run_id=analysis_run_id,
        logs=logs,
    )
