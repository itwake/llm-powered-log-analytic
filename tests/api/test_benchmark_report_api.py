from __future__ import annotations

import pytest

from scripts.benchmark_report_api import _benchmark


@pytest.mark.asyncio
async def test_report_benchmark_validates_response_bodies() -> None:
    result = await _benchmark(400)

    assert result["failed_body_checks"] == []
    assert all(result["body_checks"].values())
    assert result["body_metrics"] == {
        "run_status": "completed",
        "run_current_step": "completed",
        "summary_total": 1,
        "summary_raw_log_lines": 400,
        "timeline_series": 1,
        "timeline_points": 1,
        "timeline_total_count": 400,
        "logs_first_total": 400,
        "logs_first_items": 200,
        "logs_last_total": 400,
        "logs_last_items": 200,
        "graph_nodes": 1,
        "graph_edges": 0,
        "graph_candidates": 1,
        "rca_next_actions": 1,
        "rca_evidence_refs": 1,
        "rca_confidence": 0.5,
    }
