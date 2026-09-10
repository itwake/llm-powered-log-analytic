from __future__ import annotations

from datetime import UTC, datetime, timedelta

from logan_analysis.activities.causal import infer_causal_graph
from logan_analysis.models import LogTemplate, NormalizedLogLine


def _line(template_id: str, minute: int, service: str) -> NormalizedLogLine:
    return NormalizedLogLine(
        log_id=f"log-{template_id}-{minute}",
        raw_log_id=f"raw-{template_id}-{minute}",
        case_id="case-1",
        analysis_run_id="run-1",
        file_id="file-1",
        file_path="incident.log",
        line_number=minute + 1,
        line_numbers=[minute + 1],
        timestamp=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(minutes=minute),
        level="ERROR",
        service=service,
        message="error",
        normalized_message="error",
        redacted_message="error",
        template_id=template_id,
        template_text=f"{service} error",
        golden_signal="error",
        severity_score=0.8,
        confidence=0.9,
    )


def test_temporal_association_scores_earlier_signal() -> None:
    templates = [
        LogTemplate(
            template_id="source",
            template_key="source",
            template_text="database pool exhausted",
            normalized_template_text="database pool exhausted",
            occurrence_count=2,
        ),
        LogTemplate(
            template_id="target",
            template_key="target",
            template_text="gateway request failed",
            normalized_template_text="gateway request failed",
            occurrence_count=2,
        ),
    ]
    graph = infer_causal_graph(
        case_id="case-1",
        analysis_run_id="run-1",
        templates=templates,
        logs=[
            _line("source", 0, "payments"),
            _line("source", 1, "payments"),
            _line("target", 2, "gateway"),
            _line("target", 3, "gateway"),
        ],
        max_lag_seconds=300,
    )

    assert len(graph.nodes) == 2
    assert len(graph.edges) == 1
    edge = graph.edges[0]
    assert edge.source_template_id == "source"
    assert edge.target_template_id == "target"
    assert edge.method == "temporal_association"
    assert edge.support_windows == 2
    assert graph.root_cause_candidates[0].template_id == "source"
